"""One poll of the live paper demo, then exit. Designed for GitHub Actions.

WHY THIS EXISTS
---------------
`demo_today.py` runs a continuous loop and holds the account in memory. That
works on a machine that stays on, and it dies the moment the session or the
laptop does. It also cannot run on GitHub Actions, where a job is capped at six
hours and the London+NY window needs thirteen.

So this does exactly one poll and exits. Everything that must survive between
polls is written to `state/demo_state.json` and committed back to the repo, in
the same spirit as the encrypted state branch used elsewhere.

FILL RULES MATCH THE BACKTESTER, DELIBERATELY
---------------------------------------------
A limit only fills when price actually trades through it. If one bar covers
both the stop and the target, the STOP wins. A stop that gapped is filled at
the open, not at the stop price. These are the same pessimistic assumptions
`backtest/engine.py` makes, so demo results and backtest results mean the same
thing. If the two ever disagree, that is a bug worth chasing rather than a
discovery.

ONE POSITION ACROSS BOTH INSTRUMENTS
------------------------------------
NQ and ES correlate at +0.954. Holding both is one bet at double size, so the
state carries a single position and the second instrument is refused with the
reason recorded.

    python poll_once.py
    python poll_once.py --dry-run     # decide, print, write nothing
"""
import argparse
import datetime as dt
import functools
import json
import os
import sys

print = functools.partial(print, flush=True)

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from engine.strategy import Config, find_setups          # noqa: E402
from engine.multiframe import find_setups_mtf            # noqa: E402
from data.fetch import yahoo, resample                   # noqa: E402
from paper.risk import RiskGate, RiskRules, INSTRUMENTS  # noqa: E402
from tjr_exact import window                             # noqa: E402
from futures import costs_for                            # noqa: E402
import live                                              # noqa: E402

STATE_DIR = os.path.join(ROOT, "state")
STATE_FILE = os.path.join(STATE_DIR, "demo_state.json")
LOG_FILE = os.path.join(STATE_DIR, "demo_log.txt")

# London 03:00 through the New York close, in New York time
SCAN = window(3, 0, 16, 0)

SYMBOLS = [("MNQ", "NQ=F"), ("MES", "ES=F")]
EQUITY_START = 50_000.0
RISK_PCT = 0.726          # what keeps 95% of paths inside a 10% drawdown
FEED_LAG_LIMIT_MIN = 25   # the free CME feed runs ~10 behind; 25 is the cliff


def blank_state():
    return {"equity": EQUITY_START, "position": None, "trades": [],
            "refused": [], "last_bar": {}, "polls": 0, "started": None}


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as fh:
            return json.load(fh)
    s = blank_state()
    s["started"] = dt.datetime.now(dt.timezone.utc).isoformat()
    return s


def save_state(state):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1)


def log(state, line):
    stamp = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=4)
    text = f"[{stamp:%Y-%m-%d %H:%M} NY] {line}"
    print("  " + text)
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(LOG_FILE, "a", encoding="utf-8") as fh:
        fh.write(text + "\n")


def feeds():
    """One-minute bars for both instruments, and the 5-minute resample."""
    out = {}
    for name, sym in SYMBOLS:
        try:
            m1 = yahoo(sym, "1m", "5d", max_age=45)
        except Exception as e:
            print(f"  {name}: feed error {type(e).__name__}")
            continue
        if m1 is None or m1.empty:
            print(f"  {name}: feed empty")
            continue
        lag = (dt.datetime.now(dt.timezone.utc)
               - m1.index[-1].to_pydatetime()).total_seconds() / 60
        out[name] = {"m1": m1, "m5": resample(m1, "5min"), "lag": lag}
    return out


def manage_position(state, data):
    """Walk any bars that printed since the last poll and resolve the trade."""
    pos = state.get("position")
    if not pos:
        return
    d = data.get(pos["symbol"])
    if not d:
        return
    m1 = d["m1"]
    since = pd.Timestamp(pos["opened_at"])
    bars = m1[m1.index > since]
    if bars.empty:
        return

    inst = INSTRUMENTS[pos["symbol"]]
    for ts, b in bars.iterrows():
        hi, lo, op = float(b["high"]), float(b["low"]), float(b["open"])
        hit_stop = hi >= pos["stop"] if pos["side"] == "short" else lo <= pos["stop"]
        hit_tgt = lo <= pos["target"] if pos["side"] == "short" else hi >= pos["target"]
        if hit_stop:
            px = pos["stop"]
            # a stop is a market order: a bar that opened beyond it fills there
            if pos["side"] == "short" and op > pos["stop"]:
                px = op
            elif pos["side"] == "long" and op < pos["stop"]:
                px = op
            close_position(state, pos, px, ts, "loss", inst)   # stop wins ties
            return
        if hit_tgt:
            close_position(state, pos, pos["target"], ts, "win", inst)
            return


