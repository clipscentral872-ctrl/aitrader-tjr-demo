"""His actual rule: floor 1.3, let the good ones run to 1.5-2.2.

The target is a liquidity pool, so R:R lands where the pool sits; the floor
refuses anything closer and the cap stops a fantasy target. This measures that
band, and the safe position size that comes with it.

Safe size matters more than it looks. His screenshot risks $750, which is 1.5%
of a $50k account. At a 0.5R target the win rate is ~80% and the worst losing
streak is short, so 1.3%+ survives. In this band the win rate falls to ~50%,
streaks get longer, and the same 1.5% may not survive a 10% drawdown limit.
"""
import functools
print = functools.partial(print, flush=True)
import numpy as np, pandas as pd
from engine.strategy import Config, find_setups
from backtest.engine import run as bt_run
from backtest import bootstrap
from data.fetch import resample
from tjr_exact import TJR, window
from futures import costs_for

m5 = resample(pd.read_parquet("data/store/nsxusd_1m.parquet"), "5min")
cut = int(len(m5) * 0.6)
costs = costs_for("MNQ")
EQUITY = 50_000

BANDS = [("1.3 - 1.8", 1.3, 1.8),
         ("1.3 - 2.2  (his)", 1.3, 2.2),
         ("1.5 - 2.2", 1.5, 2.2),
         ("0.5  (today)", 0.4, 0.5)]

for wname, wf in (("full NY 09:30-16:00", window(9, 30, 16, 0)),
                  ("his window 09:45-10:30", window(9, 45, 10, 30))):
    print(f"\n{wname}")
    print(f"  {'band':<20} {'seg':>6} {'trades':>7} {'exp R':>8} {'win %':>7} "
          f"{'streak':>7} {'safe %':>7} {'$/day @safe':>12} {'$/day @1.5%':>12}")
    for label, mn, mx in BANDS:
        cfg = Config(**{**TJR, "min_rr": mn, "max_rr": mx})
        for tag, seg in (("train", m5.iloc[:cut]), ("TEST", m5.iloc[cut:])):
            s = find_setups(seg, cfg, session_filter=wf)
            if not s:
                print(f"  {label:<20} {tag:>6}   no setups"); continue
            tr, _ = bt_run(seg, s, costs)
            if len(tr) < 20:
                print(f"  {label:<20} {tag:>6} {len(tr):>7}   too few"); continue
            r = np.array([t.r for t in tr])
            yrs = (seg.index[-1] - seg.index[0]).days / 365.25
            per_day = len(r) / yrs / 252
            # worst run of consecutive losers actually observed
            streak = mx_s = 0
            for x in r:
                streak = streak + 1 if x <= 0 else 0
                mx_s = max(mx_s, streak)
            safe = bootstrap.risk_for_drawdown(list(r), 10.0) if r.mean() > 0 else 0.0
            d_safe = EQUITY * (safe / 100) * r.mean() * per_day
            d_fixed = EQUITY * 0.015 * r.mean() * per_day
            print(f"  {label:<20} {tag:>6} {len(r):>7} {r.mean():>+7.3f} "
                  f"{(r > 0).mean() * 100:>6.1f}% {mx_s:>7} {safe:>6.2f}% "
                  f"${d_safe:>11,.0f} ${d_fixed:>11,.0f}")
print("\nDONE")
