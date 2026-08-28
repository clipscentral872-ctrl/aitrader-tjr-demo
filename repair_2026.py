"""Repair the 2026 pull: rescale it, and rebuild the 5-minute bars properly.

TWO FAULTS, STACKED
-------------------
1. SCALE. Dukascopy quotes these index feeds divided by 100. The 2025 files
   were rescaled by hand when this was first found; the fetcher was never
   taught the correction, so the new 2026 pull came in raw. Stored Nasdaq read
   295.85 against a live 29,620, and S&P 77.18 against 7,739: 100.1x and 100.3x.

2. RESAMPLING. The merge built five-minute bars with
   `bars["close"].resample("5min").ohlc()`, which derives open/high/low/close
   from the CLOSE SERIES ALONE. The high became the highest close rather than
   the highest price, so every intrabar extreme was discarded and mean range
   collapsed from 15.33 points to 0.17.

Together they produced an average of -1.9R per trade on a strategy whose stop
sits at -1R, which is arithmetically impossible and is what gave the game away.

The one-minute files are intact, so this rebuilds from them rather than
re-downloading two hours of ticks.

    python repair_2026.py
"""
import functools
import os
import sys

print = functools.partial(print, flush=True)

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
STORE = os.path.join(ROOT, "data", "store")

from data.fetch import resample   # noqa: E402  the correct OHLC aggregation

# what each index should actually quote at, so a rescale is verifiable
JOBS = [
    ("nasdaq_duka_1m.parquet", "nasdaq_duka_5m.parquet", 8_000, 60_000, "Nasdaq"),
    ("sp500_duka_1m.parquet",  "sp500_duka_5m.parquet",  2_000, 12_000, "S&P 500"),
]
OHLC = ["open", "high", "low", "close"]


def main():
    for f1, f5, lo, hi, label in JOBS:
        p1, p5 = os.path.join(STORE, f1), os.path.join(STORE, f5)
        if not os.path.exists(p1):
            print(f"{label}: {f1} missing, skipping")
            continue

        one = pd.read_parquet(p1)
        last = float(one["close"].iloc[-1])

        # ---- 1. scale ------------------------------------------------
        if last < lo:
            factor = 100.0
            one[OHLC] = one[OHLC] * factor
            one.to_parquet(p1)
            print(f"{label}: rescaled 1-minute x{factor:g}  "
                  f"{last:,.2f} -> {float(one['close'].iloc[-1]):,.2f}")
        else:
            print(f"{label}: 1-minute already in range at {last:,.2f}")

        # ---- 2. rebuild the five-minute bars from real OHLC ----------
        five_new = resample(one, "5min")
        if os.path.exists(p5):
            old = pd.read_parquet(p5)
            keep = old[old.index < five_new.index[0]]   # drop the bad merge
            merged = pd.concat([keep, five_new]).sort_index()
            merged = merged[~merged.index.duplicated(keep="first")]
        else:
            merged = five_new
        merged.to_parquet(p5)

        # ---- 3. verify the join is continuous ------------------------
        cut = five_new.index[0]
        before = merged[merged.index < cut]
        after = merged[merged.index >= cut]
        rb = (before["high"] - before["low"]).mean() if len(before) else float("nan")
        ra = (after["high"] - after["low"]).mean()
        print(f"  5-minute rebuilt: {len(merged):,} bars, "
              f"{merged.index[0].date()} to {merged.index[-1].date()}")
        print(f"  mean range before the join {rb:>7.2f}   after {ra:>7.2f}   "
              f"ratio {ra / rb if rb == rb and rb else float('nan'):.2f}")
        if rb == rb and rb > 0 and not (0.5 < ra / rb < 2.0):
            print(f"  WARNING: ranges still differ by more than 2x across the join")
        print()

    print("done. run `python audit.py` next: its price-scale check covers exactly")
    print("this failure and would have caught it before the comparison ran.")


if __name__ == "__main__":
    main()
