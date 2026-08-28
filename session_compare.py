"""Which session earns most, judged on recent data only.

WHY THE WINDOW IS FIXED IN ADVANCE
----------------------------------
The years genuinely differ. Measured on London+NY with the current config:

    2023   +0.072R   63.3%     (does not clear zero)
    2024   +0.192R   69.3%
    2025   +0.247R   71.9%

That spread is 3.7 standard errors, far beyond noise, so averaging 2023 in
drags the estimate down with a regime that no longer applies. Judging on recent
data is right.

But "recent data is better" and "recent data flatters me" give the same answer,
and the trend here runs in our favour. So the window is declared here, BEFORE
looking: a trailing TWELVE months. Not six, not "since the good bit started".
If a shorter window is ever wanted, it should be argued for on its own terms
rather than chosen because it scored well.

WHAT THE WINNER IS AND IS NOT
-----------------------------
Picking the best of three sessions is a search, and searches find flattering
results by chance. Whichever session wins here has NOT been validated: it has
one number on one window with no train/test split, no walk-forward and no
second source. Treat it as a candidate to put through evaluate.py, never as a
result. `pool3+` read +0.233R on train and -0.049R on test, and would have
looked just as convincing at this stage.

    python session_compare.py
    python session_compare.py --months 6
"""
import argparse
import functools
import os
import sys

print = functools.partial(print, flush=True)

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from engine.strategy import Config, find_setups     # noqa: E402
from backtest.engine import run as bt_run           # noqa: E402
from backtest import bootstrap                      # noqa: E402
from data.fetch import resample                     # noqa: E402
from tjr_exact import window                        # noqa: E402
from futures import costs_for                       # noqa: E402
import live                                         # noqa: E402

SESSIONS = [
    ("Asia 18:00-03:00",     window(18, 0, 3, 0)),
    ("London 03:00-08:30",   window(3, 0, 8, 30)),
    ("New York 09:30-16:00", window(9, 30, 16, 0)),
    ("London+NY (running)",  window(3, 0, 16, 0)),
]


