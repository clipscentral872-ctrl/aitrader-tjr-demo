"""Does the 1-minute entry lose because of the stop, or because of the idea?

His window produced 37.8% wins on the 1-minute against 77.5% on the 5-minute.
Same setups, same session, same market. A win rate that halves while nothing
else changes points at the stop, not the edge.

The old code anchored the stop to a four-bar one-minute range. That is a noise
band. TJR uses the one-minute to get a BETTER ENTRY; the level that invalidates
the trade is structural and lives on the five-minute. This tests both.

Scanning starts 09:45, not 09:50: he begins hunting confirmation there and
takes the trade when all four steps are present, so a late confirmation is
allowed to complete rather than being cut off at the bell.
"""
import functools, sys
print = functools.partial(print, flush=True)
import numpy as np, pandas as pd
from engine.strategy import Config, find_setups
from engine.multiframe import find_setups_mtf
from backtest.engine import run as bt_run
from backtest import bootstrap
from data.fetch import resample
from tjr_exact import TJR, window
from futures import costs_for

m1 = pd.read_parquet("data/store/nsxusd_1m.parquet")
m5 = resample(m1, "5min")
c1, c5 = int(len(m1) * 0.6), int(len(m5) * 0.6)
costs = costs_for("MNQ")
cfg = Config(**TJR)
sess = window(9, 45, 10, 30)

print(f"index {float(m1['close'].iloc[-1]):,.2f}   MNQ costs   scan from 09:45 ET")
print(f"{'stop anchored to':<26} {'seg':>6} {'trades':>7} {'exp R':>8} "
      f"{'win %':>7} {'cost/R':>7} {'$/day 50k':>10}")

for label, mode in (("1m band (old)", "ltf"), ("5m structure (his)", "structural")):
    for tag, lo, hi in (("train", m1.iloc[:c1], m5.iloc[:c5]),
                        ("TEST", m1.iloc[c1:], m5.iloc[c5:])):
        s = find_setups_mtf(lo, hi, cfg, session_filter=sess, stop_mode=mode)
        if not s:
            print(f"{label:<26} {tag:>6}   no setups"); continue
        tr, _ = bt_run(lo, s, costs)
        if len(tr) < 15:
            print(f"{label:<26} {tag:>6} {len(tr):>7}   too few"); continue
        r = np.array([t.r for t in tr])
        yrs = (lo.index[-1] - lo.index[0]).days / 365.25
        cpr = np.mean([costs.cost_in_r(t.entry, t.stop) for t in tr])
        safe = bootstrap.risk_for_drawdown(list(r), 10.0) if r.mean() > 0 else 0.0
        day = 50000 * (safe / 100) * r.mean() * (len(r) / yrs) / 252
        print(f"{label:<26} {tag:>6} {len(r):>7} {r.mean():>+7.3f} "
              f"{(r > 0).mean() * 100:>6.1f}% {cpr:>6.3f} ${day:>9,.0f}")
    print()
print("DONE")
