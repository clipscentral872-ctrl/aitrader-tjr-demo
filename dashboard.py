"""Build a self-contained HTML dashboard from the trade journal.

One file, no server, no internet. Open it in a browser and it shows what the
system did and, just as importantly, what it REFUSED to do and why.

    python dashboard.py            # build and report the path
    python dashboard.py --open     # build and open it
"""
import argparse, json, os, sys, webbrowser
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from paper.journal import Journal   # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results",
                   "dashboard.html")

CSS = """
:root{--bg:#0f1115;--card:#171a21;--ink:#e8eaed;--mute:#8b93a1;--line:#252a34;
--up:#2E9E5B;--dn:#C4443A;--acc:#4C8DFF;--warn:#C9922B}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;padding:28px}
h1{font-size:20px;margin:0 0 4px;font-weight:600}
h2{font-size:13px;text-transform:uppercase;letter-spacing:.08em;color:var(--mute);
margin:28px 0 10px;font-weight:600}
.sub{color:var(--mute);font-size:13px;margin-bottom:24px}
.grid{display:grid;gap:12px;grid-template-columns:repeat(auto-fit,minmax(150px,1fr))}
.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px 16px}
.k{color:var(--mute);font-size:11px;text-transform:uppercase;letter-spacing:.06em}
.v{font-size:24px;font-weight:600;margin-top:4px;font-variant-numeric:tabular-nums}
.up{color:var(--up)} .dn{color:var(--dn)} .acc{color:var(--acc)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{text-align:left;color:var(--mute);font-size:11px;text-transform:uppercase;
letter-spacing:.06em;padding:8px 10px;border-bottom:1px solid var(--line);font-weight:600}
td{padding:8px 10px;border-bottom:1px solid var(--line);font-size:13px}
tr:last-child td{border-bottom:none}
.wrap{background:var(--card);border:1px solid var(--line);border-radius:10px;overflow:hidden}
.note{background:#1b1e26;border-left:3px solid var(--warn);padding:12px 16px;
border-radius:6px;color:var(--mute);font-size:13px;margin:16px 0}
.note b{color:var(--ink)}
.bar{height:6px;background:var(--line);border-radius:3px;overflow:hidden;margin-top:6px}
.bar i{display:block;height:100%;background:var(--acc)}
svg{display:block;width:100%;height:180px}
.empty{color:var(--mute);padding:24px;text-align:center}
"""


def spark(points, w=1000, h=180, pad=8):
    """Equity curve as an inline SVG. No library, no CDN."""
    if len(points) < 2:
        return '<div class="empty">not enough data yet</div>'
    lo, hi = min(points), max(points)
    rng = (hi - lo) or 1
    step = (w - 2 * pad) / (len(points) - 1)
    pts = " ".join(
        f"{pad + i * step:.1f},{h - pad - (v - lo) / rng * (h - 2 * pad):.1f}"
        for i, v in enumerate(points))
    up = points[-1] >= points[0]
    col = "#2E9E5B" if up else "#C4443A"
    base = h - pad
    return (f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none">'
            f'<polyline points="{pts}" fill="none" stroke="{col}" stroke-width="2"/>'
            f'<polyline points="{pad},{base} {pts} {w-pad},{base}" fill="{col}" '
            f'opacity="0.10" stroke="none"/></svg>')


def card(k, v, cls=""):
    return f'<div class="card"><div class="k">{k}</div><div class="v {cls}">{v}</div></div>'


