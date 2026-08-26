"""The daily written report: what happened, and what it does and does not mean.

Written in plain English on purpose. A report full of ratios invites you to read
the good ones and skip the rest. This one leads with the honest headline and
puts the caveat next to the number rather than in a footnote.

    python report.py                 today
    python report.py --days 7        the last week
    python report.py --save          also write it to reports/
"""
import argparse, os, sqlite3, sys
import datetime as dt
import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from paper.journal import Journal, DB
from backtest.guard import assess, Ledger

OUT = os.path.join(ROOT, "reports")


def _rows(days, source=None):
    db = sqlite3.connect(DB)
    cut = (dt.datetime.now() - dt.timedelta(days=days)).strftime("%Y-%m-%d")
    q = ("SELECT closed_at, symbol, side, entry, exit, outcome, pnl_cash, "
         "r_multiple, confluences, setup_tags FROM trades WHERE closed_at >= ?")
    args = [cut]
    if source == "live":
        # Replay trades are a test of the idea on old data, some of it since
        # shown to be unrepresentative. Mixing them into a live report would
        # report an edge that was never traded.
        q += " AND notes LIKE 'live%'"
    elif source == "replay":
        q += " AND (notes = 'replay' OR notes = '')"
    tr = db.execute(q + " ORDER BY closed_at", args).fetchall()
    dec = db.execute(
        "SELECT action, reason, COUNT(*) FROM decisions WHERE ts >= ? "
        "GROUP BY action, reason ORDER BY COUNT(*) DESC", (cut,)).fetchall()
    eq = db.execute(
        "SELECT ts, equity FROM equity WHERE ts >= ? ORDER BY ts", (cut,)).fetchall()
    db.close()
    return tr, dec, eq


def build(days=1, source="live"):
    tr, dec, eq = _rows(days, source)
    L = []
    w = L.append
    period = "today" if days == 1 else f"the last {days} days"
    stamp = dt.datetime.now().strftime("%Y-%m-%d %H:%M")

    w("=" * 66)
    w(f"  TRADING REPORT  -  {period}")
    w(f"  generated {stamp}")
    w("=" * 66)

    if not tr:
        w("")
        w("  No trades closed in this period.")
        if dec:
            w("")
            w("  The system did look. Here is why it stood aside:")
            for action, reason, n in dec[:8]:
                w(f"    {n:>5}  {action}: {reason}")
            w("")
            w("  Refusing to trade is the system working. A day with no setup")
            w("  is more common than a day with one, and forcing a trade to")
            w("  fill the day is the most expensive habit in this business.")
        else:
            w("  Nothing was even considered, which usually means the runner")
            w("  was not up or the feed returned no bars. Worth checking.")
        w("=" * 66)
        return "\n".join(L)

    r = np.array([t[7] for t in tr], dtype=float)
    cash = np.array([t[6] for t in tr], dtype=float)
    wins = int((r > 0).sum())

    w("")
    w("  WHAT HAPPENED")
    w(f"    trades closed        {len(tr)}")
    w(f"    won / lost           {wins} / {len(tr) - wins}")
    w(f"    win rate             {wins / len(tr) * 100:.0f}%")
    w(f"    money               ${cash.sum():+,.2f}")
    w(f"    in R                 {r.sum():+.2f}R  (average {r.mean():+.3f}R)")
    if len(eq) >= 2:
        w(f"    equity               ${eq[-1][1]:,.2f}")

    w("")
    w("  EVERY TRADE")
    for c_at, sym, side, entry, exit_, out, pnl, rr, conf, tags in tr:
        when = str(c_at)[:16]
        w(f"    {when}  {sym:<6} {side:<5} {entry:>9.2f} -> {exit_:>9.2f}  "
          f"{out:<7} {rr:+6.2f}R  ${pnl:+9.2f}   {conf} confluences")
        if tags:
            w(f"                     {str(tags)[:60]}")

    if dec:
        w("")
        w("  WHAT IT REFUSED")
        for action, reason, n in dec[:8]:
            if action != "approved":
                w(f"    {n:>5}  {reason}")

    # ---- the part that keeps the report honest ---------------------------
    w("")
    w("  WHAT THIS MEANS")
    if len(r) < 20:
        w(f"    Almost nothing, statistically. {len(r)} trades is far too few to")
        w("    tell skill from luck. A run of wins here and a run of losses")
        w("    would look equally convincing and neither would be.")
        w("    The number to watch is 100 trades, not this week's total.")
    else:
        v = assess(list(r), dataset="paper_live", label="daily report",
                   ledger=Ledger())
        w(f"    {v.headline}")
        w(f"    {v.detail}")

    if len(tr) and abs(r.sum()) > 3:
        w("")
        w("    A big swing in either direction over a handful of trades is")
        w("    variance, not evidence. Do not change the rules because of it.")

    w("")
    w("  STANDING CAVEAT")
    w("    No strategy in this system has passed the full evaluation yet.")
    w("    The live feed is delayed and covers one exchange, so fills here")
    w("    are optimistic. Treat these results as a test of the plumbing.")
    w("=" * 66)
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=1)
    ap.add_argument("--save", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--source", choices=["live", "replay", "all"], default="live",
                    help="live trades only by default; replay results are a "
                         "different question and are not averaged in")
    a = ap.parse_args()

    text = build(a.days, None if a.source == 'all' else a.source)
    if not a.quiet:
        print(text)
    if a.save:
        os.makedirs(OUT, exist_ok=True)
        p = os.path.join(OUT, dt.date.today().strftime("%Y-%m-%d.txt"))
        open(p, "w", encoding="utf-8").write(text)
        print(f"\nsaved to {p}")
    return text


if __name__ == "__main__":
    main()
