"""Accumulate high resolution history for free, a day at a time.

THE IDEA
--------
Yahoo will not sell you five years of one-minute bars, and nobody free will. But
it hands out the last few days of one-minute data on every request, for nothing.
Ask every day and append, and after a month you own a month of one-minute
history that no single request could ever have given you. After a year, a year.

That is the whole trick. The store only ever grows, and bars already in it are
never overwritten by a later fetch, so a bad or partial pull cannot corrode
history that was already good.

WHAT IT WILL NOT DO
-------------------
It cannot go back. Whatever was not collected before today is gone at one-minute
resolution, and the gaps already in the Dukascopy series stay there. This starts
the clock; it does not rewind it.

    python collect_bars.py            top up everything
    python collect_bars.py --report   say what is held, collect nothing
"""
import argparse
import functools
import os
import sys

print = functools.partial(print, flush=True)

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "data", "collected")

# What to ask for, and how far back each request reaches. The windows are
# Yahoo's own limits: ask for more and it returns nothing at all.
WANT = [
    ("NQ", "NQ=F", "1m", "7d"),
    ("NQ", "NQ=F", "5m", "60d"),
    ("NQ", "NQ=F", "1h", "730d"),
    ("NQ", "NQ=F", "1d", "2y"),
    ("ES", "ES=F", "1m", "7d"),
    ("ES", "ES=F", "5m", "60d"),
    ("ES", "ES=F", "1h", "730d"),
    ("ES", "ES=F", "1d", "2y"),
]
COLS = ["open", "high", "low", "close"]


def path_for(sym, tf):
    return os.path.join(OUT, f"{sym}_{tf}.parquet")


def load(sym, tf):
    p = path_for(sym, tf)
    if not os.path.exists(p):
        return None
    d = pd.read_parquet(p)
    if d.index.tz is None:
        d.index = d.index.tz_localize("UTC")
    return d


def merge(old, new):
    """Old bars win. A later partial pull must never rewrite good history."""
    if old is None or old.empty:
        return new.sort_index()
    both = pd.concat([old, new])
    both = both[~both.index.duplicated(keep="first")]
    return both.sort_index()


def report():
    print(f"{'symbol':<8} {'tf':<5} {'bars':>9}  {'from':<12} {'to':<12}  days")
    print("-" * 62)
    any_held = False
    for sym, _, tf, _ in WANT:
        d = load(sym, tf)
        if d is None or d.empty:
            print(f"{sym:<8} {tf:<5} {'-':>9}  nothing collected yet")
            continue
        any_held = True
        days = (d.index[-1] - d.index[0]).days
        print(f"{sym:<8} {tf:<5} {len(d):>9,}  {str(d.index[0].date()):<12} "
              f"{str(d.index[-1].date()):<12}  {days}")
    if not any_held:
        print("\nNothing yet. Run without --report to start collecting.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--report", action="store_true", help="show what is held")
    a = ap.parse_args()

    os.makedirs(OUT, exist_ok=True)
    if a.report:
        report()
        return

    from data.fetch import yahoo
    grew = 0
    for sym, feed, tf, window in WANT:
        try:
            fresh = yahoo(feed, tf, window, max_age=0)
        except Exception as e:
            print(f"  {sym} {tf}: fetch failed ({type(e).__name__})")
            continue
        if fresh is None or fresh.empty:
            print(f"  {sym} {tf}: nothing came back")
            continue

        fresh = fresh[[c for c in COLS if c in fresh.columns]].dropna()
        if fresh.index.tz is None:
            fresh.index = fresh.index.tz_localize("UTC")

        old = load(sym, tf)
        before = 0 if old is None else len(old)
        both = merge(old, fresh)
        added = len(both) - before
        both.to_parquet(path_for(sym, tf))
        grew += added
        span = (both.index[-1] - both.index[0]).days
        print(f"  {sym} {tf:<3} +{added:>6,} new   {len(both):>9,} held   "
              f"{span:>4}d   to {both.index[-1].date()}")

    print(f"\n{grew:,} new bars. Store: {OUT}")
    if grew == 0:
        print("Nothing new, which is normal if you already collected today.")


if __name__ == "__main__":
    main()
