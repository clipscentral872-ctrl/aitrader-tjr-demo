"""A trading journal that shows you the trade, not just the number.

WHAT THIS IS FOR
----------------
Commercial journals give you the statistics: win rate, expectancy, average win
and loss, drawdown. Useful, but a row in a table cannot show you that your stop
was moved to the wrong side of the market, or that you took 13% of a move you
had planned. You have to see the candles to learn from those.

So this does both. It keeps a running record across every session, computes the
same statistics a paid journal would, and for each trade it draws the minute
bars it actually happened on with your entry, stop, target and exit marked, plus
a written read of what went right or wrong.

HOW YOU USE IT
--------------
1. After each session, export from TradingView: Trading Panel -> Paper Trading
   -> Export data -> Order History. Save the file into `journal_data/`.
2. Run `python tradejournal.py`.

It ingests every export in that folder, ignores duplicates by order ID, so you
can drop the same file twice without corrupting anything. Trades accumulate;
nothing is overwritten.

WHAT IT CHECKS AUTOMATICALLY
----------------------------
Each trade is examined for the mistakes that are invisible in a summary:
slippage past the stop, exits well short of the planned target, stops moved to
the wrong side of price, targets set so far out they were never realistic, and
a directional lean across the day. These are mechanical, so they are caught
every time rather than when you happen to remember to look.
"""
import argparse
import csv
import functools
import glob
import io
import json
import os
import sys

print = functools.partial(print, flush=True)

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

DATA_DIR = os.path.join(ROOT, "journal_data")
STORE = os.path.join(ROOT, "journal_data", "trades.json")
META = os.path.join(ROOT, "journal_data", "meta.json")

# Contract point values. A "point" is worth different money on each contract,
# and getting this wrong silently scales every P&L figure.
POINT = {"NQ": 20.0, "MNQ": 2.0, "ES": 50.0, "MES": 5.0,
         "YM": 5.0, "MYM": 0.5, "RTY": 50.0, "M2K": 5.0}
# TradingView writes exchange-prefixed symbols; map to the contract
TICKER = {"CME_MINI:NQ1!": "NQ", "CME_MINI:ES1!": "ES", "CBOT_MINI:YM1!": "YM",
          "CME_MINI:RTY1!": "RTY", "CME_MINI:MNQ1!": "MNQ", "CME_MINI:MES1!": "MES"}
# Yahoo symbols, for pulling the candles a trade happened on
FEED = {"NQ": "NQ=F", "MNQ": "NQ=F", "ES": "ES=F", "MES": "ES=F",
        "YM": "YM=F", "MYM": "YM=F", "RTY": "RTY=F", "M2K": "RTY=F"}

LOCAL_OFFSET_H = 2      # exports are stamped in local time; SAST is UTC+2

# Chris's trail rule: leave the stop alone until price has run about double the
# original stop distance in his favour, then move it to breakeven, then tighten
# further as price approaches the target. Stated here so a stop move can be
# judged against the travel that had actually happened when he made it.
BREAKEVEN_AT_R = 2.0
PAD_BEFORE, PAD_AFTER = 10, 30      # minutes of context around each trade


# ---------------------------------------------------------------------------
# ingest
# ---------------------------------------------------------------------------
def read_exports(folder):
    """Every filled order across every export, de-duplicated by order ID."""
    seen, fills = {}, []
    files = sorted(glob.glob(os.path.join(folder, "*order-history*.csv")))
    for f in files:
        for r in csv.DictReader(io.open(f, encoding="utf-8-sig")):
            if r.get("Status", "").strip().lower() != "filled":
                continue
            oid = r.get("Order ID", "").strip()
            if not oid or oid in seen:
                continue
            seen[oid] = True
            fills.append(r)
    return files, sorted(fills, key=lambda r: r["Closing time"])


def read_stop_moves(folder):
    """Stop and target changes, from the activity log if it was exported.

    This is the only place a moved stop is recorded. Without it, a stop that was
    dragged to the wrong side of the market is indistinguishable from one that
    was simply hit.
    """
    moves = []
    for f in sorted(glob.glob(os.path.join(folder, "*activity-log*.csv"))):
        for r in csv.DictReader(io.open(f, encoding="utf-8-sig")):
            txt = r.get("Text", "")
            if "Modify position" in txt and "SL" in txt:
                try:
                    sl = float(txt.split("SL")[1].split("and")[0].strip())
                except (IndexError, ValueError):
                    continue
                tp = None
                if "TP" in txt:
                    try:
                        tp = float(txt.split("TP")[1].strip())
                    except (IndexError, ValueError):
                        tp = None
                sym = next((v for k, v in TICKER.items() if k in txt), None)
                moves.append({"t": r["Time"], "symbol": sym, "sl": sl, "tp": tp})
    # TradingView writes the activity log newest-first. Left in file order the
    # "first" stop of a trade is actually the last one you trailed to, which is
    # the whole thing this sort exists to prevent.
    return sorted(moves, key=lambda m: m["t"])


def log_coverage(folder):
    """The stretches of time the activity logs actually cover.

    TradingView caps this export, so it holds the tail of a session rather than
    the whole of it. That matters more than it sounds. A trade outside the
    covered stretch has no recorded stop, and falling back to the stop price on
    the exit order quietly measures R against the TRAILED stop instead of the
    one set at entry. That is the mistake that once produced -3.8R of
    expectancy on a day that made money.

    So instead of guessing, the covered windows are known, and a trade outside
    them is reported as having no R rather than a wrong one.
    """
    spans = []
    for f in sorted(glob.glob(os.path.join(folder, "*activity-log*.csv"))):
        stamps = [r["Time"] for r in csv.DictReader(io.open(f, encoding="utf-8-sig"))
                  if r.get("Time")]
        if stamps:
            spans.append((min(stamps), max(stamps)))
    return sorted(spans)


