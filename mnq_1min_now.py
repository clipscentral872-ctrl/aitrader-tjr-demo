"""Is the 1-minute entry still negative after today's fixes?

The earlier run said -0.407R over 1,374 trades, but it predates the 4-hour bias
fix, the New York session boundaries, SMT, the reward band and the HTF draw
picker. Re-running it on what we actually have now, against the 5-minute entry
as a baseline, because Chris's instruction is to enter on the 1-minute and the
question is whether that path can be made to work rather than whether it is
convenient.
"""
import functools
print = functools.partial(print, flush=True)
import numpy as np, pandas as pd
from engine.strategy import Config, find_setups
from engine.multiframe import find_setups_mtf
from backtest.engine import run as bt_run
from data.fetch import resample
from tjr_exact import TJR, window
from futures import costs_for
import live

cfg_live = live.Runner._tuned()
base = {k: getattr(cfg_live, k) for k in
        ("min_rr", "max_rr", "htf_factor", "use_smt", "smt_left", "smt_right",
         "draw_mode", "aligned_reach", "against_reach", "min_stop_pct",
         "max_stop_pct")}
m1 = pd.read_parquet("data/store/nsxusd_1m.parquet")
es = pd.read_parquet("data/store/sp500_duka_5m.parquet")
m1 = m1[m1.index >= max(m1.index[0], es.index[0])]
m5 = resample(m1, "5min")
c1, c5 = int(len(m1) * 0.6), int(len(m5) * 0.6)
costs = costs_for("MNQ")
wf = window(9, 30, 16, 0)
print(f"current config: {base}")
print(f"NQ {len(m1):,} 1-min bars from {m1.index[0]:%Y-%m-%d}\n")
print(f"  {'entry':<28} {'seg':>6} {'trades':>7} {'exp R':>8} {'win %':>7} {'$/day':>9}")

def report(label, tag, seg, setups):
    if len(setups) < 15:
        print(f"  {label:<28} {tag:>6} {len(setups):>7}   too few"); return
    tr, _ = bt_run(seg, setups, costs)
    r = np.array([t.r for t in tr])
    if len(r) < 15:
        print(f"  {label:<28} {tag:>6} {len(r):>7}   too few"); return
    yrs = (seg.index[-1] - seg.index[0]).days / 365.25
    day = 50000 * 0.015 * r.mean() * (len(r) / yrs / 252)
    print(f"  {label:<28} {tag:>6} {len(r):>7} {r.mean():>+7.3f} "
          f"{(r > 0).mean() * 100:>6.1f}% ${day:>8,.0f}")

for tag, lo5, hi5, lo1 in (("train", m5.iloc[:c5], m5.iloc[:c5], m1.iloc[:c1]),
                           ("TEST", m5.iloc[c5:], m5.iloc[c5:], m1.iloc[c1:])):
    report("5-minute entry (baseline)", tag, lo5,
           find_setups(lo5, Config(**base), session_filter=wf, smt_df=es))
for mode in ("ltf", "structural"):
    for tag, lo1, hi5 in (("train", m1.iloc[:c1], m5.iloc[:c5]),
                          ("TEST", m1.iloc[c1:], m5.iloc[c5:])):
        report(f"1-minute entry, {mode} stop", tag, lo1,
               find_setups_mtf(lo1, hi5, Config(**base), session_filter=wf,
                               require_confirm=True, stop_mode=mode, smt_df=es))
print("\nDONE")
