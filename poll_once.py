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


# TWO BOOKS, ONE FEED.
#
# The tuned config takes 0.6-0.8 reward to risk. It wins about nine times in ten
# and the round trip still eats close to half of each win, because a stop that
# tight cannot carry the cost. Chris trades a 1.3 minimum and TJR coaches the
# same thing, so the two shapes disagree and no amount of arguing settles it.
#
# They are therefore run side by side against the SAME bars at the SAME moment.
# Only the reward-to-risk band differs, so whatever separates them after a few
# hundred trades is the shape and not the luck of different entries.
#
# "main" keeps the original top level keys so the record already collected is
# not thrown away. "wide" gets its own book.
TRACKS = [("main", 0.6, 0.8), ("wide", 1.3, 2.2)]


def book_of(state, track):
    """The equity, position and trades belonging to one track."""
    if track == "main":
        return state
    b = state.setdefault(track, None)
    if not b:
        b = {"equity": EQUITY_START, "position": None, "trades": [],
             "refused": [], "started": dt.datetime.now(dt.timezone.utc).isoformat()}
        state[track] = b
    return b


def manage_position(state, book, data):
    """Walk any bars that printed since the last poll and resolve the trade."""
    pos = book.get("position")
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
            close_position(state, book, pos, px, ts, "loss", inst)  # stop wins ties
            return
        if hit_tgt:
            close_position(state, book, pos, pos["target"], ts, "win", inst)
            return


def close_position(state, book, pos, price, ts, outcome, inst):
    move = (pos["entry"] - price) if pos["side"] == "short" else (price - pos["entry"])
    risk = abs(pos["entry"] - pos["stop"])
    # CHARGE THE ROUND TRIP, exactly as backtest/engine.py does. Without this
    # the demo reported R multiples about 0.02 too generous on every trade,
    # roughly 12% of the measured edge, and four months of forward results
    # would not have been comparable to the backtest that justified running it.
    cost_r = costs_for(pos["symbol"]).cost_in_r(pos["entry"], pos["stop"])
    r = (move / risk - cost_r) if risk else 0.0
    cash = r * risk / inst.tick_size * inst.tick_value * pos["size"]
    book["equity"] = round(book["equity"] + cash, 2)
    book["trades"].append({
        "symbol": pos["symbol"], "side": pos["side"], "size": pos["size"],
        "entry": pos["entry"], "stop": pos["stop"], "target": pos["target"],
        "exit": round(float(price), 2), "outcome": outcome,
        "r": round(float(r), 3), "pnl": round(float(cash), 2),
        "cost_r": round(float(cost_r), 4),
        "opened_at": pos["opened_at"], "closed_at": str(ts),
    })
    book["position"] = None
    log(state, f"CLOSE {book.get('_name', 'main')} {pos['symbol']} {outcome} "
               f"at {price:,.2f}  {r:+.2f}R  ${cash:+,.0f}  "
               f"equity ${book['equity']:,.0f}")