def build():
    j = Journal()
    p = j.performance()
    trades = j.recent_trades(40)
    refusals = j.refusals(12)
    eq = j.equity_curve()

    if not p.get("trades"):
        body = ('<div class="note"><b>No trades recorded yet.</b> The journal is '
                'empty. Once the live run places something this fills in.</div>')
        stats_html = ""
        curve = '<div class="empty">no equity history yet</div>'
    else:
        exp = p["expectancy_R"]
        pnl = p["total_pnl"]
        stats_html = f"""
        <div class="grid">
          {card("Trades", p["trades"])}
          {card("Win rate", f'{p["win_rate"]}%')}
          {card("Expectancy", f'{exp:+.3f}R', "up" if exp > 0 else "dn")}
          {card("Total P&L", f'{pnl:+,.0f}', "up" if pnl > 0 else "dn")}
          {card("Total R", f'{p["total_R"]:+.1f}', "up" if p["total_R"] > 0 else "dn")}
        </div>
        <div class="grid" style="margin-top:12px">
          {card("Avg win", f'{p["avg_win_R"]:+.2f}R', "up")}
          {card("Avg loss", f'{p["avg_loss_R"]:+.2f}R', "dn")}
          {card("Worst streak", f'{p["worst_losing_streak"]} losses')}
          {card("Max drawdown", f'{p["max_drawdown_R"]:.1f}R')}
          {card("Profitable days", f'{p["profitable_days_pct"]}%')}
        </div>"""
        body = ""
        curve = spark([e[1] for e in eq]) if len(eq) > 1 else \
            '<div class="empty">no equity history yet</div>'

    rows = ""
    for t in trades:
        closed, sym, side, outcome, r, pnl, conf, tags = t
        cls = "up" if (r or 0) > 0 else "dn"
        rows += (f"<tr><td>{str(closed)[:16]}</td><td>{sym}</td>"
                 f"<td>{side}</td><td>{outcome}</td>"
                 f"<td class='{cls}'>{r:+.2f}R</td>"
                 f"<td class='{cls}'>{pnl:+,.0f}</td>"
                 f"<td>{conf or 0}</td>"
                 f"<td style='color:#8b93a1;font-size:12px'>{(tags or '')[:44]}</td></tr>")
    trades_html = (f'<div class="wrap"><table><tr><th>Closed</th><th>Symbol</th>'
                   f'<th>Side</th><th>Outcome</th><th>R</th><th>P&L</th>'
                   f'<th>Confl.</th><th>Why it qualified</th></tr>{rows}</table></div>'
                   if rows else '<div class="empty">no trades yet</div>')

    tot_ref = sum(n for _, n in refusals) or 1
    rrows = ""
    for reason, n in refusals:
        pct = n / tot_ref * 100
        rrows += (f"<tr><td>{reason}</td><td style='width:80px'>{n}</td>"
                  f"<td style='width:40%'><div class='bar'><i style='width:{pct:.0f}%'></i></div></td></tr>")
    ref_html = (f'<div class="wrap"><table><tr><th>Reason the trade was refused</th>'
                f'<th>Count</th><th></th></tr>{rrows}</table></div>'
                if rrows else '<div class="empty">nothing refused yet</div>')

    html = f"""<!doctype html><html><head><meta charset="utf-8">
<title>AI Trader</title><style>{CSS}</style></head><body>
<h1>AI Trader &mdash; paper account</h1>
<div class="sub">Built {dt.datetime.now():%A %d %B %Y, %H:%M} &nbsp;·&nbsp; Nasdaq, New York window</div>
{body}{stats_html}
<h2>Equity</h2>
<div class="wrap" style="padding:8px">{curve}</div>
<h2>Trades</h2>
{trades_html}
<h2>What the risk gate refused</h2>
<div class="sub" style="margin:0 0 10px">Refusals are data. A system that
refused 300 setups and took 5 is telling you something a P&amp;L figure cannot.</div>
{ref_html}
<div class="note"><b>Read live results carefully.</b> The free price feed is
delayed 10&ndash;15 minutes, so a live run proves the plumbing works, not that the
strategy makes money. A delayed feed cannot honestly execute a 5-minute entry.
This matters most on a good day, which is the easiest result here to misread.
The backtest needs roughly 100 trades before it means anything.</div>
</body></html>"""

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write(html)
    return OUT, p


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--open", action="store_true")
    a = ap.parse_args()
    path, perf = build()
    print(f"dashboard -> {path}")
    if perf.get("trades"):
        print(f"  {perf['trades']} trades, {perf['win_rate']}% win, "
              f"{perf['expectancy_R']:+.3f}R")
    else:
        print("  journal is empty, dashboard shows the empty state")
    if a.open:
        webbrowser.open("file:///" + path.replace("\\", "/"))
