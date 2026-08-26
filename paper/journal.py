"""The trade journal and performance database.

Every decision is written down, including the refusals. That last part matters:
a system that took 12 trades out of 300 candidates is telling you something
important, and it is invisible if you only log what you traded.

SQLite because it needs no server, survives restarts, and can be queried by the
dashboard directly.
"""
import os, sqlite3, json
import datetime as dt

DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                  "results", "journal.db")
os.makedirs(os.path.dirname(DB), exist_ok=True)

SCHEMA = """
CREATE TABLE IF NOT EXISTS trades (
    id TEXT PRIMARY KEY,
    symbol TEXT, side TEXT, size REAL,
    entry REAL, exit REAL, stop REAL, target REAL,
    opened_at TEXT, closed_at TEXT,
    outcome TEXT, pnl_cash REAL, r_multiple REAL,
    risk_cash REAL, costs REAL,
    confluences INTEGER, setup_tags TEXT,
    session TEXT, notes TEXT
);
CREATE TABLE IF NOT EXISTS decisions (
    ts TEXT, symbol TEXT, action TEXT, reason TEXT,
    side TEXT, entry REAL, stop REAL, target REAL, rr REAL,
    confluences INTEGER, setup_tags TEXT
);
CREATE TABLE IF NOT EXISTS equity (
    ts TEXT, equity REAL, open_positions INTEGER
);
CREATE INDEX IF NOT EXISTS ix_trades_closed ON trades(closed_at);
CREATE INDEX IF NOT EXISTS ix_dec_ts ON decisions(ts);
"""


class Journal:
    def __init__(self, path=DB):
        self.path = path
        self.db = sqlite3.connect(path, check_same_thread=False)
        self.db.executescript(SCHEMA)
        self.db.commit()

    # ---- writes ----------------------------------------------------------
    def record_trade(self, f, session="", source="replay"):
        self.db.execute(
            "INSERT OR REPLACE INTO trades VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f.id, f.symbol, f.side, f.size, f.entry, f.exit, f.stop, f.target,
             str(f.opened_at), str(f.closed_at), f.outcome, f.pnl_cash,
             f.r_multiple, f.risk_cash, f.costs, f.confluences, f.setup_tags,
             session, source))
        self.db.commit()

    def record_decision(self, ts, symbol, action, reason, setup=None):
        s = setup
        self.db.execute(
            "INSERT INTO decisions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (str(ts), symbol, action, reason,
             getattr(s, "side", None), getattr(s, "entry", None),
             getattr(s, "stop", None), getattr(s, "target", None),
             getattr(s, "rr", None), getattr(s, "confluences", None),
             getattr(s, "tags", None)))
        self.db.commit()

    def record_equity(self, ts, equity, open_positions=0):
        self.db.execute("INSERT INTO equity VALUES (?,?,?)",
                        (str(ts), float(equity), int(open_positions)))
        self.db.commit()

    # ---- reads -----------------------------------------------------------
    def performance(self):
        cur = self.db.execute(
            "SELECT r_multiple, pnl_cash, outcome, closed_at FROM trades "
            "ORDER BY closed_at")
        rows = cur.fetchall()
        if not rows:
            return {"trades": 0}
        rs = [r[0] for r in rows]
        wins = [r for r in rs if r > 0]
        losses = [r for r in rs if r <= 0]

        streak = worst = 0
        for r in rs:
            streak = streak + 1 if r <= 0 else 0
            worst = max(worst, streak)

        eq, peak, dd = 0.0, 0.0, 0.0
        for r in rs:
            eq += r
            peak = max(peak, eq)
            dd = max(dd, peak - eq)

        days = {}
        for r, pnl, _, closed in rows:
            d = str(closed)[:10]
            days[d] = days.get(d, 0.0) + r

        return {
            "trades": len(rs),
            "win_rate": round(100 * len(wins) / len(rs), 1),
            "avg_win_R": round(sum(wins) / len(wins), 2) if wins else 0.0,
            "avg_loss_R": round(sum(losses) / len(losses), 2) if losses else 0.0,
            "expectancy_R": round(sum(rs) / len(rs), 3),
            "total_R": round(sum(rs), 2),
            "total_pnl": round(sum(r[1] for r in rows), 2),
            "worst_losing_streak": worst,
            "max_drawdown_R": round(dd, 2),
            "trading_days": len(days),
            "profitable_days_pct": round(
                100 * sum(1 for v in days.values() if v > 0) / len(days), 1) if days else 0,
        }

    def refusals(self, limit=20):
        cur = self.db.execute(
            "SELECT reason, COUNT(*) c FROM decisions WHERE action='rejected' "
            "GROUP BY reason ORDER BY c DESC LIMIT ?", (limit,))
        return cur.fetchall()

    def recent_trades(self, n=20):
        cur = self.db.execute(
            "SELECT closed_at, symbol, side, outcome, r_multiple, pnl_cash, "
            "confluences, setup_tags FROM trades ORDER BY closed_at DESC LIMIT ?", (n,))
        return cur.fetchall()

    def equity_curve(self):
        cur = self.db.execute("SELECT ts, equity FROM equity ORDER BY ts")
        return cur.fetchall()

    def by_confluence(self):
        cur = self.db.execute(
            "SELECT confluences, COUNT(*), AVG(r_multiple), "
            "SUM(CASE WHEN r_multiple>0 THEN 1 ELSE 0 END)*1.0/COUNT(*) "
            "FROM trades GROUP BY confluences ORDER BY confluences")
        return cur.fetchall()

    def close(self):
        self.db.close()
