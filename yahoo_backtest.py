"""Backtest on the consolidated tape, which is the only clean US feed we have.

Every US equity result in this project was measured on Alpaca's free tier. That
feed serves IEX only, a small slice of volume, and on the same symbol over the
same window it produced -0.206R where the consolidated tape produced +0.005R.
A strategy that enters on wicks through levels cannot be tested on a feed that
under-reports extremes.

Yahoo carries the consolidated tape but only sixty days of five-minute history,
which on one symbol is far too few trades to judge anything.

The fix is breadth rather than depth. Sixty days across twenty liquid US symbols
is twenty independent sixty-day samples, pooled. That is not as good as twenty
years of one symbol, because sixty days is one market regime, but it is the
difference between forty trades and several hundred, and it is measured on a
feed that reports what actually traded.

    python yahoo_backtest.py
"""
import argparse, os, sys, time
import functools
print = functools.partial(print, flush=True)
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run, Costs
from backtest.guard import assess, Ledger
from backtest import bootstrap
from data.fetch import yahoo
from tjr_study import SESSIONS

SYMBOLS = ["QQQ", "SPY", "IWM", "DIA", "XLK", "XLF", "XLE", "SMH", "EEM", "EFA",
           "GLD", "SLV", "TLT", "HYG", "VNQ", "XBI", "XLV", "XLI", "XLU", "XLP"]

ETF = Costs(maker_pct=0.0, taker_pct=0.0, slip_pct=0.01)


def fetch_all(symbols, pause=0.6):
    out = {}
    for s in symbols:
        try:
            df = yahoo(s, "5m", "60d")
        except Exception as e:
            print(f"  {s:<6} failed: {type(e).__name__}")
            continue
        if df is None or len(df) < 1500:
            print(f"  {s:<6} only {0 if df is None else len(df)} bars, skipping")
            continue
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        out[s] = df
        print(f"  {s:<6} {len(df):>6,} bars  {df.index[0]:%Y-%m-%d} -> "
              f"{df.index[-1]:%Y-%m-%d}")
        time.sleep(pause)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--session", default="TJR New York (08:30-18:00)")
    ap.add_argument("--min-stop", type=float, default=0.05)
    a = ap.parse_args()

    print("=" * 80)
    print("  CONSOLIDATED TAPE BACKTEST")
    print("  60 days each, pooled across many symbols, on a feed that reports")
    print("  what actually traded rather than one exchange's slice.")
    print("=" * 80)
    print(f"\n  downloading {len(SYMBOLS)} symbols ...\n")
    data = fetch_all(SYMBOLS)
    if len(data) < 5:
        print(f"\n  only {len(data)} symbols came back; not enough to pool")
        return

    filt = SESSIONS.get(a.session)
    cfg = Config(min_stop_pct=a.min_stop, max_stop_pct=1.5,
                 min_rr=0.4, max_rr=0.5, htf_bias=True,
                 require_real_draw=True, require_premium=True)

    print(f"\n  window: {a.session}\n")
    print(f"  {'symbol':<8} {'bars':>7} {'setups':>7} {'trades':>7} "
          f"{'exp R':>9} {'win %':>7}")
    pooled, per_symbol = [], {}
    for s, df in data.items():
        st = find_setups(df, cfg, session_filter=filt)
        if not st:
            print(f"  {s:<8} {len(df):>7,} {0:>7}")
            continue
        tr, _ = bt_run(df, st, ETF)
        if not tr:
            print(f"  {s:<8} {len(df):>7,} {len(st):>7} {0:>7}")
            continue
        r = np.array([t.r for t in tr])
        per_symbol[s] = r
        pooled.extend(r.tolist())
        print(f"  {s:<8} {len(df):>7,} {len(st):>7} {len(r):>7} "
              f"{r.mean():>+8.3f} {(r > 0).mean()*100:>6.1f}%")

    if len(pooled) < 60:
        print(f"\n  only {len(pooled)} trades pooled, too few to judge")
        return

    arr = np.array(pooled)
    print("\n" + "-" * 80)
    print("  POOLED ACROSS EVERY SYMBOL")
    print(f"    {len(arr)} trades from {len(per_symbol)} symbols over 60 days")
    print(f"    expectancy {arr.mean():+.3f}R   win rate {(arr > 0).mean()*100:.1f}%")

    led = Ledger()
    v = assess(list(arr), dataset="yahoo_pooled", label="consolidated tape",
               ledger=led)
    print(f"\n    {v.headline}")
    print(f"    {v.detail}")

    # how many symbols are individually positive: a pooled mean can be one
    # symbol carrying nineteen, which is the trap the trend basket fell into
    pos = sum(1 for r in per_symbol.values() if r.mean() > 0)
    print(f"\n    symbols positive on their own: {pos} of {len(per_symbol)}")
    if pos < len(per_symbol) * 0.5:
        print("    Fewer than half. The pooled figure is being carried by a")
        print("    minority, so treat it as one result rather than twenty.")

    if arr.mean() > 0:
        safe = bootstrap.risk_for_drawdown(list(arr), 10.0)
        print(f"\n    largest risk keeping 95% of paths inside 10%: {safe}%")

    print("\n" + "=" * 80)
    print("  CAVEAT THAT CANNOT BE ENGINEERED AWAY: sixty days is one market")
    print("  regime. Twenty symbols multiply the trades, not the number of")
    print("  independent market conditions observed. This says what the clean")
    print("  feed shows recently, not what it shows across a cycle.")
    print("=" * 80)


if __name__ == "__main__":
    main()