def covered(spans, open_t, close_t):
    """Is this whole trade inside a stretch the activity log covers?"""
    return any(lo <= open_t and close_t <= hi for lo, hi in spans)


def read_start_balance(folder):
    """The account balance before the first trade, if that export is present.

    Without it the equity curve can still be drawn from zero, but it will show
    profit rather than the account, and drawdown loses its scale.
    """
    rows = []
    for f in sorted(glob.glob(os.path.join(folder, "*balance-history*.csv"))):
        rows += list(csv.DictReader(io.open(f, encoding="utf-8-sig")))
    if not rows:
        return None
    rows.sort(key=lambda r: r.get("Time", ""))
    try:
        return float(rows[0]["Balance before"])
    except (KeyError, ValueError, TypeError):
        return None


def read_broker_trades(folder):
    """The broker's own list of round trips, if that export is present.

    This is the one export that says what TradingView thinks each trade was,
    rather than leaving it to be worked out from the fills. It exists to be
    disagreed with: if folding the fills into round trips produces a different
    answer, one of the two is wrong and it needs saying out loud rather than
    quietly publishing a number.

    It earned its place on 4 September. A YM long was opened with one contract
    and three more a minute later, and reading fills as strictly alternating
    turned the second buy into an exit. That invented a trade. The broker's
    export had it right all along and nothing was checking against it.
    """
    out = {}
    for f in sorted(glob.glob(os.path.join(folder, "*trade-history*.csv"))):
        for r in csv.DictReader(io.open(f, encoding="utf-8-sig")):
            raw = r.get("Symbol", "")
            sym = TICKER.get(raw, raw.split(":")[-1].replace("1!", ""))
            kind = (r.get("Type") or "").strip().lower()
            try:
                num = int(r.get("Trade number", ""))
                px = float(r.get("Price", ""))
                pnl = float(r.get("Net PnL USD", ""))
                qty = float(r.get("Size (qty)", ""))
            except (TypeError, ValueError):
                continue
            t = out.setdefault((sym, num), {"symbol": sym, "n": num, "pnl": pnl,
                                            "qty": qty})
            if kind.startswith("entry"):
                t["side"] = "Long" if kind.endswith("long") else "Short"
                t["entry"] = px
                t["open_t"] = r.get("Date and time", "")
            elif kind.startswith("exit"):
                t["exit"] = px
                t["close_t"] = r.get("Date and time", "")
    return [t for t in out.values() if "entry" in t and "exit" in t]


def reconcile(mine, broker):
    """Compare what the fills say to what the broker says. Report the gaps."""
    if not broker:
        return []
    problems = []
    by_sym = {}
    for t in mine:
        by_sym.setdefault(t["symbol"], []).append(t)
    for sym, want in sorted({t["symbol"]: None for t in broker}.items()):
        theirs = sorted([b for b in broker if b["symbol"] == sym],
                        key=lambda b: b["n"])
        ours = sorted(by_sym.get(sym, []), key=lambda t: t["open_t"])
        if len(theirs) != len(ours):
            problems.append(f"{sym}: broker lists {len(theirs)} round trips, "
                            f"the fills fold into {len(ours)}")
            continue
        for b, o in zip(theirs, ours):
            if abs(b["pnl"] - o["pnl"]) > 0.5:
                problems.append(f"{sym} trade {b['n']}: broker ${b['pnl']:,.2f}, "
                                f"fills ${o['pnl']:,.2f}")
            elif abs(b["entry"] - o["entry"]) > 0.26:
                problems.append(f"{sym} trade {b['n']}: broker entry "
                                f"{b['entry']}, fills {o['entry']}")
    return problems


REPLAY_SOURCES = {
    ("NQ", "1m"): ["data/collected/NQ_1m.parquet", "data/store/nasdaq_duka_1m.parquet"],
    ("NQ", "5m"): ["data/collected/NQ_5m.parquet", "data/store/nasdaq_duka_5m.parquet"],
    ("NQ", "15m"): ["data/collected/NQ_5m.parquet", "data/store/nasdaq_duka_5m.parquet"],
    ("NQ", "1h"): ["data/collected/NQ_1h.parquet"],
    ("ES", "1m"): ["data/collected/ES_1m.parquet", "data/store/sp500_duka_1m.parquet"],
    ("ES", "5m"): ["data/collected/ES_5m.parquet", "data/store/sp500_duka_5m.parquet"],
    ("ES", "15m"): ["data/collected/ES_5m.parquet", "data/store/sp500_duka_5m.parquet"],
    ("ES", "1h"): ["data/collected/ES_1h.parquet"],
}
_replay_bars = {}


def _bars_for(sym, tf):
    key = (sym, tf)
    if key in _replay_bars:
        return _replay_bars[key]
    parts = []
    for rel in REPLAY_SOURCES.get(key, []):
        full = os.path.join(ROOT, rel)
        if not os.path.exists(full):
            continue
        f = pd.read_parquet(full)[["open", "high", "low", "close"]].dropna()
        if f.index.tz is None:
            f.index = f.index.tz_localize("UTC")
        parts.append(f)
    d = None
    if parts:
        d = pd.concat(parts)
        d = d[~d.index.duplicated(keep="first")].sort_index()
    _replay_bars[key] = d
    return d