def load(months):
    """Nasdaq on five-minute bars, and the S&P as the pair for the veto.

    Two Nasdaq series exist and they end at different times. HistData is denser
    (89% of a 24-hour weekday series against Dukascopy's 63%) but stops at
    2025-12-31. Dukascopy is sparser but now runs to 2026-08-27.

    This used to load HistData unconditionally, so after fetching 2026 the
    comparison still measured 2025 and reported it under a "trailing 12 months"
    heading. Pick whichever actually covers the window asked for, and say which
    one was used, because the two disagree on 23% of bar highs by more than 20
    points and a sweep of a high is the whole strategy.
    """
    store = os.path.join(ROOT, "data", "store")
    want_start = pd.Timestamp.now("UTC") - pd.Timedelta(days=int(months * 30.44))

    options = []
    hist = os.path.join(store, "nsxusd_1m.parquet")
    if os.path.exists(hist):
        options.append(("HistData (denser, 89%)",
                        resample(pd.read_parquet(hist), "5min")))
    duka = os.path.join(store, "nasdaq_duka_5m.parquet")
    if os.path.exists(duka):
        options.append(("Dukascopy (sparser, 63%)", pd.read_parquet(duka)))

    # prefer the one whose end is nearest to today; break ties on density
    options.sort(key=lambda o: o[1].index[-1], reverse=True)
    label, nq = options[0]
    covered = (nq.index[-1] - max(nq.index[0], want_start)).days
    print(f"  Nasdaq source: {label}, to {nq.index[-1].date()} "
          f"({covered} days of the window covered)")

    es = pd.read_parquet(os.path.join(store, "sp500_duka_5m.parquet"))
    return nq, es


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12,
                    help="trailing window; 12 is the declared default")
    ap.add_argument("--no-veto", action="store_true",
                    help="run without the index-alignment veto. Needed when the "
                         "pair does not cover the window, e.g. Nasdaq 2026 has "
                         "landed but the S&P has not. NOT the live config.")
    a = ap.parse_args()

    nq, es = load(a.months)

    # Anchor the window to TODAY, not to wherever the data happens to stop.
    # Anchoring to the data's end meant that with feeds ending 2025-12-31,
    # "trailing 12 months" silently became January-December 2025: a window
    # ending eight months ago, reported as recent. The whole point of judging
    # on recent data is defeated if "recent" is defined by the stale file.
    now = pd.Timestamp.now("UTC")
    want_start = now - pd.Timedelta(days=int(a.months * 30.44))
    # only let the PAIR clamp the window when the pair is actually used.
    # Taking min() unconditionally meant the S&P ending 2025-12-31 dragged the
    # window back a year even with the veto off, so the freshly fetched 2026
    # Nasdaq was loaded and then sliced away.
    have_end = nq.index[-1] if a.no_veto else min(nq.index[-1], es.index[-1])

    missing = (now - have_end).days
    if missing > 21:
        print(f"  WARNING: the window you asked for ends {now.date()}, but the")
        print(f"  data stops at {have_end.date()}, {missing} days short. This is")
        print(f"  measuring {want_start.date()} to {have_end.date()}, NOT the")
        print(f"  {a.months} months to today. Treat it accordingly.")
        print()

    start, end = want_start, have_end
    nq = nq[(nq.index >= start) & (nq.index <= end)]
    if nq.empty:
        print(f"  no data at all inside {start.date()} to {end.date()}")
        return

    cfg = live.Runner._tuned()
    if a.no_veto:
        import dataclasses
        cfg = dataclasses.replace(cfg, require_index_align=False)
    costs = costs_for("MNQ")

    print("=" * 74)
    print(f"  SESSION COMPARISON   trailing {a.months} months")
    print("=" * 74)
    print(f"  {start.date()} to {end.date()}   {len(nq):,} five-minute bars")
    print(f"  config: {cfg.min_rr}-{cfg.max_rr}R, stop_rule={cfg.stop_rule}, "
          f"veto={cfg.require_index_align}")
    if not cfg.require_index_align:
        print("  NOTE: the veto is OFF, so this is not the configuration that "
              "runs live.")
    stale = (now - end).days
    if stale > 45:
        print(f"  WARNING: data ends {stale} days ago, so this is not "
              f"actually recent")
    print()

    print(f"  {'session':<22} {'n':>5} {'exp R':>8} {'win %':>7} "
          f"{'95% range':>20} {'safe%':>6} {'$/mo':>9}")
    rows = []
    for name, wf in SESSIONS:
        s = find_setups(nq, cfg, session_filter=wf,
                        smt_df=(None if a.no_veto else es))
        if not s:
            print(f"  {name:<22} {0:>5}   no setups")
            continue
        tr, _ = bt_run(nq, s, costs)
        r = np.array([t.r for t in tr])
        if len(r) < 20:
            print(f"  {name:<22} {len(r):>5}   too few to judge")
            continue
        se = r.std(ddof=1) / np.sqrt(len(r))
        lo, hi = r.mean() - 1.96 * se, r.mean() + 1.96 * se
        yrs = (nq.index[-1] - nq.index[0]).days / 365.25
        safe = bootstrap.risk_for_drawdown(list(r), 10.0) if r.mean() > 0 else 0.0
        mo = 50_000 * (safe / 100) * r.mean() * (len(r) / yrs / 252) * 21
        rows.append((name, len(r), r.mean(), (r > 0).mean() * 100, lo, safe, mo))
        print(f"  {name:<22} {len(r):>5} {r.mean():>+7.3f} "
              f"{(r > 0).mean() * 100:>6.1f}%   {lo:>+6.3f} to {hi:<+6.3f} "
              f"{safe:>5.2f}% ${mo:>8,.0f}")

    print()
    solid = [x for x in rows if x[4] > 0]
    if not solid:
        print("  Nothing clears zero on its own. No session is worth switching to.")
    else:
        best_r = max(solid, key=lambda x: x[2])
        best_w = max(solid, key=lambda x: x[3])
        best_m = max(solid, key=lambda x: x[6])
        print(f"  best return    {best_r[0]}  ({best_r[2]:+.3f}R)")
        print(f"  best win rate  {best_w[0]}  ({best_w[3]:.1f}%)")
        print(f"  most money     {best_m[0]}  (${best_m[6]:,.0f}/month)")
        print()
        print("  These are CANDIDATES, not results. Best-of-N on one window with")
        print("  no train/test split is how flattering numbers get found. Put the")
        print("  winner through evaluate.py before believing it.")
    print("=" * 74)


if __name__ == "__main__":
    main()
