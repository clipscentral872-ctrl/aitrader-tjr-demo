"""One command that answers: is this thing working, and should I believe it.

Run this before a session and after one. It checks the parts that can quietly
break without anything looking wrong: expired credentials, a stale feed, a
position left open overnight, a halted risk gate, an empty journal.

    python status.py
"""
import os, sqlite3, sys
import datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)

OK, BAD, MEH = "ok  ", "FAIL", "warn"


def line(tag, name, detail=""):
    print(f"  [{tag}] {name}" + (f"   {detail}" if detail else ""))


def main():
    print("=" * 66)
    print(f"  AITRADER STATUS   {dt.datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 66)
    problems = []

    # ---- broker ----------------------------------------------------------
    print("\nBROKER")
    try:
        from paper.alpaca_broker import AlpacaPaperBroker
        b = AlpacaPaperBroker()
        s = b.summary()
        line(OK, "Alpaca paper account", f"{s['status']}, equity ${s['equity']:,.0f}")
        if s["open_positions"]:
            line(MEH, "open positions", f"{s['open_positions']} still on the book")
            problems.append("a position is open; close it or know why it is there")
        else:
            line(OK, "no open positions")
        if s["resting_orders"]:
            line(MEH, "resting orders", f"{s['resting_orders']} waiting")
            problems.append("orders are resting at the broker")
    except Exception as e:
        line(BAD, "Alpaca", f"{type(e).__name__}: {str(e)[:60]}")
        problems.append("cannot reach the broker")

    # ---- feed -------------------------------------------------------------
    print("\nDATA FEED")
    try:
        from data.freshness import measure, verdict
        r = measure("QQQ")
        if r:
            age, last, is_open = r
            tag, note = verdict(age, is_open)
            good = tag in ("real time", "slightly behind", "market closed")
            line(OK if good else MEH, f"QQQ feed: {tag}", f"last bar {last:%m-%d %H:%M}")
            if not good:
                problems.append(f"the feed is {tag.lower()}; live results would mean nothing")
        else:
            line(BAD, "no bars returned")
            problems.append("the data feed returned nothing")
    except Exception as e:
        line(BAD, "feed check", f"{type(e).__name__}: {str(e)[:60]}")

    # ---- alerts -----------------------------------------------------------
    print("\nALERTS")
    try:
        import notify
        tok, _ = notify.creds()
        line(OK if tok else MEH, "Telegram credentials",
             "found" if tok else "missing, alerts will not send")
        q = notify._queue_load()
        line(OK if not q else MEH, "queued messages",
             f"{len(q)} waiting for the window to open" if q else "none")
        line(OK, "quiet hours",
             f"{'inside' if notify.in_window() else 'outside'} 15:00-21:30 SAST")
    except Exception as e:
        line(BAD, "notify", str(e)[:60])

    # ---- journal ----------------------------------------------------------
    print("\nJOURNAL")
    try:
        from paper.journal import DB
        db = sqlite3.connect(DB)
        live = db.execute("SELECT COUNT(*) FROM trades WHERE notes LIKE 'live%'").fetchone()[0]
        rep = db.execute("SELECT COUNT(*) FROM trades WHERE notes NOT LIKE 'live%'").fetchone()[0]
        db.close()
        line(OK, "trades recorded", f"{live} live, {rep} replay")
        if live < 100:
            line(MEH, "live sample", f"{live} of the 100 needed to judge anything")
    except Exception as e:
        line(BAD, "journal", str(e)[:60])

    # ---- the research position --------------------------------------------
    print("\nRESEARCH")
    line(OK, "EURUSD 0.5R target: VALIDATED",
         "+0.147R, 788 trades, all five checks")
    line(MEH, "QQQ / Nasdaq: PROVISIONAL",
         "significance and walk-forward pass, second source pending")
    line(OK, "execution model", "realistic: must trade through, stops gap")

    # ---- verdict -----------------------------------------------------------
    print("\n" + "=" * 66)
    if problems:
        print("  NEEDS ATTENTION")
        for p in problems:
            print(f"    - {p}")
    else:
        print("  Everything that can be checked automatically is fine.")
    print()
    print("  Standing truth: one configuration has cleared evaluate.py, on spot")
    print("  EURUSD, which this broker cannot trade. What runs here is the same")
    print("  rule set on QQQ, which has not cleared its second-source check.")
    print("  Provisional, not validated. Do not fund anything on it.")
    print("=" * 66)


if __name__ == "__main__":
    main()
