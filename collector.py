"""Harvest futures data daily and build history that outlives the free window.

Yahoo only serves a rolling 60 days of 5-minute bars. Run this once a day and it
merges each fresh window into a permanent store, so after three months of
collecting we have five months of history instead of the two we can ever see at
one time. That is the free route to the sample size the backtest needs.

Safe to run repeatedly: bars are keyed by timestamp and de-duplicated, so an
extra run costs nothing and a missed day only loses that day if we are away for
more than 60 days.

    python collector.py            # collect the default symbols
    python collector.py --status   # what we have so far
"""
import argparse, os, sys, time
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.fetch import yahoo   # noqa: E402

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "store")
os.makedirs(STORE, exist_ok=True)

SYMBOLS = {
    "NQ=F": "nq",     # Nasdaq 100 futures - TJR's instrument
    "ES=F": "es",     # S&P 500 futures
    "GC=F": "gc",     # gold, a sanity check on a different market
}
INTERVALS = ["5m", "15m"]


def path(tag, interval):
    return os.path.join(STORE, f"{tag}_{interval}.parquet")


def merge(tag, interval, fresh):
    """Add new bars to the permanent store, keeping whatever we already had."""
    p = path(tag, interval)
    if os.path.exists(p):
        old = pd.read_parquet(p)
        before = len(old)
        combined = pd.concat([old, fresh])
    else:
        before = 0
        combined = fresh
    combined = combined[~combined.index.duplicated(keep="last")].sort_index()
    combined.to_parquet(p)
    return before, len(combined), len(combined) - before


def collect(quiet=False):
    added_any = 0
    for sym, tag in SYMBOLS.items():
        for iv in INTERVALS:
            rng = "60d" if iv == "5m" else "60d"
            try:
                fresh = yahoo(sym, iv, rng)
            except Exception as e:
                print(f"  {tag} {iv}: fetch failed - {type(e).__name__}", flush=True)
                continue
            if fresh.empty:
                print(f"  {tag} {iv}: empty response", flush=True)
                continue
            before, after, added = merge(tag, iv, fresh)
            added_any += added
            if not quiet:
                span = ""
                if after:
                    d = pd.read_parquet(path(tag, iv))
                    span = f"  {d.index[0]:%Y-%m-%d} -> {d.index[-1]:%Y-%m-%d}"
                print(f"  {tag} {iv}: {before:,} -> {after:,} bars  (+{added}){span}",
                      flush=True)
            time.sleep(1)
    return added_any


def status():
    rows = []
    for sym, tag in SYMBOLS.items():
        for iv in INTERVALS:
            p = path(tag, iv)
            if not os.path.exists(p):
                rows.append((tag, iv, 0, "-", "-", 0))
                continue
            d = pd.read_parquet(p)
            days = (d.index[-1] - d.index[0]).days
            rows.append((tag, iv, len(d), f"{d.index[0]:%Y-%m-%d}",
                         f"{d.index[-1]:%Y-%m-%d}", days))
    print(f"  {'sym':<5} {'tf':<4} {'bars':>9} {'from':>12} {'to':>12} {'days':>6}")
    for r in rows:
        print(f"  {r[0]:<5} {r[1]:<4} {r[2]:>9,} {r[3]:>12} {r[4]:>12} {r[5]:>6}")
    print()
    # the number that matters: how close are we to a testable sample?
    best = max((r[5] for r in rows), default=0)
    print(f"  longest history: {best} days")
    if best < 90:
        print(f"  need roughly {90 - best} more days before a train/test split is honest")
    else:
        print("  enough span to split train/test - worth re-running the analysis")


def load(tag="nq", interval="5m"):
    """Read the accumulated store for backtesting."""
    p = path(tag, interval)
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        status()
    else:
        print(f"collecting  {pd.Timestamp.utcnow():%Y-%m-%d %H:%M} UTC", flush=True)
        n = collect()
        print(f"\n  {n:,} new bars stored")
        print()
        status()
