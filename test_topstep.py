"""Does the paper account keep Topstep's rules the way Topstep does?

A prop firm's rules are the whole point of this book, so each one is checked on
made up days where the right answer is known in advance:

  1. the trading day starts at 18:00 New York, and nothing is held after 16:10
  2. the Max Loss Limit trails the END OF DAY balance and locks at $50,000
  3. a big day raises the target instead of passing early (consistency)
  4. two trading days at least, and the target met, to pass
  5. sizing stops at 50 micros, and refuses when one contract risks too much
  6. the loss limits are priced counting the open loss
  7. a failed attempt is filed and a fresh $50,000 starts at the next session
  8. fees: $49 a month, $49 a reset beyond the free one each renewal

    python test_topstep.py
"""
import datetime as dt
import functools
import sys
import os

print = functools.partial(print, flush=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

from paper import topstep as TS                            # noqa: E402

FAILS = []


def check(name, ok, detail=""):
    print(f"  [{'ok  ' if ok else 'FAIL'}] {name}" + (f"   {detail}" if detail else ""))
    if not ok:
        FAILS.append(f"{name}: {detail}")


def ny(s):
    return dt.datetime.fromisoformat(s)


def book():
    return TS.fresh({}, 1, "2026-09-14T08:00:00")


def end_day(b, day, pnl, traded=True):
    """Put a day on the book and settle it the way the poller does."""
    TS.roll(b, day, f"{day}T00:00:00")
    b["equity"] += pnl
    b["ts"]["traded_today"] = traded
    return TS.close_day(b)


def main():
    print("=" * 60)
    print("  TOPSTEP RULES")
    print("=" * 60)

    print("\n1. THE TRADING DAY")
    check("17:59 Monday belongs to Monday",
          TS.ts_day(ny("2026-09-14T17:59")) == dt.date(2026, 9, 14))
    check("18:00 Monday belongs to Tuesday",
          TS.ts_day(ny("2026-09-14T18:00")) == dt.date(2026, 9, 15))
    check("16:09 may still trade", not TS.must_be_flat(ny("2026-09-14T16:09")))
    check("16:10 must be flat", TS.must_be_flat(ny("2026-09-14T16:10")))
    check("17:59 still flat", TS.must_be_flat(ny("2026-09-14T17:59")))
    check("18:00 open again", not TS.must_be_flat(ny("2026-09-14T18:00")))

    print("\n2. THE MAX LOSS LIMIT TRAILS THE END OF DAY BALANCE")
    b = book()
    check("starts $2,000 under", b["ts"]["mll"] == 48_000, str(b["ts"]["mll"]))
    end_day(b, "2026-09-14", +1_000)
    check("a $51,000 close lifts it to $49,000", b["ts"]["mll"] == 49_000,
          str(b["ts"]["mll"]))
    end_day(b, "2026-09-15", -500)
    check("a losing day never lowers it", b["ts"]["mll"] == 49_000, str(b["ts"]["mll"]))
    end_day(b, "2026-09-16", +2_000)
    check("it stops for good at the starting balance", b["ts"]["mll"] == 50_000,
          str(b["ts"]["mll"]))
    end_day(b, "2026-09-17", +1_000)
    check("and stays there however high it goes", b["ts"]["mll"] == 50_000,
          str(b["ts"]["mll"]))

    print("\n3. CONSISTENCY")
    b = book()
    end_day(b, "2026-09-14", +2_000)
    check("a $2,000 day raises the target to $4,000", TS.need(b["ts"]) == 4_000,
          str(TS.need(b["ts"])))
    ev = end_day(b, "2026-09-15", +1_500)
    check("$3,500 is not enough after it", ev is None and b["ts"]["status"] == "active",
          f"{ev} {b['ts']['status']}")
    ev = end_day(b, "2026-09-16", +600)
    check("$4,100 is", ev == "passed", f"{ev} {b['ts']['reason']}")

    print("\n4. TWO DAYS AND THE TARGET")
    b = book()
    ev = end_day(b, "2026-09-14", +1_400)
    check("one day is never a pass", ev is None)
    ev = end_day(b, "2026-09-15", +1_700)
    check("$3,100 with a $1,700 best day is short of $3,400",
          ev is None and TS.need(b["ts"]) == 3_400, f"{ev} need {TS.need(b['ts'])}")
    ev = end_day(b, "2026-09-16", +400)
    check("$3,500 passes on the third day", ev == "passed" and b["ts"]["days_traded"] == 3,
          f"{ev} days {b['ts']['days_traded']}")
    b = book()
    end_day(b, "2026-09-14", +1_400)
    ev = end_day(b, "2026-09-15", +1_700, traded=False)
    check("a day with no trade does not count as a trading day",
          b["ts"]["days_traded"] == 1, str(b["ts"]["days_traded"]))

    print("\n5. SIZING")
    check("$200 at $8 a contract is 25", TS.contracts(200, 8) == 25)
    check("never more than 50 micros", TS.contracts(1_000, 8) == 50)
    check("none when one contract risks more than allowed", TS.contracts(100, 150) == 0)

    print("\n6. THE LOSS LIMITS COUNT THE OPEN LOSS")
    b = book()
    TS.roll(b, "2026-09-14", "2026-09-14T00:00:00")
    pos = {"side": "long", "entry": 100.0, "size": 10}
    mll_px, dll_px = TS.limit_prices(b, pos, 2.0)
    check("a long touches the $2,000 limit 100 points down", abs(mll_px - 0.0) < 1e-9,
          str(mll_px))
    check("and the $1,000 daily limit 50 points down", abs(dll_px - 50.0) < 1e-9,
          str(dll_px))
    pos = {"side": "short", "entry": 100.0, "size": 10}
    mll_px, dll_px = TS.limit_prices(b, pos, 2.0)
    check("a short the same distance up", abs(mll_px - 200.0) < 1e-9
          and abs(dll_px - 150.0) < 1e-9, f"{mll_px} {dll_px}")
    b["equity"] -= 400                       # down $400 on the day already
    pos = {"side": "long", "entry": 100.0, "size": 10}
    _, dll_px = TS.limit_prices(b, pos, 2.0)
    check("a day already down $400 has $600 of room left", abs(dll_px - 70.0) < 1e-9,
          str(dll_px))

    print("\n7. FAILING, AND THE RESET")
    b = book()
    TS.roll(b, "2026-09-14", "2026-09-14T00:00:00")
    b["equity"] = 47_990
    TS.after_close(b, "mll")
    check("touching the limit fails the attempt", b["ts"]["status"] == "failed")
    ok, why = TS.gate(b, ny("2026-09-14T10:00"))
    check("and nothing more is opened that day", not ok, why)
    TS.roll(b, "2026-09-15", "2026-09-15T00:00:00")
    check("the next session starts attempt 2 at $50,000",
          b["ts"]["attempt"] == 2 and b["equity"] == 50_000
          and b["ts"]["status"] == "active", f"{b['ts']['attempt']} {b['equity']}")
    check("the failure is on file", len(b["ts"]["history"]) == 1
          and b["ts"]["history"][0]["result"] == "failed")
    b2 = book()
    TS.roll(b2, "2026-09-14", "2026-09-14T00:00:00")
    b2["equity"] -= 1_000
    TS.after_close(b2, "dll")
    check("the daily limit stops the day but is not a failure",
          b2["ts"]["dll_hit"] and b2["ts"]["status"] == "active")

    print("\n8. FEES")
    f = TS.fees(b, "2026-09-20T00:00:00")
    check("one month and one reset is $98", f["total"] == 98, str(f))
    f = TS.fees(b, "2026-10-20T00:00:00")
    check("a month later the renewal's free reset covers it", f["total"] == 98
          and f["resets"] == 0, str(f))

    print("\n9. THE POLLER KEEPS THEM, ON BARS")
    import tempfile
    import pandas as pd
    import poll_once
    from paper.risk import INSTRUMENTS
    poll_once.LOG_FILE = os.path.join(tempfile.gettempdir(), "topstep_test_log.txt")

    def run(pos, bars, equity=50_000.0, day_start=None, mll=48_000.0, start_utc=None):
        """Walk made up one minute bars through the Topstep book."""
        state = poll_once.blank_state()
        b = poll_once.book_of(state, "topstep")
        b["equity"] = equity
        TS.roll(b, TS.ts_day(poll_once._ny(pos["opened_at"])).isoformat(), "x")
        b["ts"]["day_start"] = equity if day_start is None else day_start
        b["ts"]["mll"] = mll
        b["position"] = dict(pos)
        idx = pd.date_range(start_utc, periods=len(bars), freq="1min", tz="UTC")
        df = pd.DataFrame(bars, columns=["open", "high", "low", "close"], index=idx)
        poll_once.manage_position(state, b, {pos["symbol"]: {"m1": df, "m5": df, "lag": 0}})
        return b

    # 15:50 New York is 19:50 UTC in September.
    pos = {"symbol": "MNQ", "side": "long", "size": 10.0, "entry": 20000.0,
           "stop": 19990.0, "target": 20020.0,
           "opened_at": "2026-09-14 19:49:00+00:00"}
    quiet = [(20001, 20003, 19998, 20001)] * 30          # 19:50 to 20:19 UTC
    b = run(pos, quiet, start_utc="2026-09-14 19:50")
    t = b["trades"][-1] if b["trades"] else {}
    check("a trade still open at 16:10 is flattened there",
          t.get("outcome") == "flat" and t.get("closed_at", "").startswith("2026-09-14 20:10"),
          f"{t.get('outcome')} at {t.get('closed_at')}")
    check("and the Combine carries on", b["ts"]["status"] == "active")

    # $100 of room above the Max Loss Limit on 50 micros is one point.
    pos = {"symbol": "MNQ", "side": "long", "size": 50.0, "entry": 20000.0,
           "stop": 19990.0, "target": 20020.0,
           "opened_at": "2026-09-14 14:00:00+00:00"}
    b = run(pos, [(20000, 20001, 19995, 19996)], equity=48_100.0,
            start_utc="2026-09-14 14:01")
    t = b["trades"][-1] if b["trades"] else {}
    check("touching the Max Loss Limit ends the trade before its stop",
          t.get("outcome") == "mll" and abs(t.get("exit", 0) - 19999.0) < 1e-6,
          f"{t.get('outcome')} at {t.get('exit')}")
    check("and fails the attempt", b["ts"]["status"] == "failed", b["ts"]["reason"])

    # Down $950 on the day: $50 of room on 50 micros is half a point.
    b = run(pos, [(20000, 20001, 19995, 19996)], equity=49_050.0, day_start=50_000.0,
            start_utc="2026-09-14 14:01")
    t = b["trades"][-1] if b["trades"] else {}
    check("the daily limit ends the trade at $1,000 down on the day",
          t.get("outcome") == "dll" and abs(t.get("exit", 0) - 19999.5) < 1e-6,
          f"{t.get('outcome')} at {t.get('exit')}")
    check("stops the day without failing",
          b["ts"]["dll_hit"] and b["ts"]["status"] == "active")

    pos = {"symbol": "MNQ", "side": "short", "size": 10.0, "entry": 20000.0,
           "stop": 20010.0, "target": 19980.0,
           "opened_at": "2026-09-14 14:00:00+00:00"}
    b = run(pos, [(20000, 20012, 19975, 19990)], start_utc="2026-09-14 14:01")
    t = b["trades"][-1] if b["trades"] else {}
    check("a bar reaching both the stop and the target is still a loss",
          t.get("outcome") == "loss", str(t.get("outcome")))
    check("every trade is tagged with its attempt", t.get("attempt") == 1)

    tmp = os.path.join(tempfile.gettempdir(), "topstep_summary_test.json")
    real = poll_once.SUMMARY_FILE
    poll_once.SUMMARY_FILE = tmp
    try:
        st = poll_once.blank_state()
        poll_once.book_of(st, "topstep")
        poll_once.save_summary(st)
        import json
        got = json.load(open(tmp, encoding="utf-8"))
        c = (got.get("topstep") or {}).get("combine") or {}
        check("the web summary carries the Combine",
              c.get("attempt") == 1 and c.get("need") == 3000 and c.get("mll") == 48000,
              json.dumps(c)[:120])
    finally:
        poll_once.SUMMARY_FILE = real
        if os.path.exists(tmp):
            os.remove(tmp)

    print("\n" + "=" * 60)
    print(f"  {len(FAILS)} FAILED" if FAILS else "  All Topstep rules hold.")
    print("=" * 60)
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