def close_position(state, pos, price, ts, outcome, inst):
    move = (pos["entry"] - price) if pos["side"] == "short" else (price - pos["entry"])
    risk = abs(pos["entry"] - pos["stop"])
    # CHARGE THE ROUND TRIP, exactly as backtest/engine.py does. Without this
    # the demo reported R multiples about 0.02 too generous on every trade,
    # roughly 12% of the measured edge, and four months of forward results
    # would not have been comparable to the backtest that justified running it.
    cost_r = costs_for(pos["symbol"]).cost_in_r(pos["entry"], pos["stop"])
    r = (move / risk - cost_r) if risk else 0.0
    cash = r * risk / inst.tick_size * inst.tick_value * pos["size"]
    state["equity"] = round(state["equity"] + cash, 2)
    state["trades"].append({
        "symbol": pos["symbol"], "side": pos["side"], "size": pos["size"],
        "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
        "exit": round(float(price), 2), "outcome": outcome,
        "r": round(float(r), 3), "pnl": round(float(cash), 2),
        "cost_r": round(float(cost_r), 4),
        "opened_at": pos["opened_at"], "closed_at": str(ts),
    })
    state["position"] = None
    log(state, f"CLOSE {pos['symbol']} {outcome} at {price:,.2f}  "
               f"{r:+.2f}R  ${cash:+,.0f}  equity ${state['equity']:,.0f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="decide and print, but write no state")
    a = ap.parse_args()

    state = load_state()
    state["polls"] = state.get("polls", 0) + 1
    now_ny = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=4)

    cfg = live.Runner._tuned()
    rules = RiskRules(risk_pct=RISK_PCT, min_rr=cfg.min_rr, max_rr=cfg.max_rr,
                      max_total_drawdown_pct=10.0)

    print(f"poll {state['polls']}   {now_ny:%Y-%m-%d %H:%M} New York   "
          f"equity ${state['equity']:,.0f}   trades {len(state['trades'])}")

    data = feeds()
    if not data:
        print("  no usable feed this poll")
        if not a.dry_run:
            save_state(state)
        return

    for name in data:
        print(f"  {name}: last {data[name]['m1'].index[-1]:%H:%M} UTC, "
              f"lag {data[name]['lag']:.0f}m")

    manage_position(state, data)

    in_window = SCAN(pd.Timestamp(dt.datetime.now(dt.timezone.utc)))
    if not in_window:
        print("  outside the London+NY window, not scanning")
        if not a.dry_run:
            save_state(state)
        return

    if state.get("position"):
        print(f"  holding {state['position']['symbol']}, "
              f"one position across the correlated group")
        if not a.dry_run:
            save_state(state)
        return

    # ---- look for a setup on each instrument, take the better one --------
    best = None
    for name, d in data.items():
        if d["lag"] > FEED_LAG_LIMIT_MIN:
            log(state, f"{name} refused: feed {d['lag']:.0f} min behind")
            continue
        pair = data.get("MES" if name == "MNQ" else "MNQ")
        try:
            setups = find_setups_mtf(d["m1"], d["m5"], cfg, session_filter=SCAN,
                                     require_confirm=True,
                                     smt_df=pair["m5"] if pair else None)
        except Exception as e:
            log(state, f"{name} setup error: {type(e).__name__}: {str(e)[:70]}")
            continue
        if not setups:
            continue
        last = len(d["m1"]) - 1
        fresh = [s for s in setups if s.bar >= last - 2]
        if not fresh:
            continue
        s = max(fresh, key=lambda x: (x.confluences, x.rr))
        if best is None or (s.confluences, s.rr) > (best[1].confluences, best[1].rr):
            best = (name, s)

    if best is None:
        print("  no setup")
        if not a.dry_run:
            save_state(state)
        return

    name, s = best
    gate = RiskGate(rules, start_equity=EQUITY_START)
    d = gate.check(s, state["equity"], dt.datetime.now(dt.timezone.utc),
                   INSTRUMENTS[name], open_positions=0)
    if not d.approved:
        log(state, f"{name} refused by the gate: {d.reason}")
        state["refused"].append({"when": now_ny.isoformat(), "symbol": name,
                                 "why": d.reason})
    else:
        state["position"] = {
            "symbol": name, "side": s.side, "size": d.size,
            "entry": round(float(s.entry), 2), "stop": round(float(s.stop), 2),
            "target": round(float(s.target), 2), "rr": round(float(s.rr), 2),
            "tags": s.tags, "reason": s.reason,
            "opened_at": str(data[name]["m1"].index[-1]),
        }
        log(state, f"OPEN {name} {s.side} {d.size:g} @ {s.entry:,.2f}  "
                   f"stop {s.stop:,.2f}  target {s.target:,.2f}  "
                   f"rr {s.rr:.2f}  risk ${d.risk_cash:,.0f}  [{s.tags}]")

    if not a.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
