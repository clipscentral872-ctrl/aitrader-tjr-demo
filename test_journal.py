"""Check the reading a practice trade gets, on bars built to have a known answer.

The diary's job is to tell Chris what he did wrong. If that reading is itself
wrong it is worse than nothing, because it teaches a lesson the market never
taught. So the scenarios here are constructed so the correct verdict is known in
advance, and the analysis has to arrive at it.

Bars are injected into the module's cache rather than read from disk, so the
result does not drift when the data store grows.

    python test_journal.py
"""
import functools
import sys

print = functools.partial(print, flush=True)

import pandas as pd

import tradejournal as J

FAILED = []


def check(name, got, want):
    ok = got == want
    if not ok:
        FAILED.append(name)
    print(f"  {'pass' if ok else 'FAIL'}  {name}"
          + ("" if ok else f"   got {got!r}, want {want!r}"))


def bars(rows, start="2026-08-20 13:00"):
    """rows are (open, high, low, close) on five-minute spacing."""
    idx = pd.date_range(start, periods=len(rows), freq="5min", tz="UTC")
    return pd.DataFrame(rows, index=idx,
                        columns=["open", "high", "low", "close"])


def trade(**kw):
    base = {
        "source": "replay", "symbol": "NQ", "tf": "5m", "side": "Short", "qty": 1,
        "open_t": "2026-08-20 13:00:00", "close_t": "2026-08-20 13:10:00",
        "entry": 100.0, "exit": 95.0, "stop": 110.0, "target": 80.0,
        "risk_pts": 10.0, "planned_rr": 2.0, "got_r": 0.5, "got_pts": 5.0,
        "pnl": 100.0, "exit_type": "manual",
    }
    base.update(kw)
    return base


def run(name, rows, t, expect_flags, note_must_contain=None):
    J._replay_bars[("NQ", "5m")] = bars(rows)
    out = J.judge_replay(dict(t))
    check(name + " flags", sorted(out.get("flags", [])), sorted(expect_flags))
    if note_must_contain:
        got = note_must_contain.lower() in out.get("note", "").lower()
        check(name + " note mentions " + note_must_contain, got, True)
    return out


print("\na short that was right, stopped, then price fell hard")
# in at 100, stopped at 110 for -1R, then price collapses to 70 (3R his way)
out = run(
    "stopped early",
    [(100, 111, 99, 110),      # 13:00 the stop bar
     (110, 112, 105, 106),     # 13:05
     (106, 107, 85, 86),       # 13:10  close of the trade window
     (86, 87, 70, 71),         # 13:15  after: 3R past entry
     (71, 75, 70, 74)],
    trade(exit=110.0, got_r=-1.0, got_pts=-10.0, pnl=-200.0, exit_type="stop"),
    ["right, stopped early"], "the read was right")
check("mfe/mae computed", out.get("mae_r") is not None, True)

print("\nclosed by hand, then price reached the target anyway")
out = run(
    "cut short",
    [(100, 101, 96, 97),
     (97, 98, 94, 95),
     (95, 96, 93, 94),
     (94, 95, 79, 80),         # after the exit, target 80 is reached
     (80, 82, 78, 79)],
    trade(exit=95.0, got_r=0.5, got_pts=5.0, exit_type="manual"),
    ["cut short"], "reached your target")

print("\nrisking more than the trade stands to make")
# a real upside-down short: in at 100, stop 10 points away, target only 5
run("upside down rr",
    [(100, 101, 99, 100)] * 5,
    trade(stop=110.0, target=95.0, planned_rr=0.5, exit=99.0, got_r=0.1,
          got_pts=1.0, exit_type="manual"),
    ["target far out"], "break even")

print("\ntarget hit cleanly is not criticised")
run("clean target",
    [(100, 101, 96, 97),
     (97, 98, 80, 81),
     (81, 82, 79, 80),
     (80, 81, 79, 80),
     (80, 81, 79, 80)],
    trade(exit=80.0, got_r=2.0, got_pts=20.0, exit_type="target"),
    ["target hit"])

print("\ngave back most of a good move")
out = run(
    "closed early",
    [(100, 101, 99, 100),
     (100, 101, 82, 83),       # ran to 18 points his way, 1.8R
     (83, 98, 83, 97),         # handed it back
     (97, 98, 96, 97),
     (97, 98, 96, 97)],
    trade(close_t="2026-08-20 13:10:00", exit=97.0, got_r=0.3, got_pts=3.0,
          exit_type="manual"),
    ["closed early"], "best price")
check("kept_pct is a real fraction", 0 <= out.get("kept_pct", -1) <= 100, True)

print("\nno bars for that day leaves the trade alone rather than guessing")
J._replay_bars[("NQ", "5m")] = None
out = J.judge_replay(trade())
check("untouched without data", out.get("mfe_r"), None)


