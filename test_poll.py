"""Does poll_once resolve a trade the same way the backtester does?

The demo is about to run for four months. If its fill logic or its arithmetic
differs from `backtest/engine.py`, the forward results will not be comparable
to the backtest that justified running it, and we would not find out until we
sat down to compare them.

poll_once.py claims in its own docstring that the rules match. This checks it
rather than trusting it, on real bars, against the real backtester:

  1. every closed trade agrees on outcome and on R
  2. a bar covering BOTH stop and target resolves as a loss
  3. a stop that gapped fills at the open, not at the stop price
  4. state survives a save/load round trip

    python test_poll.py
"""
import datetime as dt
import functools
import json
import os
import sys
import tempfile

print = functools.partial(print, flush=True)

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

import poll_once
from paper.risk import INSTRUMENTS
from backtest.engine import run as bt_run, Costs
from futures import costs_for

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'ok  ' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not ok:
        FAILS.append(f"{name}: {detail}")


def synthetic(bars):
    """Build a 1-minute frame from (open, high, low, close) tuples."""
    idx = pd.date_range("2026-08-03 14:00", periods=len(bars), freq="1min", tz="UTC")
    return pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=idx)


def run_poll_side(pos, df, inst_name="MNQ"):
    """Resolve one position through poll_once and return (outcome, r)."""
    state = poll_once.blank_state()
    state["position"] = dict(pos)
    data = {inst_name: {"m1": df, "m5": df, "lag": 0.0}}
    # position management now works on a book, so that the tuned and the wide
    # reward-to-risk tracks can run side by side. For "main" the book is the
    # state itself, which is what keeps the record already collected intact.
    poll_once.manage_position(state, poll_once.book_of(state, "main"), data)
    if not state["trades"]:
        return None, None
    t = state["trades"][-1]
    return t["outcome"], t["r"]


def main():
    print("=" * 66)
    print("  POLL vs BACKTESTER")
    print("=" * 66)

    # silence the poll's log file during the test
    poll_once.LOG_FILE = os.path.join(tempfile.gettempdir(), "poll_test_log.txt")

    # ---- 1. a bar covering BOTH stop and target must be a LOSS ---------
    print("\n1. ONE BAR COVERS BOTH (the pessimistic rule)")
    pos = {"symbol": "MNQ", "side": "short", "size": 1.0, "entry": 20000.0,
           "stop": 20050.0, "target": 19900.0,
           "opened_at": "2026-08-03 13:59:00+00:00"}
    df = synthetic([(20000, 20060, 19890, 19950)])     # touches stop AND target
    out, r = run_poll_side(pos, df)
    check("both touched resolves as a loss", out == "loss", f"got {out}")

    # ---- 2. a gapped stop fills at the OPEN ----------------------------
    print("\n2. GAPPED STOP")
    df = synthetic([(20080, 20090, 20070, 20085)])     # opened beyond the stop
    out, r = run_poll_side(pos, df)
    # the raw move, LESS the round-trip cost the poll now charges. Writing this
    # as the raw move alone is what made this check fail once the cost fix
    # landed: the test was stale, not the code.
    cost_r = costs_for("MNQ").cost_in_r(pos["entry"], pos["stop"])
    expect_r = (20000.0 - 20080.0) / 50.0 - cost_r     # filled at the open
    check("gapped stop fills at the open", out == "loss" and abs(r - expect_r) < 1e-6,
          f"outcome {out}, r {r} vs expected {expect_r:.3f}")

    # ---- 3. clean target hit -------------------------------------------
    print("\n3. CLEAN TARGET")
    df = synthetic([(20000, 20010, 19980, 19990), (19990, 19995, 19895, 19900)])
    out, r = run_poll_side(pos, df)
    check("target hit resolves as a win", out == "win", f"got {out}")

    # ---- 4. agreement with the backtester on REAL bars -----------------
    print("\n4. AGREEMENT WITH backtest/engine.py ON REAL BARS")
    store = os.path.join(ROOT, "data", "store", "nsxusd_1m.parquet")
    if not os.path.exists(store):
        check("real-bar comparison", False, "nsxusd_1m.parquet missing")
    else:
        m1 = pd.read_parquet(store).iloc[-4000:]
        costs = costs_for("MNQ")
        px = float(m1["close"].iloc[100])
        risk = px * 0.0015
        from engine.strategy import Setup
        s = Setup(bar=100, side="short", entry=px, stop=px + risk,
                  target=px - risk * 0.8, rr=0.8, swept_price=px + risk,
                  confluences=3, tags="t", efficiency=0.5, reason="t")
        tr, _ = bt_run(m1, [s], costs)
        if not tr:
            check("real-bar comparison", False, "backtester produced no trade")
        else:
            bt = tr[0]
            pos2 = {"symbol": "MNQ", "side": "short", "size": 1.0,
                    "entry": s.entry, "stop": s.stop, "target": s.target,
                    "opened_at": str(m1.index[bt.entry_bar])}
            out, r = run_poll_side(pos2, m1)
            check("same outcome", out == bt.outcome, f"poll {out} vs backtest {bt.outcome}")
            if r is not None:
                gap = abs(r - bt.r)
                check("same R multiple", gap < 0.001,
                      f"poll {r:+.3f} vs backtest {bt.r:+.3f}, differ by {gap:.3f}")
                if gap >= 0.001:
                    print(f"         backtest charges {bt.cost_r:.3f}R of costs; "
                          f"does the poll?")

    # ---- 5. state survives a round trip ---------------------------------
    print("\n5. STATE ROUND TRIP")
    tmp = os.path.join(tempfile.gettempdir(), "poll_state_test.json")
    real = poll_once.STATE_FILE
    poll_once.STATE_FILE = tmp
    try:
        st = poll_once.blank_state()
        st["position"] = dict(pos)
        st["equity"] = 51234.56
        st["trades"] = [{"symbol": "MNQ", "r": 0.8}]
        poll_once.save_state(st)
        back = poll_once.load_state()
        check("equity survives", back["equity"] == 51234.56, str(back["equity"]))
        check("position survives", back["position"] == pos)
        check("trades survive", len(back["trades"]) == 1)
    finally:
        poll_once.STATE_FILE = real
        if os.path.exists(tmp):
            os.remove(tmp)

    print("\n" + "=" * 66)
    if FAILS:
        print(f"  {len(FAILS)} MISMATCH(ES)")
        for f in FAILS:
            print(f"    - {f}")
    else:
        print("  Poll and backtester agree.")
    print("=" * 66)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
