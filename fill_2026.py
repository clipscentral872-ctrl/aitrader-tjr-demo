"""Fetch 2026 at ONE-MINUTE resolution, so every timeframe is derivable.

WHY 2026 AT ALL
---------------
Every backtest in this project stops at 2025-12-31, which is 240 days stale.
A method trading short intraday slots should be judged on the current regime,
and the years demonstrably differ: on London+NY with the current config, 2023
gives +0.072R (not clearing zero), 2024 +0.192R, 2025 +0.247R. That spread is
3.7 standard errors, well beyond noise.

WHY ONE MINUTE AND NOT FIVE
---------------------------
The puller fetches TICKS and resamples, so the network cost is identical at any
output resolution. But resampling only ever goes coarser. One-minute bars give
5-minute, 15-minute and hourly for free; five-minute bars can never give back
the minute. Step 4 of the method enters on the one-minute chart, so storing
only 5-minute would have quietly removed the entry timeframe for 2026 and we
would have had to fetch the whole range again.

Written as 1-minute files, and ALSO resampled into the existing 5-minute
series so code that already reads those keeps working.

Sequential on purpose: two concurrent Dukascopy pulls starved each other
earlier in this project, and a throttled request returns EMPTY rather than
failing, so a starved job looks like a finished one with missing hours.
"""
import functools
import os
import sys
import time

print = functools.partial(print, flush=True)

import datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from data.dukascopy_pull import pull, STORE   # noqa: E402

JOBS = [
    ("nasdaq", "USATECHIDXUSD", "nasdaq_duka_1m.parquet", "nasdaq_duka_5m.parquet"),
    ("sp500",  "USA500IDXUSD",  "sp500_duka_1m.parquet",  "sp500_duka_5m.parquet"),
]
START, END = "2026-01-01", "2026-08-28"


def main():
    for label, sym, out_1m, out_5m in JOBS:
        p1 = os.path.join(STORE, out_1m)
        if os.path.exists(p1):
            have = pd.read_parquet(p1)
            if have.index[-1].date() >= dt.date(2026, 8, 20):
                print(f"{label}: 1-minute already to {have.index[-1].date()}, skipping")
                continue

        print(f"\n{label}: fetching {START} to {END} at ONE MINUTE ...")
        t0 = time.time()
        try:
            bars = pull(sym, START, END, "1min", workers=16)
        except Exception as e:
            print(f"  failed: {type(e).__name__}: {str(e)[:90]}")
            continue
        if bars is None or bars.empty:
            print("  returned nothing (throttled?)")
            continue

        # a weekday minute-bar count, to catch a throttled pull that came back
        # sparse rather than erroring
        days = len(pd.bdate_range(START, END))
        cov = len(bars) / (days * 24 * 60)
        mins = (time.time() - t0) / 60
        print(f"  {len(bars):,} one-minute bars, coverage {cov*100:.0f}%, {mins:.0f} min")
        if cov < 0.40:
            print("  REJECTED: too sparse to trust, likely throttled")
            continue

        bars.to_parquet(p1)
        print(f"  stored 1-minute: {bars.index[0].date()} to {bars.index[-1].date()}")

        # and fold the 5-minute view into the existing series
        five = bars["close"].resample("5min").ohlc().dropna()
        five["volume"] = bars.get("volume", bars["close"]).resample("5min").sum()
        p5 = os.path.join(STORE, out_5m)
        if os.path.exists(p5):
            old = pd.read_parquet(p5)
            merged = pd.concat([old, five]).sort_index()
            merged = merged[~merged.index.duplicated(keep="first")]
        else:
            merged = five
        merged.to_parquet(p5)
        print(f"  merged 5-minute: {len(merged):,} bars, "
              f"{merged.index[0].date()} to {merged.index[-1].date()}")

    print("\nDONE")


if __name__ == "__main__":
    main()
