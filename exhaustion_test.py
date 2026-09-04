"""Does refusing spent liquidity actually help, or does it just trade less?

THE RULE UNDER TEST
-------------------
TJR walks through a losing trade in his teaching session where every step was
correct and it still failed. His diagnosis: the lows being targeted had already
been swept earlier in the move. Where retail stops sit is where the desk that
filled those orders takes profit, so entering into spent liquidity puts you on
the wrong side of the people who are getting out.

`require_fresh_draw` refuses a setup when the level it would target has already
been traded through.

HOW IT IS JUDGED
----------------
NOT by comparing two confidence intervals. The two runs share most of their
trades, so their errors are correlated and the comparison would be meaningless.

The filter's only effect is to REMOVE a subset of trades. So the question that
actually decides it is: what was the expectancy of the trades it removed? If
they were losers, the filter earns its place. If they were around break-even,
it is trading less for no gain. If they were winners, it is destroying edge.

That subset is measured directly, with a standard error, and the window is the
same trailing twelve months declared in session_compare.py. A first-half /
second-half split follows, because one number on one window is how every
flattering result in this project has started.
"""
import argparse
import dataclasses
import functools
import os
import sys

print = functools.partial(print, flush=True)

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import live
from backtest.engine import run as bt_run
from futures import costs_for
from engine.strategy import find_setups
from session_compare import SESSIONS, load


def stats(rs):
    r = np.asarray(rs, dtype=float)
    if len(r) == 0:
        return None
    se = r.std(ddof=1) / np.sqrt(len(r)) if len(r) > 1 else float("nan")
    return {"n": len(r), "mean": r.mean(), "win": (r > 0).mean() * 100,
            "se": se, "lo": r.mean() - 1.96 * se, "hi": r.mean() + 1.96 * se}


def line(label, s):
    if s is None or s["n"] == 0:
        print(f"  {label:<22} {0:>5}   none")
        return
    if s["n"] < 2:
        print(f"  {label:<22} {s['n']:>5} {s['mean']:>+7.3f} "
              f"{s['win']:>6.1f}%   too few for a range")
        return
    print(f"  {label:<22} {s['n']:>5} {s['mean']:>+7.3f} {s['win']:>6.1f}%   "
          f"{s['lo']:>+6.3f} to {s['hi']:<+6.3f}")


def split(nq, es, cfg_off, cfg_on, wf, costs, use_pair):
    """Run both configs over the same bars and separate what the filter drops."""
    pair = es if use_pair else None
    off = find_setups(nq, cfg_off, session_filter=wf, smt_df=pair)
    on = find_setups(nq, cfg_on, session_filter=wf, smt_df=pair)
    if not off:
        return None, None, None, []

    t_off, _ = bt_run(nq, off, costs)
    kept_bars = set()
    if on:
        t_on, _ = bt_run(nq, on, costs)
        kept_bars = {t.entry_bar for t in t_on}
    else:
        t_on = []

    kept = [t for t in t_off if t.entry_bar in kept_bars]
    dropped = [t for t in t_off if t.entry_bar not in kept_bars]
    return t_off, kept, dropped, t_on


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--months", type=int, default=12)
    a = ap.parse_args()

    nq, es = load(a.months)
    now = pd.Timestamp.now("UTC")
    want_start = now - pd.Timedelta(days=int(a.months * 30.44))

    # the pair only clamps the window when it actually covers it
    use_pair = es.index[-1] >= nq.index[-1] - pd.Timedelta(days=21)
    have_end = min(nq.index[-1], es.index[-1]) if use_pair else nq.index[-1]
    nq = nq[(nq.index >= want_start) & (nq.index <= have_end)]
    if nq.empty:
        print("  no data inside the window")
        return

    cfg_off = live.Runner._tuned()
    if not use_pair:
        cfg_off = dataclasses.replace(cfg_off, require_index_align=False)
    cfg_on = dataclasses.replace(cfg_off, require_fresh_draw=True)
    costs = costs_for("MNQ")

    print("=" * 74)
    print("  EXHAUSTION FILTER   require_fresh_draw")
    print("=" * 74)
    print(f"  {nq.index[0].date()} to {nq.index[-1].date()}   "
          f"{len(nq):,} five-minute bars")
    if not use_pair:
        print("  NOTE: the pair does not cover this window, so the index veto "
              "is OFF for both sides.")
    print()

    for name, wf in SESSIONS:
        t_off, kept, dropped, t_on = split(nq, es, cfg_off, cfg_on, wf,
                                           costs, use_pair)
        if t_off is None:
            print(f"  {name}: no setups at all")
            print()
            continue
        print(f"  {name}")
        print(f"  {'':<22} {'n':>5} {'exp R':>7} {'win %':>7}   {'95% range':>20}")
        line("without the filter", stats([t.r for t in t_off]))
        line("kept by the filter", stats([t.r for t in kept]))
        line("REFUSED", stats([t.r for t in dropped]))

        d = stats([t.r for t in dropped])
        k = stats([t.r for t in kept])
        if d and k and d["n"] >= 20:
            if d["hi"] < 0:
                print("    -> the refused trades lose, and the range clears zero")
            elif d["lo"] > 0:
                print("    -> the refused trades WIN. This filter destroys edge.")
            else:
                print("    -> the refused trades are indistinguishable from "
                      "break-even")
        elif d:
            print(f"    -> only {d['n']} refused, too few to judge")
        print()

    # One window is how every flattering result here has started, so the same
    # question is asked of each half separately.
    mid = nq.index[len(nq) // 2]
    print("=" * 74)
    print(f"  SPLIT HALVES   train to {mid.date()}, test after")
    print("=" * 74)
    for half, frame in (("train", nq[nq.index <= mid]), ("test", nq[nq.index > mid])):
        name, wf = SESSIONS[-1]          # the running London+NY window
        t_off, kept, dropped, _ = split(frame, es, cfg_off, cfg_on, wf,
                                        costs, use_pair)
        if t_off is None:
            print(f"  {half}: no setups")
            continue
        print(f"  {half} ({name})")
        line("  without", stats([t.r for t in t_off]))
        line("  kept", stats([t.r for t in kept]))
        line("  REFUSED", stats([t.r for t in dropped]))
        print()

    print("  A filter earns its place only if the trades it refuses lose in")
    print("  BOTH halves. Refusing losers in one half and winners in the other")
    print("  is noise wearing the shape of a rule.")


if __name__ == "__main__":
    main()