def scan_and_open(state, book, track, cfg, rules, data, now_ny):
    """Look for a setup for one book, and take it if the gate approves."""
    if book.get("position"):
        print(f"  [{track}] holding {book['position']['symbol']}")
        return

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

        # Every candidate this poll saw, kept so the record can answer questions
        # the code cannot. Ten trades in a row came out long while an offline
        # reconstruction of the same period produced more shorts than longs, and
        # four theories about why were all wrong. Rather than guess a fifth time,
        # the poller writes down what it was actually offered.
        state.setdefault("seen", []).append({
            "when": now_ny.isoformat(), "track": track, "symbol": name,
            "all": len(setups), "fresh": len(fresh),
            "long": sum(1 for x in setups if x.side == "long"),
            "short": sum(1 for x in setups if x.side == "short"),
            "fresh_long": sum(1 for x in fresh if x.side == "long"),
            "fresh_short": sum(1 for x in fresh if x.side == "short"),
        })
        state["seen"] = state["seen"][-4000:]

        if not fresh:
            continue
        s = max(fresh, key=lambda x: (x.confluences, x.rr))
        if best is None or (s.confluences, s.rr) > (best[1].confluences, best[1].rr):
            best = (name, s)

    if best is None:
        print(f"  [{track}] no setup")
        return

    name, s = best
    gate = RiskGate(rules, start_equity=EQUITY_START)
    d = gate.check(s, book["equity"], dt.datetime.now(dt.timezone.utc),
                   INSTRUMENTS[name], open_positions=0)
    if not d.approved:
        log(state, f"[{track}] {name} refused by the gate: {d.reason}")
        book.setdefault("refused", []).append(
            {"when": now_ny.isoformat(), "symbol": name, "why": d.reason})
        return

    # A setup stays "fresh" for three bars, so when a position closes inside that
    # window the next poll finds the SAME setup and opens it again. It produced
    # 17 trades out of 10 real setups, which inflated the record and anything
    # concluded from it. One setup, one trade.
    inst = INSTRUMENTS[name]
    setup_bar = str(data[name]["m1"].index[min(s.bar, len(data[name]["m1"]) - 1)])
    ident = f"{name}|{s.side}|{setup_bar}|{s.entry:.2f}|{s.stop:.2f}"
    if book.get("last_setup") == ident:
        log(state, f"[{track}] {name} same setup as the last trade, not re-entering")
        return
    book["last_setup"] = ident

    # Futures trade in ticks. Nine of the first seventeen entries were prices
    # that cannot exist, e.g. MES at 7,722.65, because the raw feed close was
    # used as the fill. Snap every level to the tick the contract deals in.
    tick = float(getattr(inst, "tick_size", 0.25)) or 0.25
    snap = lambda v: round(round(float(v) / tick) * tick, 4)
    book["position"] = {
        "symbol": name, "side": s.side, "size": d.size,
        "entry": snap(s.entry), "stop": snap(s.stop),
        "target": snap(s.target), "rr": round(float(s.rr), 2),
        "tags": s.tags, "reason": s.reason,
        "opened_at": str(data[name]["m1"].index[-1]),
    }
    log(state, f"OPEN [{track}] {name} {s.side} {d.size:g} @ {snap(s.entry):,.2f}  "
               f"stop {snap(s.stop):,.2f}  target {snap(s.target):,.2f}  "
               f"rr {s.rr:.2f}  risk ${d.risk_cash:,.0f}  [{s.tags}]")


def main():
    import dataclasses
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="decide and print, but write no state")
    a = ap.parse_args()

    state = load_state()
    state["polls"] = state.get("polls", 0) + 1
    now_ny = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=4)
    cfg_base = live.Runner._tuned()

    books = " ".join(
        f"{t}=${book_of(state, t)['equity']:,.0f}/{len(book_of(state, t)['trades'])}"
        for t, _, _ in TRACKS)
    print(f"poll {state['polls']}   {now_ny:%Y-%m-%d %H:%M} New York   {books}")

    data = feeds()
    if not data:
        print("  no usable feed this poll")
        if not a.dry_run:
            save_state(state)
        return

    for name in data:
        print(f"  {name}: last {data[name]['m1'].index[-1]:%H:%M} UTC, "
              f"lag {data[name]['lag']:.0f}m")

    for track, _, _ in TRACKS:
        b = book_of(state, track)
        b["_name"] = track
        manage_position(state, b, data)

    if not SCAN(pd.Timestamp(dt.datetime.now(dt.timezone.utc))):
        print("  outside the London+NY window, not scanning")
        if not a.dry_run:
            save_state(state)
        return

    for track, lo_rr, hi_rr in TRACKS:
        b = book_of(state, track)
        b["_name"] = track
        cfg = dataclasses.replace(cfg_base, min_rr=lo_rr, max_rr=hi_rr)
        rules = RiskRules(risk_pct=RISK_PCT, min_rr=lo_rr, max_rr=hi_rr,
                          max_total_drawdown_pct=10.0)
        scan_and_open(state, b, track, cfg, rules, data, now_ny)

    if not a.dry_run:
        save_state(state)


if __name__ == "__main__":
    main()
