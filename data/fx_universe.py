"""Pull the other FX pairs, which is the last idea with real headroom.

EURUSD is the only market where this strategy works. Every US equity tested is
negative, Bitcoin is negative, and combining them produced a losing portfolio.
So the multi-market thesis is not dead in general, it is dead for equities. It
has never been tested where the edge actually lives.

If GBPUSD and USDJPY behave like EURUSD, trade count multiplies and so does
income. If they do not, then the EURUSD result is one market out of six and
should be treated as the coin flip it probably is. Either answer is worth
having and neither is available without the data.

One practical hazard, learned the hard way: Dukascopy throttles. An earlier
availability check reported seven pairs as having no data at all, purely
because a concurrent download was saturating the connection. Retried with a
second between requests, all seven returned normally. A throttled request
returns EMPTY rather than failing, so silent gaps are the real danger here, and
every pull is checked for coverage before it is stored.

    python data/fx_universe.py --check
    python data/fx_universe.py --pull --years 2022 2026
"""
import argparse, os, sys
import datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from data.dukascopy_pull import pull, STORE

PAIRS = ["GBPUSD", "USDJPY", "USDCHF", "AUDUSD", "USDCAD",
         "NZDUSD", "EURGBP", "GBPJPY", "AUDJPY", "XAUUSD"]


def path_for(sym):
    return os.path.join(STORE, f"{sym.lower()}_5m_duka.parquet")


def coverage(df, start, end):
    """What fraction of expected weekday hours actually came back.

    A throttled request returns nothing rather than erroring, so a pull can
    look successful and be full of holes. This is the check that catches it.
    """
    if df is None or df.empty:
        return 0.0
    d0, d1 = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    weekdays = sum(1 for i in range((d1 - d0).days)
                   if (d0 + dt.timedelta(days=i)).weekday() < 5)
    expected = weekdays * 24 * 12          # 12 five-minute bars an hour
    return len(df) / expected if expected else 0.0


def pull_pair(sym, start, end, workers=12, min_coverage=0.80):
    print(f"\n{sym}  {start} -> {end}", flush=True)
    try:
        bars = pull(sym, start, end, "5min", workers=workers)
    except Exception as e:
        print(f"  failed: {type(e).__name__}: {str(e)[:70]}")
        return None
    cov = coverage(bars, start, end)
    print(f"  {len(bars):,} bars, coverage {cov*100:.0f}%", flush=True)
    if cov < min_coverage:
        print(f"  REJECTED: under {min_coverage*100:.0f}% coverage, which means")
        print("  throttled requests came back empty. Not storing a holed series.")
        return None
    return bars


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--years", nargs=2, default=["2022", "2026"])
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()

    if a.check:
        from data.dukascopy_pull import fetch_hour
        import time
        d = dt.date(2023, 6, 13)
        print("availability, one request per pair with spacing:\n")
        for sym in PAIRS:
            try:
                t = fetch_hour(sym, d, 10)
                n = len(t) if t is not None else 0
            except Exception:
                n = 0
            print(f"  {sym:<8} {n:>7,} ticks")
            time.sleep(1.2)
        return

    if not a.pull:
        for sym in PAIRS:
            p = path_for(sym)
            if os.path.exists(p):
                df = pd.read_parquet(p)
                print(f"  {sym:<8} {len(df):>8,} bars  "
                      f"{df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}")
            else:
                print(f"  {sym:<8} not downloaded")
        return

    y0, y1 = int(a.years[0]), int(a.years[1])
    for sym in PAIRS:
        p = path_for(sym)
        if os.path.exists(p):
            print(f"\n{sym}: already stored, skipping")
            continue
        frames = []
        for year in range(y0, y1):
            b = pull_pair(sym, f"{year}-01-01", f"{year + 1}-01-01",
                          workers=a.workers)
            if b is not None and not b.empty:
                frames.append(b)
        if not frames:
            print(f"  {sym}: nothing usable")
            continue
        merged = pd.concat(frames).sort_index()
        merged = merged[~merged.index.duplicated(keep="first")]
        merged.to_parquet(p)
        print(f"  {sym}: stored {len(merged):,} bars", flush=True)


if __name__ == "__main__":
    main()