# ---------------------------------------------------------------------------
# Folding fills into round trips. Adding to a position is a real thing Chris
# does, and reading fills as strictly alternating turned an add into an exit.
# ---------------------------------------------------------------------------
def fill(side, qty, px, t, typ="Market"):
    return {"Symbol": "CME_MINI:NQ1!", "Side": side, "Quantity": str(qty),
            "Fill price": str(px), "Closing time": t, "Type": typ,
            "Stop price": "", "Limit price": ""}


print("\nadding to a position is not an exit")
got, still_open = J.pair_trades([
    fill("Buy", 1, 100.0, "2026-09-04 13:30:00"),
    fill("Buy", 3, 104.0, "2026-09-04 13:32:00"),
    fill("Sell", 4, 106.0, "2026-09-04 13:52:00"),
])
check("one round trip, not two", len(got), 1)
check("nothing left open", still_open, [])
check("entry is the size-weighted average", got[0]["entry"], 103.0)
check("size is the whole position", got[0]["qty"], 4.0)
# 4 contracts, 3 points each, NQ is $20 a point
check("P&L covers all four contracts", got[0]["pnl"], 240.0)

print("\nclosing half leaves the other half running")
got, still_open = J.pair_trades([
    fill("Buy", 2, 100.0, "2026-09-04 13:30:00"),
    fill("Sell", 1, 110.0, "2026-09-04 13:40:00"),
])
check("the closed half is recorded", len(got), 1)
check("only one contract in it", got[0]["qty"], 1.0)
check("the rest is still open", still_open, ["NQ"])

print("\nselling more than you hold flips the position")
got, still_open = J.pair_trades([
    fill("Buy", 1, 100.0, "2026-09-04 13:30:00"),
    fill("Sell", 3, 110.0, "2026-09-04 13:40:00"),
    fill("Buy", 2, 105.0, "2026-09-04 13:50:00"),
])
check("both round trips recorded", len(got), 2)
check("the long closed for a profit", got[0]["pnl"], 200.0)
check("the short that opened on the flip closed too", got[1]["side"], "Short")
check("flat at the end", still_open, [])

print("\nthe broker's own export is checked against, not trusted blindly")
mine = [{"symbol": "NQ", "open_t": "2026-09-04 13:30:00", "entry": 103.0,
         "pnl": 240.0}]
broker = [{"symbol": "NQ", "n": 1, "entry": 103.0, "exit": 106.0, "pnl": 240.0,
           "qty": 4.0, "side": "Long", "open_t": "", "close_t": ""}]
check("agreement is silent", J.reconcile(mine, broker), [])
wrong = [dict(mine[0], pnl=45.0)]
check("a P&L disagreement is reported", len(J.reconcile(wrong, broker)), 1)
split = mine + [dict(mine[0], open_t="2026-09-04 13:32:00")]
check("a count disagreement is reported", len(J.reconcile(split, broker)), 1)


# ---------------------------------------------------------------------------
# Stops taken in the last seconds before a scheduled release.
# ---------------------------------------------------------------------------
print("\na stop taken seconds before a release slot says so")
# 14:29:32 South Africa is 08:29:32 New York, 28 seconds before the data slot
out = J.flag_release_window({"close_t": "2026-09-04 14:29:32", "exit_type": "Stop",
                             "flags": [], "note": ""})
check("flagged", "stopped into the news" in out["flags"], True)
check("counts the seconds", "28 seconds before 08:30" in out["note"], True)

print("\nthe rest of the day is left alone")
out = J.flag_release_window({"close_t": "2026-09-04 16:31:00", "exit_type": "Stop",
                             "flags": [], "note": ""})
check("no flag away from a slot", out["flags"], [])
out = J.flag_release_window({"close_t": "2026-09-04 14:29:32",
                             "exit_type": "Take Profit", "flags": [], "note": ""})
check("a target hit is not a stop run", out["flags"], [])

print("\nwinter time is not summer time")
# 14:29:32 SAST in January is 07:29:32 New York, an hour off the slot
out = J.flag_release_window({"close_t": "2026-01-09 14:29:32", "exit_type": "Stop",
                             "flags": [], "note": ""})
check("daylight saving is honoured", out["flags"], [])
out = J.flag_release_window({"close_t": "2026-01-09 15:29:32", "exit_type": "Stop",
                             "flags": [], "note": ""})
check("the same slot in winter is found", out["flags"], ["stopped into the news"])

print("" if not FAILED else "\n" + str(len(FAILED)) + " failed: " + ", ".join(FAILED))
print("all checks passed" if not FAILED else "")
sys.exit(1 if FAILED else 0)
