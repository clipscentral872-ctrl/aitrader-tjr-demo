"""Do slower timeframes help, and is the reason the one we think it is?

The BTC discovery pointed here. At a 0.05% stop with 0.06% round-trip costs,
every trade was charged 1.2R before it started. Costs are a fixed fraction of
notional; risk is the stop distance. So the cost burden is decided entirely by
how wide the stop is, and stop width is decided by the timeframe.

A five-minute swing on EURUSD might be 4 pips. A four-hour swing might be 40.
Same fees either way, so the four-hour trade carries a tenth of the drag.

TJR says the concepts apply everywhere, which makes this a fair test rather
than a different strategy:

    "all of our confluences show up on every single time frame"

The honest caution: slower timeframes give fewer trades, so confidence
intervals widen fast. A better-looking number on 200 trades instead of 2,000
may just be a noisier number. Both are reported.

    python timeframe_study.py --market eurusd
    python timeframe_study.py --market btc --all
"""
import argparse, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run
from backtest.guard import assess, Ledger
from data.fetch import resample
from evaluate import get_data
from tjr_study import SESSIONS

TFS = ["5min", "15min", "30min", "1h", "2h", "4h"]


def study(market, session=None, min_stop=0.05, ledger=None, quiet=False):
    df, costs, ms, _ = get_data(market)
    if df is None or df.empty:
        print(f"  no data for {market}")
        return []
    filt = SESSIONS.get(session) if session else None
    led = ledger or Ledger()
    rows = []

    if not quiet:
        print(f"\n  {market.upper()}   {len(df):,} five-minute bars   "
              f"{df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}")
        print(f"  {'timeframe':>10} {'bars':>9} {'trades':>7} {'mean R':>9} "
              f"{'win %':>7} {'cost/R':>8} {'stop %':>8}")

    for tf in TFS:
        d = df if tf == "5min" else resample(df, tf)
        if len(d) < 2000:
            if not quiet:
                print(f"  {tf:>10} {len(d):>9}   too few bars")
            continue

        # a session window on a 4-hour bar is meaningless: one bar spans the
        # whole session, so the filter is dropped above 30 minutes
        use_filt = filt if tf in ("5min", "15min", "30min") else None

        cfg = Config(min_stop_pct=min_stop, max_stop_pct=max(4.0, min_stop * 20),
                     min_rr=3.0, max_rr=5.0, htf_bias=True,
                     require_real_draw=True, require_premium=True)
        s = find_setups(d, cfg, session_filter=use_filt)
        if not s:
            if not quiet:
                print(f"  {tf:>10} {len(d):>9}   no setups")
            continue
        tr, _ = bt_run(d, s, costs)
        if len(tr) < 20:
            if not quiet:
                print(f"  {tf:>10} {len(d):>9} {len(tr):>7}   too few trades")
            continue

        r = np.array([t.r for t in tr])
        cr = float(np.mean([t.cost_r for t in tr]))
        sp = float(np.mean([abs(t.entry - t.stop) / t.entry * 100 for t in tr]))
        if not quiet:
            print(f"  {tf:>10} {len(d):>9} {len(r):>7} {r.mean():>+9.3f} "
                  f"{(r > 0).mean()*100:>7.1f} {cr:>8.3f} {sp:>8.3f}")
        rows.append((market, tf, len(r), float(r.mean()), cr, sp, list(r)))
        led.record(market, f"{tf} timeframe")
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="eurusd")
    ap.add_argument("--all", action="store_true", help="every market we hold")
    ap.add_argument("--min-stop", type=float, default=0.05)
    a = ap.parse_args()

    print("=" * 78)
    print("  DOES SLOWING DOWN HELP, AND IS IT THE COSTS")
    print("=" * 78)

    markets = ([("eurusd", "engine default (09:30-12:30 NY)"),
                ("qqq", "TJR NY open only (08:30-11:30)"),
                ("spy", "TJR NY open only (08:30-11:30)"),
                ("btc", None)]
               if a.all else [(a.market, None)])

    led = Ledger()
    led.reset()
    allrows = []
    for m, sess in markets:
        allrows += study(m, sess, a.min_stop, led)

    if not allrows:
        print("\n  nothing to compare")
        return

    # ---- does the cost story actually hold up? ---------------------------
    print("\n" + "-" * 78)
    print("  IS THE IMPROVEMENT EXPLAINED BY COSTS FALLING?")
    print("  If yes, mean R should rise by roughly the amount cost/R falls.\n")
    for m in dict.fromkeys(x[0] for x in allrows):
        rows = [x for x in allrows if x[0] == m]
        if len(rows) < 2:
            continue
        base = rows[0]
        print(f"  {m.upper()}  (against {base[1]})")
        for r in rows[1:]:
            d_mean = r[3] - base[3]
            d_cost = base[4] - r[4]
            unexplained = d_mean - d_cost
            print(f"    {r[1]:>6}  mean {d_mean:+.3f}R   cost saved {d_cost:+.3f}R"
                  f"   unexplained {unexplained:+.3f}R")
        print()

    # ---- the best of them, judged honestly --------------------------------
    print("-" * 78)
    print("  THE BEST ONES, CHARGED FOR THE SEARCH\n")
    best = sorted(allrows, key=lambda x: -x[3])[:5]
    for m, tf, n, mean, cr, sp, rs in best:
        v = assess(rs, dataset=m, label=f"{tf}", ledger=led)
        tag = "CLEARS THE BAR" if v.is_edge else "inside its own noise"
        print(f"  {m:<8} {tf:>6} {n:>6} trades {mean:>+8.3f}R   {tag}")
        if not v.is_edge:
            print(f"           {v.detail}")

    print("\n" + "=" * 78)
    print(f"  {led.count(best[0][0])} timeframes tested per market. A slower")
    print("  timeframe that looks better on a tenth of the trades may simply be")
    print("  a noisier estimate. The confidence interval, not the mean, decides.")
    print("=" * 78)


if __name__ == "__main__":
    main()
