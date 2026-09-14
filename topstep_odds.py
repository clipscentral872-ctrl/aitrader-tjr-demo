"""How likely is the robot to pass Topstep's $50K Combine, at what trade size?

The robot's own paper trades are replayed as whole days, drawn at random with
replacement, through the Combine's rules: the trailing $2,000 Max Loss Limit,
the $1,000 daily limit, the consistency rule and the $3,000 target. Each size
is tried many thousands of times.

Whole days rather than single trades, because the robot's losses cluster: the
worst day in the record had two losses back to back. Shuffling trades one at a
time would spread them out and flatter every answer.

THREE WORLDS, BECAUSE THE RECORD IS SHORT
-----------------------------------------
    as recorded     the paper trades exactly as they came out
    half the edge   every trade 0.17R worse, about where the long backtests sit
    no edge         every trade shifted so the average is zero

The record is a few weeks long. If only the first line looks good, the answer
is "it depends on luck continuing", and that is worth knowing before paying.

    python topstep_odds.py
    python topstep_odds.py --runs 20000
"""
import argparse
import collections
import datetime as dt
import functools
import json
import os
import subprocess
import sys

print = functools.partial(print, flush=True)

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from paper import topstep as TS                            # noqa: E402

POINT = {"MNQ": 2.0, "MES": 5.0}
SIZES = [100, 150, 200, 250, 300, 363]
MAX_DAYS = 60                   # about three months of trading days


def load_trades():
    """The remote state, never the local copy: the local one goes stale."""
    try:
        raw = subprocess.run(["git", "show", "origin/main:state/demo_state.json"],
                             cwd=ROOT, capture_output=True, text=True, check=True).stdout
        s = json.loads(raw)
    except Exception:                                        # noqa: BLE001
        s = json.load(open(os.path.join(ROOT, "state", "demo_state.json"),
                           encoding="utf-8"))
    return s["trades"]


def by_day(trades):
    days = collections.defaultdict(list)
    for t in trades:
        ts = dt.datetime.fromisoformat(t["closed_at"].replace("Z", "+00:00"))
        ny = ts - dt.timedelta(hours=4)
        pv = POINT.get(t["symbol"], 2.0)
        stop_pts = abs(t["entry"] - t["stop"])
        days[TS.ts_day(ny)].append((float(t["r"]), stop_pts * pv))
    return [days[d] for d in sorted(days)]


def attempt(days, risk, shift, rng):
    """One Combine attempt. Returns ("passed"|"failed"|"open", days_used)."""
    eq, mll, best, traded = TS.START, TS.START - TS.MLL_GAP, 0.0, 0
    for n in range(1, MAX_DAYS + 1):
        day = days[rng.integers(len(days))]
        start = eq
        for r, per_contract in day:
            k = TS.contracts(risk, per_contract)
            if k < 1:
                continue
            eq += (r + shift) * k * per_contract
            if eq <= mll:
                return "failed", n
            if eq - start <= -TS.DLL:
                break
        traded += 1
        best = max(best, eq - start)
        mll = max(mll, min(eq - TS.MLL_GAP, TS.START))
        if eq - TS.START >= max(TS.TARGET, 2 * best) and traded >= TS.MIN_DAYS:
            return "passed", n
    return "open", MAX_DAYS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=10000)
    a = ap.parse_args()

    trades = load_trades()
    days = by_day(trades)
    mean = float(np.mean([t["r"] for t in trades]))
    worlds = [("as recorded", 0.0), ("half the edge", -mean / 2), ("no edge", -mean)]
    print(f"{len(trades)} paper trades over {len(days)} Topstep days, "
          f"average {mean:+.3f}R\n")

    for name, shift in worlds:
        print(f"  {name} (average {mean + shift:+.3f}R)")
        print(f"    {'risk a trade':>12} {'pass':>7} {'fail':>7} {'unsettled':>10}"
              f" {'days to pass':>13}")
        for risk in SIZES:
            rng = np.random.default_rng(7)
            res = [attempt(days, risk, shift, rng) for _ in range(a.runs)]
            p = sum(1 for x in res if x[0] == "passed") / a.runs
            f = sum(1 for x in res if x[0] == "failed") / a.runs
            o = max(0.0, 1 - p - f)
            dp = [x[1] for x in res if x[0] == "passed"]
            med = f"{int(np.median(dp))}" if dp else "-"
            print(f"    ${risk:>11} {p:>7.0%} {f:>7.0%} {o:>10.0%} {med:>13}")
        print()


if __name__ == "__main__":
    main()
