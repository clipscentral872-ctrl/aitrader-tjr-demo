"""Chris trades 2R. The config caps reward at 0.5R. Which is right?

His screenshot: risk $750, reward ~$1,510, R:R 2.03 and 2.05, stops 0.125%
and 0.140%. The config would cut those 74- and 84-point targets to about 18
points. That is not a tweak, it is a different trade.

Earlier work found tight targets beat wide ones, but that was measured on
other markets and other sessions. This measures it where he actually trades:
NQ, his window, and the full New York session for comparison, because his
45-minute window is far too thin to separate anything on its own.
"""
import functools
print = functools.partial(print, flush=True)
import numpy as np, pandas as pd
from engine.strategy import Config, find_setups
from backtest.engine import run as bt_run
from data.fetch import resample
from tjr_exact import TJR, window
from futures import costs_for

m1 = pd.read_parquet("data/store/nsxusd_1m.parquet")
m5 = resample(m1, "5min")
cut = int(len(m5) * 0.6)
costs = costs_for("MNQ")
RISK_PCT = 1.3          # his stated minimum, as a share of the account
EQUITY = 50_000

SETTINGS = [("0.5R  (config today)", 0.4, 0.5),
            ("1.3R  (his floor)",    1.3, 1.6),
            ("2.0R  (his screenshot)", 1.8, 2.2),
            ("open target",          1.3, 5.0)]
WINDOWS = [("his window 09:45-10:30", window(9, 45, 10, 30)),
           ("full NY 09:30-16:00",    window(9, 30, 16, 0))]

for wname, wf in WINDOWS:
    print(f"\n{wname}")
    print(f"  {'target':<24} {'seg':>6} {'trades':>7} {'exp R':>8} {'win %':>7} "
          f"{'$/day':>9}")
    for label, mn, mx in SETTINGS:
        cfg = Config(**{**TJR, "min_rr": mn, "max_rr": mx})
        for tag, seg in (("train", m5.iloc[:cut]), ("TEST", m5.iloc[cut:])):
            s = find_setups(seg, cfg, session_filter=wf)
            if not s:
                print(f"  {label:<24} {tag:>6}   no setups"); continue
            tr, _ = bt_run(seg, s, costs)
            if len(tr) < 20:
                print(f"  {label:<24} {tag:>6} {len(tr):>7}   too few"); continue
            r = np.array([t.r for t in tr])
            yrs = (seg.index[-1] - seg.index[0]).days / 365.25
            per_day = len(r) / yrs / 252
            day = EQUITY * (RISK_PCT / 100) * r.mean() * per_day
            print(f"  {label:<24} {tag:>6} {len(r):>7} {r.mean():>+7.3f} "
                  f"{(r > 0).mean() * 100:>6.1f}% ${day:>8,.0f}")
print("\nDONE")