def judge_replay(t, after_min=45):
    """Give a practice trade the same reading a real one gets.

    Practice with no feedback just rehearses whatever you already do. So the
    bars the trade happened on are reloaded and the same questions asked: how
    far did it run your way, how much of that did you keep, and once you were
    out did price go on to your target or turn around.

    The flag vocabulary is deliberately the one live trades use, so a habit that
    shows up in practice is recognisable when it shows up for real.
    """
    d = _bars_for(t["symbol"], t.get("tf", "5m"))
    risk = t.get("risk_pts")
    if d is None or d.empty or not risk:
        return t
    try:
        a = pd.Timestamp(t["open_t"], tz="UTC")
        b = pd.Timestamp(t["close_t"], tz="UTC")
    except (ValueError, TypeError):
        return t

    live = d[(d.index >= a) & (d.index <= b)]
    after = d[(d.index > b) & (d.index <= b + pd.Timedelta(minutes=after_min))]
    if live.empty:
        return t
    short = t["side"] == "Short"

    def fav(seg):
        if seg.empty:
            return 0.0
        return float((t["entry"] - seg["low"].min()) if short
                     else (seg["high"].max() - t["entry"]))

    t["mfe_r"] = round(fav(live) / risk, 2)
    t["mae_r"] = round((float(live["high"].max()) - t["entry"]) / risk, 2) if short \
        else round((t["entry"] - float(live["low"].min())) / risk, 2)
    if t["mfe_r"] > 0:
        t["kept_pct"] = (round(max(t["got_r"], 0) / t["mfe_r"] * 100)
                         if t.get("got_r") is not None else None)

    flags, notes = [], []
    if t["exit_type"] == "target":
        flags.append("target hit")
    if t["planned_rr"] and t["planned_rr"] < 1:
        flags.append("target far out")
        notes.append(f"Risked {risk:,.2f} points to make "
                     f"{risk * t['planned_rr']:,.2f}. A trade has to win far more "
                     f"often than half the time just to break even on that shape.")

    if not after.empty:
        ran = round(fav(after) / risk, 2)
        if t["got_r"] is not None and t["got_r"] < 0 and ran >= 1.0:
            flags.append("right, stopped early")
            notes.append(f"Price then ran {ran:.2f}R past your entry the way you "
                         f"took it, inside {len(after)} bars of being stopped. The "
                         f"read was right and the stop was inside the noise.")
        if (t["exit_type"] == "manual" and t["got_r"] is not None
                and t["got_r"] > 0 and t.get("target")):
            reach = (float(after["low"].min()) <= t["target"]) if short \
                else (float(after["high"].max()) >= t["target"])
            if reach:
                flags.append("cut short")
                notes.append(f"Price reached your target shortly after you closed. "
                             f"You took {t['got_r']:+.2f}R of a "
                             f"{t['planned_rr']:.2f}R trade.")

    if (t.get("kept_pct") is not None and t["got_r"] is not None
            and t["got_r"] > 0 and t["kept_pct"] < 55):
        flags.append("closed early")
        notes.append(f"You kept {t['kept_pct']}% of the best price the trade "
                     f"offered, which peaked at {t['mfe_r']:.2f}R.")

    t["flags"] = flags
    t["flags_base"] = list(flags)
    t["note"] = " ".join(notes) if notes else (
        "Nothing mechanical to flag. Entry, stop and exit behaved as set.")
    t["note_base"] = t["note"]
    return t


def read_replay(folder):
    """Practice trades exported from the bar replay page.

    These are tagged and kept apart from live trades on purpose. Practice
    folded into the real record would flatter or wreck it, and the number you
    would check before funding an account would stop meaning anything.
    """
    p = os.path.join(folder, "replay_trades.json")
    if not os.path.exists(p):
        return []
    out = []
    for r in json.load(io.open(p, encoding="utf-8")):
        day = r.get("day")
        if not day or r.get("got_r") is None:
            continue
        step = int(str(r.get("tf", "5m"))[:-1] or 5)
        out.append({
            "source": "replay", "symbol": r["symbol"], "side": r["side"], "qty": 1,
            "open_t": f"{day} {r['open_t']}:00", "close_t": f"{day} {r['close_t']}:00",
            "entry": r["entry"], "exit": r["exit"],
            "stop": r["stop"], "target": r["target"],
            "initial_stop": r["stop"], "final_stop": r["stop"], "stop_moved": False,
            "risk_pts": r["risk_pts"], "reward_pts": abs(r["target"] - r["entry"]),
            "planned_rr": r["planned_rr"], "got_r": r["got_r"], "got_pts": r["got_pts"],
            "pnl": r["pnl"], "exit_type": r.get("exit_type", ""),
            "held_min": int(r.get("bars", 0)) * step,
            "trail": [], "flags": [], "flags_base": [],
            "note": "Practice on replayed bars. Not part of your live record.",
            "note_base": "Practice on replayed bars. Not part of your live record.",
        })
    # give practice the same reading a real trade gets, so a habit is
    # recognisable in the diary whichever set it turns up in
    return [judge_replay(t) for t in out]


def read_paper(folder):
    """Paper trades you placed by hand on the Demo tab, at real prices."""
    p = os.path.join(folder, "paper_state.json")
    if not os.path.exists(p):
        return []
    st = json.load(io.open(p, encoding="utf-8"))
    out = []
    for r in st.get("trades", []):
        if r.get("got_r") is None:
            continue
        o, c = str(r.get("at", ""))[:19], str(r.get("closed_at", ""))[:19]
        held = None
        try:
            held = int((pd.Timestamp(c) - pd.Timestamp(o)).total_seconds() // 60)
        except Exception:
            pass
        out.append({
            "source": "demo", "symbol": r["symbol"],
            "side": "Short" if r["side"] == "short" else "Long", "qty": 1,
            "open_t": o, "close_t": c,
            "entry": r["entry"], "exit": r["exit"],
            "stop": r["stop"], "target": r.get("target"),
            "initial_stop": r["stop"], "final_stop": r["stop"], "stop_moved": False,
            "risk_pts": r["risk_pts"],
            "reward_pts": (round(abs(r["target"] - r["entry"]), 2)
                           if r.get("target") else None),
            "planned_rr": r.get("planned_rr"),
            "got_r": r["got_r"], "got_pts": r["got_pts"], "pnl": r["pnl"],
            "exit_type": "manual", "held_min": held,
            "trail": [], "flags": [], "flags_base": [],
            "note": "Placed by hand on the Demo tab at a live, delayed price.",
            "note_base": "Placed by hand on the Demo tab at a live, delayed price.",
        })
    return out


def read_demo():
    """Trades the automated system has taken, across both books.

    Two books run against the same feed and differ only in how far the target
    sits from the stop. They are tagged separately, because a blended figure
    would hide the one question they exist to answer.
    """
    p = os.path.join(ROOT, "state", "demo_state.json")
    if not os.path.exists(p):
        return []
    st = json.load(io.open(p, encoding="utf-8"))
    out = []
    books = [("system", st)]
    if isinstance(st.get("wide"), dict):
        books.append(("system-wide", st["wide"]))
    for src, bk in books:
        out += _demo_trades(src, bk)
    return out


def _demo_trades(src, st):
    out = []
    for r in st.get("trades", []):
        risk = abs(r["entry"] - r["stop"])
        pts = (r["entry"] - r["exit"]) if r["side"] == "short" else (r["exit"] - r["entry"])
        out.append({
            "source": src, "symbol": r["symbol"],
            "side": "Short" if r["side"] == "short" else "Long",
            "qty": r.get("size", 1),
            "open_t": str(r["opened_at"])[:19], "close_t": str(r["closed_at"])[:19],
            "entry": r["entry"], "exit": r["exit"],
            "stop": r["stop"], "target": r.get("target"),
            "initial_stop": r["stop"], "final_stop": r["stop"], "stop_moved": False,
            "risk_pts": round(risk, 2),
            "reward_pts": round(abs(r["target"] - r["entry"]), 2) if r.get("target") else None,
            "planned_rr": (round(abs(r["target"] - r["entry"]) / risk, 2)
                           if r.get("target") and risk else None),
            # the demo's own R already carries the round-trip cost, so it is
            # kept rather than recomputed from price alone
            "got_r": r["r"], "got_pts": round(pts, 2), "pnl": r["pnl"],
            "exit_type": r.get("outcome", ""), "held_min": None,
            "trail": [], "flags": [], "flags_base": [],
            "note": "Taken by the automated demo, costs already charged.",
            "note_base": "Taken by the automated demo, costs already charged.",
        })
    return out


def pair_trades(fills):
    """Fold executions into round trips, per contract, in time order.

    Quantity is tracked properly rather than assuming fills alternate open,
    close, open, close. Adding to a position is a real thing you do: on
    4 September you bought 1 YM and then 3 more a minute later, and a strict
    alternation read that second buy as the exit of the first. That invented a
    trade you never took and left the rest of the position looking open.

    A fill the same way as the position averages into it. A fill the other way
    reduces it, and the round trip is only recorded when the position reaches
    flat. A fill big enough to go through flat closes what was there and opens
    the remainder the other way.
    """
    open_pos, trades = {}, []

    def close(sym, o, px, t, r, qty):
        pts = (o["px"] - px) if o["side"] == "sell" else (px - o["px"])
        pv = POINT.get(sym, 1.0)
        trades.append({
            "symbol": sym, "side": "Short" if o["side"] == "sell" else "Long",
            "qty": qty, "open_t": o["t"], "entry": round(o["px"], 4),
            "close_t": t, "exit": px, "pnl": round(pts * pv * qty, 2),
            "exit_type": r.get("Type", ""),
            "exit_stop_px": (float(r["Stop price"]) if r.get("Stop price") else None),
            "exit_limit_px": (float(r["Limit price"]) if r.get("Limit price") else None),
        })

    for r in fills:
        raw = r["Symbol"]
        sym = TICKER.get(raw, raw.split(":")[-1].replace("1!", ""))
        side = r["Side"].strip().lower()
        px, qty, t = float(r["Fill price"]), float(r["Quantity"]), r["Closing time"]
        o = open_pos.get(sym)

        if o is None:
            open_pos[sym] = {"side": side, "px": px, "qty": qty, "t": t,
                             "stop": r.get("Stop price"), "type": r.get("Type")}
            continue

        if side == o["side"]:
            # scaling in: the position's entry is the size-weighted average,
            # which is what the broker reports and what R has to be measured on
            total = o["qty"] + qty
            o["px"] = (o["px"] * o["qty"] + px * qty) / total
            o["qty"] = total
            continue

        done = min(qty, o["qty"])
        close(sym, o, px, t, r, done)
        left_open = o["qty"] - done
        if left_open > 1e-9:
            o["qty"] = left_open          # partial close, the rest runs on
            continue
        open_pos.pop(sym)
        flipped = qty - done
        if flipped > 1e-9:                # sold more than was held: now the other way
            open_pos[sym] = {"side": side, "px": px, "qty": flipped, "t": t,
                             "stop": r.get("Stop price"), "type": r.get("Type")}
    return trades, list(open_pos)


# ---------------------------------------------------------------------------
# analysis
# ---------------------------------------------------------------------------
def analyse(t, moves, spans=None):
    """Turn one round trip into facts, flags and a plain-English read."""
    entry, exit_, side = t["entry"], t["exit"], t["side"]
    short = side == "Short"

    rel = [m for m in moves if m["symbol"] == t["symbol"]
           and t["open_t"] <= m["t"] <= t["close_t"]]

    # The planned target is the one set when the trade was opened. Chris trails
    # the stop toward price as it approaches the target, so the stop changes
    # through the trade while the target usually does not.
    target = next((m["tp"] for m in rel if m["tp"]), None) or t.get("exit_limit_px")
    t["trail"] = [{"t": m["t"][11:], "sl": m["sl"]} for m in rel]

    # R is defined by the risk taken AT ENTRY, so use the FIRST stop of the
    # trade, never the last. Using the trailed stop divided a small loss by a
    # tiny remaining risk and produced -22R on one trade, dragging expectancy
    # to -3.8R on a day that made money. An impossible number is what caught it.
    #
    # The stop price on the exit order is only the entry stop when the stop was
    # never moved, and that is only knowable when the activity log covers the
    # trade. Outside that, there is no R to report. Saying so beats inventing a
    # denominator, which is the same mistake in a quieter form.
    no_log = False
    if rel:
        stop = rel[0]["sl"]
    elif spans is None or covered(spans, t["open_t"], t["close_t"]):
        stop = t.get("exit_stop_px")
    else:
        stop, no_log = None, True
    t["initial_stop"] = stop
    t["final_stop"] = rel[-1]["sl"] if rel else stop
    t["stop_moved"] = bool(rel) and abs(rel[-1]["sl"] - rel[0]["sl"]) > 0.01

    flags, notes = [], []
    risk = abs(entry - stop) if stop else None
    reward = abs(target - entry) if target else None
    got = (entry - exit_) if short else (exit_ - entry)

    t["stop"], t["target"] = stop, target
    t["risk_pts"] = round(risk, 2) if risk else None
    t["reward_pts"] = round(reward, 2) if reward else None
    t["planned_rr"] = round(reward / risk, 2) if (risk and reward) else None
    t["got_r"] = round(got / risk, 2) if risk else None
    t["got_pts"] = round(got, 2)
    t["held_min"] = int((pd.Timestamp(t["close_t"]) -
                         pd.Timestamp(t["open_t"])).total_seconds() // 60)

    # slippage: a stop is a market order and takes whatever price is there
    fired = t.get("exit_stop_px") or t.get("final_stop")
    if fired and t["exit_type"] == "Stop":
        slip = (exit_ - fired) if short else (fired - exit_)
        if slip > 0.01:
            flags.append("slipped")
            cost = (f"the loss came to {abs(t['got_r']):.2f}R rather than the 1R "
                    f"you risked" if t["got_r"] is not None
                    else "the loss came out bigger than the one you set")
            notes.append(f"The stop sat at {fired:,.2f} and filled at {exit_:,.2f}, "
                         f"{slip:,.2f} points worse. A stop is a market order: once "
                         f"touched it takes whatever price is there, so {cost}.")

    # a stop dragged to the wrong side of price fires the moment it is placed
    if len(rel) > 1:
        flags.append("trailed")
    if rel and stop:
        wrong = [m for m in rel if (short and m["sl"] < entry) or
                 (not short and m["sl"] > entry)]
        if wrong and t["got_r"] is not None and t["got_r"] < 0:
            m = wrong[-1]
            flags.append("stop wrong side")
            notes.append(f"At {m['t'][11:]} the stop was moved to {m['sl']:,.2f}, which "
                         f"is on the wrong side of a {side.lower()} entry at {entry:,.2f}. "
                         f"For a {side.lower()}, the stop is a "
                         f"{'buy' if short else 'sell'} order and must sit "
                         f"{'above' if short else 'below'} the market. Placed the other "
                         f"side it is already triggered, so it filled immediately. "
                         f"Trailing the stop in behind price is the plan, but here "
                         f"price had moved away from the target, not toward it, so "
                         f"there was no gain to protect yet.")

    # reached the target, or bailed early
    if target and reward:
        hit = (exit_ <= target + 0.01) if short else (exit_ >= target - 0.01)
        pct = got / reward * 100 if reward else 0
        if hit:
            flags.append("target hit")
            # TradingView caps the activity-log export, so on an older trade the
            # stop that was set can be off the end of it. Without a stop there is
            # no R to quote, and quoting it anyway took the whole ingest down.
            if t["planned_rr"] is not None and t["got_r"] is not None:
                notes.append(f"Reached the target. Planned {t['planned_rr']:.2f}R "
                             f"and took {t['got_r']:+.2f}R.")
            else:
                notes.append("Reached the target. No stop is recorded for this "
                             "trade, so there is no R to measure it against.")
        elif got > 0 and pct < 70:
            flags.append("closed early")
            notes.append(f"Closed by hand with {pct:.0f}% of the planned move: {got:,.2f} "
                         f"points of the {reward:,.2f} you were aiming at. Banking a "
                         f"winner is fine, but a target that far out makes every exit "
                         f"feel premature.")

    # a target so far away it was never the trade being managed
    if t["planned_rr"] and t["planned_rr"] >= 3.5:
        flags.append("target far out")

    # stopped almost immediately
    if t["held_min"] <= 1 and t["got_r"] is not None and t["got_r"] < 0:
        flags.append("stopped fast")

    if no_log:
        flags.append("no R")
        notes.insert(0, "No activity log covers this trade, so the stop you set "
                        "at entry is not on record and there is no R to measure. "
                        "The money is right; the R is simply unknown. Export the "
                        "activity log on the day you trade and this fills in.")
    elif stop is None:
        flags.append("no R")
        notes.insert(0, "No stop was set on this trade. R is defined by the risk "
                        "you take, so a trade with no stop has no R at all, and "
                        "no size that could have been worked out in advance.")

    t["flags"] = flags
    t["flags_base"] = list(flags)
    t["note"] = " ".join(notes) if notes else (
        "Nothing mechanical to flag. Entry, stop and exit all behaved as set.")
    t["note_base"] = t["note"]
    return t


def summarise(trades):
    """The figures a paid journal would give you."""
    done = [t for t in trades if t.get("got_r") is not None]
    rs = [t["got_r"] for t in done]
    pnl = [t["pnl"] for t in trades]
    wins = [x for x in pnl if x > 0]
    losses = [x for x in pnl if x < 0]
    streak = worst = 0
    for x in pnl:
        streak = streak + 1 if x <= 0 else 0
        worst = max(worst, streak)
    eq, peak, dd = 0.0, 0.0, 0.0
    for x in pnl:
        eq += x
        peak = max(peak, eq)
        dd = max(dd, peak - eq)
    return {
        "trades": len(trades),
        "wins": len(wins), "losses": len(losses),
        "win_rate": round(len(wins) / len(pnl) * 100, 1) if pnl else 0,
        "pnl": round(sum(pnl), 2),
        "avg_win": round(sum(wins) / len(wins), 2) if wins else 0,
        "avg_loss": round(sum(losses) / len(losses), 2) if losses else 0,
        "expectancy_r": round(sum(rs) / len(rs), 3) if rs else None,
        "total_r": round(sum(rs), 2) if rs else None,
        "worst_streak": worst,
        "max_dd": round(dd, 2),
        "longs": sum(1 for t in trades if t["side"] == "Long"),
        "shorts": sum(1 for t in trades if t["side"] == "Short"),
    }


# ---------------------------------------------------------------------------
# candles
# ---------------------------------------------------------------------------
def attach_bars(trades):
    """The minute bars each trade happened on.

    Yahoo only keeps a few days of one-minute history, so this can only be done
    while a trade is recent. Bars are cached into the store on first run and
    reused after that, which is what lets old trades still be reviewed.
    """
    from data.fetch import yahoo
    feeds, got = {}, 0
    for t in trades:
        # Only live trades get candles. Replay trades are historical, and the
        # one-minute feed only reaches back a few days, so asking for them
        # would burn time and come back empty every run.
        if t.get("source", "live") != "live" or t.get("bars"):
            continue
        sym = FEED.get(t["symbol"])
        if not sym:
            continue
        if sym not in feeds:
            try:
                feeds[sym] = yahoo(sym, "1m", "5d", max_age=900)
            except Exception as e:
                print(f"  {sym}: feed unavailable ({type(e).__name__})")
                feeds[sym] = None
        d = feeds[sym]
        if d is None or d.empty:
            continue
        base = pd.Timedelta(hours=LOCAL_OFFSET_H)
        lo = pd.Timestamp(t["open_t"], tz="UTC") - base - pd.Timedelta(minutes=PAD_BEFORE)
        hi = pd.Timestamp(t["close_t"], tz="UTC") - base + pd.Timedelta(minutes=PAD_AFTER)
        w = d[(d.index >= lo) & (d.index <= hi)]
        if w.empty:
            continue
        t["bars"] = [{"t": (ts + pd.Timedelta(hours=LOCAL_OFFSET_H)).strftime("%H:%M"),
                      "o": round(float(b["open"]), 2), "h": round(float(b["high"]), 2),
                      "l": round(float(b["low"]), 2), "c": round(float(b["close"]), 2)}
                     for ts, b in w.iterrows()]
        hhmm = t["open_t"][11:16]
        t["entry_i"] = next((i for i, b in enumerate(t["bars"]) if b["t"] == hhmm), 0)
        hhmm2 = t["close_t"][11:16]
        t["exit_i"] = next((i for i, b in enumerate(t["bars"]) if b["t"] == hhmm2),
                           len(t["bars"]) - 1)
        got += 1
    return got


def analyse_excursion(t):
    """Judge the trail against price, which needs the candles to be attached.

    Three questions a summary cannot answer: how far did price actually run in
    your favour, had it run far enough to justify each stop move, and once the
    trail took you out did price carry on to the target or reverse.
    """
    bars, risk = t.get("bars"), t.get("risk_pts")
    if not bars or not risk:
        return t

    # This runs over every stored trade on every run, so it has to be
    # idempotent. Appending without resetting first doubled the flag counts and
    # repeated whole sentences in the note each time the journal was re-run.
    t["note"] = t.get("note_base", t.get("note", ""))
    t["flags"] = list(t.get("flags_base", t.get("flags", [])))
    short = t["side"] == "Short"
    entry, ei, xi = t["entry"], t.get("entry_i", 0), t.get("exit_i", len(bars) - 1)

    def fav(seq):      # points in your favour, best case, over these bars
        if not seq:
            return 0.0
        return (entry - min(b["l"] for b in seq)) if short else                (max(b["h"] for b in seq) - entry)

    live = bars[ei:xi + 1]
    t["mfe_r"] = round(fav(live) / risk, 2)
    t["mae_r"] = round((max(b["h"] for b in live) - entry) / risk, 2) if short else                  round((entry - min(b["l"] for b in live)) / risk, 2)
    if t["mfe_r"] > 0 and t.get("got_r") is not None:
        t["kept_pct"] = round(max(t["got_r"], 0) / t["mfe_r"] * 100)

    # judge each stop move against the travel behind it
    steps = []
    for m in t.get("trail", []):
        j = next((i for i, b in enumerate(bars) if b["t"] == m["t"][:5]), None)
        if j is None or j < ei:
            steps.append({**m, "fav_r": None})
            continue
        f = round(fav(bars[ei:j + 1]) / risk, 2)
        past = (m["sl"] < entry) if short else (m["sl"] > entry)
        be = abs(m["sl"] - entry) < 0.01
        kind = "wrong side" if past else ("breakeven" if be else "tighten")
        steps.append({**m, "fav_r": f, "kind": "initial" if not steps else kind})
    t["trail"] = steps

    # a tighten made before the rule says to is the habit worth seeing
    early = [x for x in steps[1:] if x.get("fav_r") is not None
             and x["fav_r"] < BREAKEVEN_AT_R and x.get("kind") != "wrong side"]
    if early:
        t.setdefault("flags", []).append("trailed early")
        x = early[0]
        t["note"] += (f" The stop was tightened at {x['t']} after price had run "
                      f"{x['fav_r']:.2f}R in your favour. Your rule holds the stop "
                      f"until about {BREAKEVEN_AT_R:.0f}R, so this came "
                      f"{BREAKEVEN_AT_R - x['fav_r']:.2f}R early.")
        if t["exit_type"] == "Stop":
            t["note"] += (" That tightened stop is what closed the trade, so the "
                          "early move is what ended it.")
        else:
            t["note"] += (" It cost nothing here because you closed by hand before "
                          "the tightened stop was reached.")

    # The most useful thing a journal can say about a loss: the read was right,
    # the stop was just too close. Measured from the entry, in the direction the
    # trade was taken, over the bars after it was closed.
    after = bars[xi + 1:]
    if after and t.get("got_r") is not None and t["got_r"] < 0:
        ran = round(fav(after) / risk, 2)
        if ran >= 1.0:
            t.setdefault("flags", []).append("right, stopped early")
            t["note"] += (f" Price then ran {ran:.2f}R past your entry in the "
                          f"direction you took, within {len(after)} minutes of being "
                          f"stopped. The read was right. A stop {risk:,.2f} points "
                          f"away sat inside the noise, not outside it.")

    # once out, did price carry on to the target or reverse
    if after and t.get("target") and "target hit" not in t.get("flags", []):
        reach = (min(b["l"] for b in after) <= t["target"]) if short else                 (max(b["h"] for b in after) >= t["target"])
        best = round(fav(bars[ei:]) / risk, 2)
        mins = len(after)
        if reach:
            t.setdefault("flags", []).append("cut short")
            t["note"] += (f" Price went on to reach your target within {mins} minutes "
                          f"of the exit. The trail took {t['got_r']:+.2f}R where the "
                          f"full move was worth {t['planned_rr']:.2f}R.")
        elif best - t["mfe_r"] < 0.05:
            t["note"] += (f" Price did not improve after the exit over the next "
                          f"{mins} minutes, so leaving early cost nothing here.")
    flag_release_window(t)

    # The opening line is written before the candles are read, so a trade that
    # looked clean on the order log alone could end up saying "nothing to flag"
    # and then list five things. If the candles found something, drop it.
    if len(t.get("flags", [])) > len(t.get("flags_base", [])):
        for opener in ("Nothing mechanical to flag. Entry, stop and exit all "
                       "behaved as set. ",
                       "Nothing mechanical to flag. Entry, stop and exit "
                       "behaved as set. "):
            if t["note"].startswith(opener):
                t["note"] = t["note"][len(opener):]
                break
    return t


# US macro data lands at fixed times, so this needs no calendar and no feed.
# 08:30 New York is the main data slot: payrolls, CPI, PPI, retail sales, and
# jobless claims every Thursday. 10:00 is the second slot, 14:00 is where the
# Fed statement goes. What is scheduled is the SLOT, not any particular number,
# which is exactly what makes this safe to check mechanically.
RELEASE_SLOTS = {"08:30": "the main US data slot",
                 "10:00": "the second US data slot",
                 "14:00": "the Fed statement slot"}


def ny_clock(stamp):
    """A SAST export stamp as New York wall time, honouring daylight saving.

    A fixed six-hour offset is right from March to November and an hour wrong
    for the rest of the year, which would put every winter check on the wrong
    minute. The zone database knows; hardcoding does not.
    """
    ts = pd.Timestamp(stamp) - pd.Timedelta(hours=LOCAL_OFFSET_H)
    return ts.tz_localize("UTC").tz_convert("America/New_York")


def flag_release_window(t, before_min=3):
    """Say so when a stop was taken in the last minutes before a release slot.

    This is not a rule telling you to avoid the news. It is the observation
    that the minute before a scheduled release is when a market reaches for
    resting stops, and a stop parked just above the last few highs is the
    easiest one in the book to reach for.

    4 September is the clearest case on record. A short on ES was stopped at
    08:29:32 New York, twenty-eight seconds before the 08:30 slot, on a spike
    that took out the prior twenty minutes of highs. The next bar fell thirty
    points and went straight through the target.
    """
    if t.get("exit_type", "").lower() not in ("stop", "stop loss"):
        return t
    try:
        ny = ny_clock(t["close_t"])
    except (ValueError, KeyError, TypeError):
        return t
    h, m, s = ny.hour, ny.minute, ny.second
    mins = h * 60 + m
    for slot, what in RELEASE_SLOTS.items():
        sh, sm = int(slot[:2]), int(slot[3:])
        gap = sh * 60 + sm - mins
        if 0 <= gap <= before_min and not (gap == 0 and s == 0):
            secs = gap * 60 - s
            t.setdefault("flags", []).append("stopped into the news")
            t["note"] += (f" That stop was taken {secs} seconds before {slot} "
                          f"New York, {what}. The minute before a scheduled "
                          f"release is when the market reaches for resting "
                          f"stops, and yours was sitting where it could reach.")
            break
    return t


# ---------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=DATA_DIR, help="folder holding the exports")
    ap.add_argument("--no-bars", action="store_true", help="skip fetching candles")
    a = ap.parse_args()

    os.makedirs(a.data, exist_ok=True)
    files, fills = read_exports(a.data)
    if not files:
        print(f"No exports found in {a.data}")
        print("Put your TradingView order-history CSV there and run again.")
        return
    moves = read_stop_moves(a.data)
    spans = log_coverage(a.data)
    fresh, still_open = pair_trades(fills)

    # Merge with whatever is already stored. The key carries the source, so a
    # replayed practice trade and a live one at the same minute stay separate.
    stored = json.load(io.open(STORE, encoding="utf-8")) if os.path.exists(STORE) else []
    for t in stored:
        t.setdefault("source", "live")
    by_key = {(t["source"], t["symbol"], t["open_t"]): t for t in stored}

    added = 0
    for t in fresh:
        t["source"] = "live"
        k = ("live", t["symbol"], t["open_t"])
        if k in by_key:
            continue
        by_key[k] = analyse(t, moves, spans)
        added += 1

    # practice and the automated demo come in beside the live trades, tagged
    for t in read_replay(a.data) + read_paper(a.data) + read_demo():
        k = (t["source"], t["symbol"], t["open_t"])
        if k in by_key:
            continue
        by_key[k] = t
        added += 1

    trades = sorted(by_key.values(), key=lambda t: t["open_t"])
    from collections import Counter
    per = Counter(t["source"] for t in trades)

    print(f"{len(files)} export(s), {len(fills)} filled orders")
    print(f"  {len(trades)} trades on record  ({added} new this run)")
    for src in ("live", "replay", "demo", "system"):
        if per.get(src):
            print(f"    {src:<7} {per[src]}")
    if still_open:
        print(f"  {len(still_open)} position(s) still open, not counted: {still_open}")

    # Check the fills against the broker's own round-trip export, if it is
    # there. A silent disagreement here means every number below is suspect.
    broker = read_broker_trades(a.data)
    if broker:
        gaps = reconcile([t for t in trades if t.get("source", "live") == "live"],
                         broker)
        if gaps:
            print(f"  DOES NOT MATCH the broker's own export on {len(gaps)} point(s):")
            for g in gaps:
                print(f"    {g}")
            print("    Trust the broker column. Something in the pairing is wrong.")
        else:
            print(f"  matches the broker's own export on all "
                  f"{len(broker)} round trips")

    if not a.no_bars:
        n = attach_bars(trades)
        print(f"  candles attached to {n} trade(s)")
        for t in trades:
            if t.get("source", "live") == "live":
                analyse_excursion(t)

    json.dump(trades, io.open(STORE, "w", encoding="utf-8"), indent=1)

    # keep the earliest balance ever seen, so a later export that starts
    # mid-history cannot quietly move the floor of the equity curve
    meta = json.load(io.open(META, encoding="utf-8")) if os.path.exists(META) else {}
    start = read_start_balance(a.data)
    if start is not None and (meta.get("start_balance") is None
                              or start < meta["start_balance"]):
        meta["start_balance"] = start
    json.dump(meta, io.open(META, "w", encoding="utf-8"), indent=1)
    if meta.get("start_balance"):
        print(f"  opening balance ${meta['start_balance']:,.2f}")
    s = summarise(trades)
    print()
    print(f"  win rate     {s['win_rate']}%  ({s['wins']}W / {s['losses']}L)")
    print(f"  net P&L      ${s['pnl']:,.2f}")
    if s["expectancy_r"] is not None:
        print(f"  expectancy   {s['expectancy_r']:+.3f}R over {s['trades']} trades")
    print(f"  avg win      ${s['avg_win']:,.2f}   avg loss ${s['avg_loss']:,.2f}")
    print(f"  worst streak {s['worst_streak']}   max drawdown ${s['max_dd']:,.2f}")
    print(f"  direction    {s['longs']} long / {s['shorts']} short")

    flagged = [f for t in trades for f in t.get("flags", [])]
    if flagged:
        from collections import Counter
        print("\n  what kept happening:")
        for k, v in Counter(flagged).most_common():
            print(f"    {k:<18} {v}")

    print(f"\n  stored in {STORE}")
    print("  run `python journal_render.py` to build the page")


if __name__ == "__main__":
    main()
