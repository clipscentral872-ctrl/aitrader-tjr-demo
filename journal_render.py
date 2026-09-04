"""Turn the stored trades into a page you can actually look at.

The chart is drawn the way the position tool in TradingView draws it, because
that is how the trade was set up in the first place: a faded red band from the
entry out to the stop, a faded green band from the entry out to the target, and
the candles running through them. Bars after the exit are dimmed rather than
boxed off, so what price did next is visible without competing for attention.

Nothing is ever written over the candles. The values sit in a strip above the
chart and the levels get price tags on the right axis.
"""
import functools
import io
import json
import os

print = functools.partial(print, flush=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "journal_data", "trades.json")
OUT = os.path.join(ROOT, "journal_data", "journal.html")

FLAG_TEXT = {
    "slipped": "stop filled worse than it was set",
    "stop wrong side": "stop moved past the entry, so it fired at once",
    "trailed": "stop was trailed during the trade",
    "trailed early": "trailed before price had run 2R",
    "target hit": "reached the target",
    "closed early": "closed by hand well short of the target",
    "cut short": "price reached the target after the exit",
    "right, stopped early": "direction was right, stop was too tight",
    "target far out": "target set beyond 3.5R",
    "stopped fast": "stopped within a minute",
}
GOOD = {"target hit"}
BAD = {"stop wrong side", "slipped", "cut short", "closed early"}


META = os.path.join(ROOT, "journal_data", "meta.json")
LIB = os.path.join(ROOT, "For Learning")
GROUPS = ["Daily", "Weekly", "Overall"]


def library():
    """Whatever videos exist, grouped the way the folders are.

    The page is opened from disk through the desktop shortcut, so relative
    links reach the files. Published to the web the player has nothing to load,
    which is why the section says where the files actually live.
    """
    found = []
    for g in GROUPS:
        d = os.path.join(LIB, g)
        if not os.path.isdir(d):
            continue
        items = []
        for f in sorted(os.listdir(d), reverse=(g != "Overall")):
            if not f.lower().endswith(".mp4"):
                continue
            mb = os.path.getsize(os.path.join(d, f)) / 1048576
            items.append({"name": f[:-4],
                          "src": "../For Learning/" + g + "/" + f,
                          "mb": round(mb, 1)})
        if items:
            found.append({"group": g, "items": items})
    return found


def summarise(trades):
    from tradejournal import summarise as s
    return s(trades)


SOURCES = [("live", "Live"), ("demo", "Demo"), ("replay", "Replay"),
           ("system", "System"), ("all", "All")]
SOURCE_NOTE = {
    "live": "Trades you actually placed on the paper account.",
    "replay": "Practice on replayed bars. Deliberately kept out of your live figures.",
    "demo": "Paper trades you placed by hand on the Demo tab, at live prices.",
    "system": "Taken by the automated system, with round-trip costs already charged.",
    "all": "Everything together. Useful for volume, misleading as a record.",
}


def blocks(trades):
    """Stats and patterns per source, rendered once each.

    Worked out here rather than in the browser so the arithmetic stays in the
    one place it is already tested, and the page only has to show or hide.
    """
    from collections import Counter

    def stat(label, value, cls=""):
        return (f'<div class="stat"><span class="sl">{label}</span>'
                f'<span class="sv {cls}">{value}</span></div>')

    out = {}
    for src, _ in SOURCES:
        sel = [t for t in trades if src == "all" or t.get("source", "live") == src]
        if not sel:
            continue
        s = summarise(sel)
        pnl, exp = s["pnl"], s["expectancy_r"]
        sign = "+" if pnl >= 0 else "-"
        head = "".join([
            stat("net", f"{sign}${abs(pnl):,.0f}", "win" if pnl >= 0 else "loss"),
            stat("win rate", f"{s['win_rate']:.0f}%"),
            stat("record", f"{s['wins']}W / {s['losses']}L"),
            stat("expectancy", f"{exp:+.2f}R" if exp is not None else "&mdash;",
                 "win" if (exp or 0) >= 0 else "loss"),
            stat("avg win", f"${s['avg_win']:,.0f}", "win"),
            stat("avg loss", f"${abs(s['avg_loss']):,.0f}", "loss"),
            stat("max drawdown", f"${s['max_dd']:,.0f}"),
            stat("trades", f"{s['trades']}"),
        ])
        counts = Counter(f for t in sel for f in t.get("flags", []))
        pat = "".join(
            f'<li class="pat {"good" if k in GOOD else ("bad" if k in BAD else "")}">'
            f'<span class="pn">{v}</span><span class="pl">{FLAG_TEXT.get(k, k)}</span></li>'
            for k, v in counts.most_common())
        out[src] = {"head": head, "pat": pat or
                    '<li class="pat"><span class="pl">Nothing flagged.</span></li>',
                    "n": len(sel)}
    return out


def standing(trades):
    """Where the system actually stands, computed rather than asserted.

    A new trader's biggest risk with a tool like this is believing it. So the
    counts are worked out from the record every time the page is built, and the
    things that are simply true are stated flatly instead of being softened.
    """
    from collections import Counter
    n = Counter(t.get("source", "live") for t in trades)
    live, sysm = n.get("live", 0), n.get("system", 0) + n.get("system-wide", 0)
    rows = []

    def row(state, label, detail):
        rows.append(f'<li class="stand {state}"><span class="sl2">{label}</span>'
                    f'<span class="sd">{detail}</span></li>')

    row("no", "Not validated",
        "Nothing in this system has passed the full evaluate.py gate. It fails "
        "walk-forward because the folds are too thin, and second source because "
        "no independent futures feed is available for free.")
    row("no", "One config ever showed support",
        "EURUSD at a 0.5R target, +0.147R expectancy, about $500 a month on "
        "$50,000. Every other configuration tested came out negative or "
        "indistinguishable from zero.")
    row("no", "A filter was tested and rejected",
        "The exhaustion rule from TJR's teaching video was built and measured. "
        "On the denser feed the trades it refused were winners, so it was left "
        "switched off rather than kept because it sounded right.")
    row("warn", "The demo's win rate is a shape, not an edge",
        "The tuned book targets 0.6 to 0.8 times what it risks, so it wins most "
        "trades by design and the round trip eats close to half of each win. A "
        "second book at 1.3 to 2.2 now runs beside it on the same bars.")

    need = 100
    if live < need:
        row("warn", f"Your own record is {live} trades",
            f"About {need} are needed before a win rate or an expectancy means "
            f"anything. At {live} the numbers on this page describe what happened, "
            f"not what tends to happen.")
    else:
        row("ok", f"Your own record is {live} trades",
            "Enough to read an expectancy from, though a single month is still "
            "one market regime rather than a general result.")

    row("warn", f"The system's record is {sysm} trades",
        "The two books need a few hundred between them before the comparison "
        "settles anything.")

    # R is only as good as the stop it is measured against, and TradingView
    # caps the activity-log export, so some trades have no recorded entry stop.
    # Excluding them is honest but not neutral: if the ones missing an R happen
    # to be losers, the expectancy left behind is flattered. Say which way.
    mine = [t for t in trades if t.get("source", "live") == "live"]
    noR = [t for t in mine if t.get("got_r") is None]
    if noR:
        lost = sum(1 for t in noR if t["pnl"] < 0)
        row("warn", f"{len(noR)} of your {live} trades have no R",
            f"TradingView caps the activity-log export, so the stop set at entry "
            f"is off the end of it on those. The money is exact either way, but "
            f"the expectancy is measured on the other {live - len(noR)} only, and "
            f"{lost} of the {len(noR)} left out "
            f"{'were losses, so the R figure here reads better than the account did'
               if lost else 'were winners, so the R figure here reads worse than the account did'}"
            f". Export the activity log at the end of every session and this closes.")
    row("no", "Do not fund an account off this",
        "The profit targets this project started from were between six and "
        "eighty times what the one measured configuration produced.")
    return "".join(rows)


def build(trades, stats):
    data = json.dumps(trades, separators=(",", ":"))
    per = blocks(trades)
    stand = standing(trades)

    picker = "".join(
        f'<button class="src" data-src="{k}" onclick="pickSource(\'{k}\')">'
        f'{label}<span class="sn">{per[k]["n"]}</span></button>'
        for k, label in SOURCES if k in per)
    panes = "".join(
        f'<div class="pane-src" data-src="{k}" hidden>'
        f'<div class="stats hud">{per[k]["head"]}</div>'
        f'<p class="srcnote">{SOURCE_NOTE[k]}</p></div>'
        for k in per)
    patpanes = "".join(
        f'<ul class="pats pane-pat" data-src="{k}" hidden>{per[k]["pat"]}</ul>'
        for k in per)
    head = f'<div class="srcrow">{picker}</div>{panes}'

    meta = json.load(io.open(META, encoding="utf-8")) if os.path.exists(META) else {}
    start = meta.get("start_balance")

    lib = library()
    if lib:
        learn = "".join(
            '<div class="cutgroup"><h4>' + g["group"] + '</h4><div class="cutlist">' +
            "".join(
                '<button class="cut" onclick="playCut(this)" data-src="' + i["src"] + '">'
                '<span class="cn">' + i["name"] + '</span>'
                '<span class="cs">' + str(i["mb"]) + ' MB</span></button>'
                for i in g["items"]) +
            "</div></div>"
            for g in lib)
        section = LEARN_SECTION.replace("__CUTS__", learn)
    else:
        section = LEARN_EMPTY

    return (TEMPLATE.replace("__DATA__", data).replace("__HEAD__", head)
                    .replace("__PAT__", patpanes)
                    .replace("__NTRADES__", str(len(trades)))
                    .replace("__LEARN__", section)
                    .replace("__STAND__", stand)
                    .replace("__START__", json.dumps(start)))


LEARN_SECTION = """
<section>
  <h2>For Learning</h2>
  <p class="lead">Losers together and winners together, so a habit that repeats
  becomes obvious. Pick a cut to play it.</p>
  <div class="card hud" style="padding:18px">
    <video id="player" controls preload="none"></video>
    <p class="playing" id="playing">Nothing selected yet.</p>
    <div class="cuts">__CUTS__</div>
  </div>
</section>
"""

LEARN_EMPTY = """
<section>
  <h2>For Learning</h2>
  <p class="lead">No videos rendered yet. Run
  <code>python replay/make_videos.py</code> to build the library: every day
  three ways, every week split into losers and winners, and every trade you have
  ever taken sorted the same way.</p>
</section>
"""


TEMPLATE = r"""<title>Traders Diary</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800;900&family=Chakra+Petch:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap">
<style>
/* One committed dark treatment. This is read beside a dark charting platform,
   so the ground is painted explicitly rather than following the host theme. */
:root{
  --ground:#05070C; --raised:#0A0F17; --lift:#111A26;
  --line:#1B2838; --line-soft:#121A26;
  --text:#E8F0F8; --muted:#7E90A8; --faint:#4A5A70;
  --accent:#35E0F0; --accent-dim:rgba(53,224,240,.14);
  --win:#2BE08A; --loss:#FF5C6E;
  --win-faded:#177A4C; --loss-faded:#8E2F3A;
  --win-zone:rgba(43,224,138,.085); --loss-zone:rgba(255,92,110,.085);
  --candle-up:#22B877; --candle-dn:#C4485A;
}
*{box-sizing:border-box}
body{
  margin:0; color:var(--text);
  font-family:"Chakra Petch",system-ui,-apple-system,sans-serif;
  font-size:15px; line-height:1.55; -webkit-font-smoothing:antialiased;
  background:
    linear-gradient(rgba(53,224,240,.022) 1px, transparent 1px) 0 0/46px 46px,
    linear-gradient(90deg, rgba(53,224,240,.022) 1px, transparent 1px) 0 0/46px 46px,
    radial-gradient(1100px 520px at 50% -8%, rgba(53,224,240,.09), transparent 72%),
    var(--ground);
  background-attachment:fixed;
}
.wrap{max-width:1120px; margin:0 auto; padding:44px 22px 96px}
.num{font-family:"JetBrains Mono",ui-monospace,monospace; font-variant-numeric:tabular-nums}
.win{color:var(--win)} .loss{color:var(--loss)}

/* HUD corner brackets, the one flourish that carries the whole look */
.hud{position:relative}
.hud::before,.hud::after{
  content:""; position:absolute; width:17px; height:17px; pointer-events:none;
}
.hud::before{top:-1px; left:-1px; border-top:2px solid var(--accent); border-left:2px solid var(--accent)}
.hud::after{bottom:-1px; right:-1px; border-bottom:2px solid var(--accent); border-right:2px solid var(--accent)}

header{border-bottom:1px solid var(--line); padding-bottom:30px; margin-bottom:34px}

/* import panel */
.drop{
  border-style:dashed; border-width:1px; cursor:pointer; text-align:center;
  padding:34px 20px; transition:border-color .15s, background .15s;
}
.drop.over,.drop:hover{border-color:var(--accent); background:var(--lift)}
.drop:focus-visible{outline:2px solid var(--accent); outline-offset:3px}
.drop.busy{cursor:progress}
.dropmark{
  width:34px; height:34px; margin:0 auto 14px; border:2px solid var(--accent);
  border-top-color:transparent; border-right-color:transparent;
  transform:rotate(-45deg); box-shadow:0 0 18px var(--accent-dim);
}
.dropbig{
  font-family:"Orbitron",sans-serif; font-weight:800; font-size:17px;
  letter-spacing:.06em; text-transform:uppercase; margin:0 0 7px;
}
.dropsub{color:var(--muted); font-size:13px; margin:0}
.dropfiles{list-style:none; padding:0; margin:18px 0 0; display:grid; gap:5px}
.dropfiles li{
  display:flex; align-items:center; gap:9px; justify-content:center;
  font-family:"JetBrains Mono",monospace; font-size:11.5px; color:var(--muted);
}
.dropfiles li b{color:var(--text); font-weight:500}
.dropfiles li.used::before{content:"+"; color:var(--win); font-weight:700}
.dropfiles li.skip::before{content:"-"; color:var(--faint); font-weight:700}
.dropbar{height:2px; background:var(--line); margin-top:18px; overflow:hidden}
.dropbar i{
  display:block; height:100%; width:35%; background:var(--accent);
  box-shadow:0 0 10px var(--accent); animation:slide 1.1s ease-in-out infinite;
}
@keyframes slide{0%{margin-left:-35%}100%{margin-left:100%}}
@media (prefers-reduced-motion:reduce){.dropbar i{animation:none; width:100%}}
.dropmsg{
  margin:18px 0 0; font-size:13.5px; line-height:1.6; color:var(--text);
  white-space:pre-line;
}
.dropmsg.bad{color:var(--loss)}
.how{margin-top:16px; border:1px solid var(--line); background:var(--raised)}
.how summary{
  cursor:pointer; padding:12px 16px; font-size:12px; color:var(--muted);
  text-transform:uppercase; letter-spacing:.09em; font-weight:600;
}
.how summary:hover{color:var(--accent)}
.how[open] summary{border-bottom:1px solid var(--line); color:var(--text)}
.howsteps{margin:14px 18px 4px; padding-left:20px; color:var(--muted);
  font-size:13.5px; line-height:1.75}
.howsteps b{color:var(--text)}
.howwhy{margin:10px 18px 16px; color:var(--muted); font-size:13px; line-height:1.7}
.howwhy b{color:var(--text)}
h1{
  font-family:"Orbitron",sans-serif; font-weight:900; font-size:50px;
  line-height:1.08; margin:0 0 13px; letter-spacing:.012em; text-transform:uppercase;
  background:linear-gradient(178deg,#FFFFFF 8%,#9DE9F6 92%);
  -webkit-background-clip:text; background-clip:text; color:transparent;
  filter:drop-shadow(0 0 22px rgba(53,224,240,.34));
}
.sub{
  color:var(--muted); font-size:12.5px; margin:0; text-transform:uppercase;
  letter-spacing:.24em; font-weight:500;
}
.sub .num{color:var(--accent); letter-spacing:.1em}

.sources{margin-top:26px}
.srcrow{display:flex; flex-wrap:wrap; gap:7px; margin-bottom:16px}
.src{
  background:var(--raised); border:1px solid var(--line); color:var(--muted);
  font-family:"Chakra Petch",sans-serif; font-weight:600; font-size:11.5px;
  text-transform:uppercase; letter-spacing:.14em; padding:8px 14px; cursor:pointer;
  display:flex; align-items:baseline; gap:9px;
  transition:border-color .13s, color .13s, background .13s, box-shadow .13s;
}
.src:hover{border-color:var(--faint); color:var(--text)}
.src[aria-pressed="true"]{
  border-color:var(--accent); color:var(--text); background:var(--lift);
  box-shadow:0 0 20px rgba(53,224,240,.16);
}
.src:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.sn{font-family:"JetBrains Mono",monospace; font-size:12px; color:var(--accent)}
.srcnote{
  margin:12px 0 0; font-size:11.5px; color:var(--faint);
  text-transform:uppercase; letter-spacing:.11em;
}
.stats{
  display:grid; grid-template-columns:repeat(auto-fit,minmax(124px,1fr)); gap:1px;
  background:var(--line-soft); border:1px solid var(--line); margin-top:28px;
  box-shadow:0 0 40px rgba(53,224,240,.05);
}
.stat{
  background:var(--raised); padding:14px 16px; display:flex; flex-direction:column;
  gap:5px; position:relative;
}
.stat::before{
  content:""; position:absolute; top:0; left:0; width:22px; height:2px;
  background:var(--accent); opacity:.55;
}
.sl{
  font-size:9.5px; text-transform:uppercase; letter-spacing:.19em;
  color:var(--faint); font-weight:600;
}
.sv{
  font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
  font-size:20px; font-weight:700; letter-spacing:-.01em;
}
.sv.win{text-shadow:0 0 20px rgba(43,224,138,.4)}
.sv.loss{text-shadow:0 0 20px rgba(255,92,110,.35)}

h2{
  font-family:"Orbitron",sans-serif; font-weight:800; font-size:15px;
  margin:0 0 16px; letter-spacing:.13em; text-transform:uppercase; color:var(--text);
  display:flex; align-items:center; gap:13px;
}
h2::before{
  content:""; width:26px; height:2px; background:var(--accent);
  box-shadow:0 0 12px var(--accent); flex:none;
}
section{margin-bottom:44px}

/* `hidden` is only a default style, so any rule that sets display beats it.
   .pats sets display:flex, which is why every source's pattern list was
   drawn on top of the others instead of one at a time. */
[hidden]{display:none !important}
.pats{list-style:none; margin:0; padding:0; display:flex; flex-wrap:wrap; gap:9px}
.pat{
  display:flex; align-items:baseline; gap:11px; background:var(--raised);
  border:1px solid var(--line); padding:8px 15px 8px 12px;
  border-left:2px solid var(--faint);
}
.pat.bad{border-left-color:var(--loss)} .pat.good{border-left-color:var(--win)}
.pn{
  font-family:"JetBrains Mono",monospace; font-weight:700; font-size:16px;
  color:var(--accent);
}
.pl{font-size:13px; color:var(--muted)}

.tabs{display:flex; flex-wrap:wrap; gap:7px; margin-bottom:18px}
.tab{
  background:var(--raised); border:1px solid var(--line); color:var(--muted);
  padding:9px 15px; cursor:pointer; font:inherit; font-size:12px; display:flex; gap:11px;
  align-items:baseline; text-transform:uppercase; letter-spacing:.11em; font-weight:600;
  transition:border-color .14s,color .14s,background .14s,box-shadow .14s;
}
.tab:hover{border-color:var(--faint); color:var(--text)}
.tab[aria-selected="true"]{
  border-color:var(--accent); color:var(--text); background:var(--lift);
  box-shadow:0 0 22px rgba(53,224,240,.18), inset 0 0 22px rgba(53,224,240,.05);
}
.tab .r{
  font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
  font-weight:700; letter-spacing:0;
}
.tab:focus-visible{outline:2px solid var(--accent); outline-offset:2px}

.card{
  background:var(--raised); border:1px solid var(--line);
  box-shadow:0 0 50px rgba(53,224,240,.05);
}
.chead{
  display:flex; flex-wrap:wrap; align-items:baseline; gap:15px;
  padding:16px 20px 14px; border-bottom:1px solid var(--line-soft);
}
.chead .who{
  font-family:"Orbitron",sans-serif; font-size:14px; font-weight:800;
  text-transform:uppercase; letter-spacing:.08em;
}
.chead .when{
  font-size:12px; color:var(--muted); font-family:"JetBrains Mono",monospace;
}
.chead .res{
  margin-left:auto; font-family:"JetBrains Mono",monospace;
  font-variant-numeric:tabular-nums; font-size:18px; font-weight:700;
}
canvas{display:block; width:100%; height:410px}
.values{
  display:flex; flex-wrap:wrap; gap:1px; background:var(--line-soft);
  border-bottom:1px solid var(--line-soft);
}
.val{
  background:var(--raised); padding:10px 17px; display:flex; flex-direction:column;
  gap:3px; flex:1 1 auto; min-width:104px;
}
.vl{
  font-size:9px; text-transform:uppercase; letter-spacing:.19em; color:var(--faint);
  font-weight:600;
}
.vv{
  font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
  font-size:15.5px; font-weight:700;
}
.vv small{
  font-size:10.5px; color:var(--faint); font-weight:400; margin-left:6px;
  letter-spacing:.04em;
}
.legend{
  display:flex; flex-wrap:wrap; gap:19px; padding:12px 20px; font-size:10.5px;
  color:var(--muted); border-top:1px solid var(--line-soft);
  border-bottom:1px solid var(--line-soft); text-transform:uppercase;
  letter-spacing:.12em; font-weight:500;
}
.legend span{display:flex; align-items:center; gap:8px}
.box{width:16px; height:10px}
.solid{width:16px; height:0; border-top:2px solid currentColor}

.body{display:grid; grid-template-columns:minmax(0,1.1fr) minmax(0,1fr)}
@media(max-width:780px){ .body{grid-template-columns:1fr} }
.pane{padding:18px 20px}
.pane + .pane{border-left:1px solid var(--line-soft)}
@media(max-width:780px){ .pane + .pane{border-left:0; border-top:1px solid var(--line-soft)} }
.pane h3{
  font-family:"Orbitron",sans-serif; font-size:9.5px; text-transform:uppercase;
  letter-spacing:.15em; color:var(--accent); margin:0 0 13px; font-weight:700; opacity:.9;
}

table{width:100%; border-collapse:collapse; font-size:13px}
td{padding:5px 0; vertical-align:baseline}
td:first-child{
  color:var(--muted); padding-right:14px; white-space:nowrap;
  text-transform:uppercase; letter-spacing:.09em; font-size:11px; font-weight:500;
}
td:last-child{
  text-align:right; font-family:"JetBrains Mono",monospace;
  font-variant-numeric:tabular-nums; font-weight:500;
}
.dim{color:var(--faint)}
.note{font-size:14px; line-height:1.68; margin:0; color:#C3D2E2}
.trail{margin-top:20px}
.kind{
  display:inline-block; font-size:9px; letter-spacing:.14em; text-transform:uppercase;
  padding:1px 7px; border:1px solid var(--line); color:var(--faint); margin-left:9px;
  font-weight:600;
}
.kind.bad{border-color:var(--loss-faded); color:var(--loss)}
.kind.early{border-color:var(--accent); color:var(--accent)}
.flags{display:flex; flex-wrap:wrap; gap:7px; margin-bottom:15px}
.chip{
  font-size:10.5px; padding:3px 10px; border:1px solid var(--line); color:var(--muted);
  text-transform:uppercase; letter-spacing:.09em; font-weight:500;
}
.chip.bad{border-color:var(--loss-faded); color:var(--loss)}
.chip.good{border-color:var(--win-faded); color:var(--win)}
.stands{list-style:none; margin:0; padding:0; display:flex;
  flex-direction:column; gap:1px; background:var(--line-soft);
  border:1px solid var(--line)}
.stand{background:var(--raised); padding:13px 16px; display:flex; gap:16px;
  align-items:baseline; flex-wrap:wrap; border-left:2px solid var(--faint)}
.stand.no{border-left-color:var(--loss)}
.stand.warn{border-left-color:var(--accent)}
.stand.ok{border-left-color:var(--win)}
.sl2{font-family:"Orbitron",sans-serif; font-size:10px; font-weight:700;
  text-transform:uppercase; letter-spacing:.13em; flex:0 0 230px}
.stand.no .sl2{color:var(--loss)}
.stand.warn .sl2{color:var(--accent)}
.stand.ok .sl2{color:var(--win)}
.sd{font-size:13px; color:var(--muted); flex:1 1 320px; line-height:1.6}
#eq{display:block; width:100%; height:250px}
.eqhead{
  display:flex; flex-wrap:wrap; gap:24px; align-items:baseline;
  padding:14px 20px 12px; border-bottom:1px solid var(--line-soft);
}
.eql{
  font-size:9.5px; text-transform:uppercase; letter-spacing:.17em;
  color:var(--faint); font-weight:600;
}
.eql b{
  font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
  font-size:15px; font-weight:700; letter-spacing:0; margin-left:8px;
  text-transform:none;
}
.eqnote{
  margin-left:auto; font-size:10.5px; color:var(--faint);
  text-transform:uppercase; letter-spacing:.11em;
}
.lead{color:var(--muted); font-size:13.5px; margin:0 0 16px; max-width:66ch}
.bigbtn{
  display:inline-block; text-decoration:none; background:var(--lift);
  border:1px solid var(--accent); color:var(--text);
  font-family:"Orbitron",sans-serif; font-weight:700; font-size:12px;
  text-transform:uppercase; letter-spacing:.15em; padding:13px 26px;
  box-shadow:0 0 24px rgba(53,224,240,.16);
  transition:background .14s, box-shadow .14s;
}
.bigbtn:hover{background:var(--raised); box-shadow:0 0 34px rgba(53,224,240,.3)}
.bigbtn:focus-visible{outline:2px solid var(--accent); outline-offset:3px}
.lead code{
  font-family:"JetBrains Mono",monospace; font-size:12.5px; color:var(--accent);
  background:var(--lift); padding:2px 7px; border:1px solid var(--line);
}
#player{
  width:100%; display:none; background:#000; border:1px solid var(--line);
  margin-bottom:14px;
}
#player.on{display:block}
.playing{
  margin:0 0 16px; font-size:11px; color:var(--faint); text-transform:uppercase;
  letter-spacing:.15em; font-weight:600;
}
.cuts{display:flex; flex-direction:column; gap:20px}
.cutgroup h4{
  font-family:"Orbitron",sans-serif; font-size:10px; font-weight:700;
  letter-spacing:.19em; text-transform:uppercase; color:var(--accent);
  margin:0 0 10px; opacity:.9;
}
.cutlist{display:flex; flex-wrap:wrap; gap:8px}
.cut{
  background:var(--raised); border:1px solid var(--line); color:var(--text);
  padding:10px 15px; cursor:pointer; font:inherit; display:flex; flex-direction:column;
  gap:3px; align-items:flex-start; text-align:left; min-width:200px;
  transition:border-color .14s, box-shadow .14s, background .14s;
}
.cut:hover{border-color:var(--accent); background:var(--lift)}
.cut[aria-pressed="true"]{
  border-color:var(--accent); background:var(--lift);
  box-shadow:0 0 22px rgba(53,224,240,.18);
}
.cut:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.cn{font-size:12.5px; font-weight:600}
.cs{
  font-family:"JetBrains Mono",monospace; font-size:10.5px; color:var(--faint);
}
footer{
  margin-top:52px; padding-top:20px; border-top:1px solid var(--line);
  color:var(--faint); font-size:12px; max-width:70ch; line-height:1.7;
}
</style>

<div class="wrap">
<header>
  <h1>Traders Diary</h1>
  <p class="sub"><span class="num">__NTRADES__</span> Trades &nbsp;/&nbsp; TradingView Paper Account</p>
  <div class="sources">__HEAD__</div>
</header>

<section id="importer">
  <h2>Import a session</h2>
  <p class="lead">Drop all six TradingView exports in at once. Anything the
  diary cannot use is ignored, and the same file dropped twice changes
  nothing, so there is no wrong way to do this.</p>

  <div class="card hud drop" id="drop" tabindex="0" role="button"
       aria-label="Choose your TradingView export files">
    <input type="file" id="pick" multiple accept=".csv" hidden>
    <div class="dropface">
      <div class="dropmark" aria-hidden="true"></div>
      <p class="dropbig">Drop your exports here</p>
      <p class="dropsub">or click to choose them &nbsp;/&nbsp; CSV files from
      TradingView paper trading</p>
    </div>
    <ul class="dropfiles" id="dropfiles"></ul>
    <div class="dropbar" id="dropbar" hidden><i></i></div>
    <p class="dropmsg" id="dropmsg" hidden></p>
  </div>

  <details class="how">
    <summary>Where these files come from</summary>
    <ol class="howsteps">
      <li>In TradingView, open the <b>Trading Panel</b> at the bottom of the
      chart and pick your <b>Paper Trading</b> account.</li>
      <li>Click the <b>gear icon</b> on the right of that panel, then
      <b>Export data</b>.</li>
      <li>Tick everything it offers and download. You get six CSV files.</li>
      <li>Drag all six onto the box above.</li>
    </ol>
      <p class="howwhy">Three of the six do the work. <b>Order history</b> is
      every fill, and it is what the trades are built from. <b>Activity log</b>
      is the only record of a stop being moved, so without it a trade has no R.
      <b>Balance history</b> sets the opening balance so the equity curve shows
      the account rather than just profit. The other three are read as a
      cross-check: if what they say disagrees with what the fills say, the
      page tells you rather than quietly picking one.</p>
      <p class="howwhy">Export at the <b>end</b> of a session. TradingView caps
      the activity log at roughly the last hour of events, so exporting late
      catches the whole session and exporting the next morning misses it.</p>
  </details>
</section>

<section>
  <h2>Where this stands</h2>
  <p class="lead">Read this before you act on anything else on the page. It is
  rebuilt from the record every time, so it cannot quietly go out of date.</p>
  <ul class="stands" id="stands">__STAND__</ul>
</section>

<section>
  <h2>Equity curve</h2>
  <div class="card hud">
    <div class="eqhead">
      <span class="eql">Opened <b id="eqStart"></b></span>
      <span class="eql">Now <b id="eqNow"></b></span>
      <span class="eql">Peak <b id="eqPeak"></b></span>
    </div>
    <canvas id="eq"></canvas>
  </div>
</section>

<section>
  <h2>What kept happening</h2>
  __PAT__
</section>

<section>
  <h2>Bar Replay</h2>
  <p class="lead">Step a past session one bar at a time and trade it without
  seeing what comes next. Stops and targets fill on the same rules the
  backtester uses, so practice can be compared with the real thing rather than
  flattering it. Trades you save there arrive here under Replay, never mixed
  into your live figures.</p>
  <a class="bigbtn" href="replay.html">Open Bar Replay</a>
</section>

__LEARN__

<section>
  <h2>Trade by trade</h2>
  <div class="tabs" role="tablist" id="tabs"></div>
  <div class="card hud">
    <div class="chead" id="chead"></div>
    <div class="values" id="values"></div>
    <canvas id="c"></canvas>
    <div class="legend">
      <span><i class="box" style="background:var(--loss-zone); border:1px solid var(--loss-faded)"></i>risk to stop</span>
      <span><i class="box" style="background:var(--win-zone); border:1px solid var(--win-faded)"></i>reward to target</span>
      <span style="color:var(--text)"><i class="solid"></i>entry</span>
      <span style="color:var(--accent)"><i class="solid"></i>trailed stop</span>
      <span>faded candles are after your exit</span>
    </div>
    <div class="body">
      <div class="pane">
        <h3>The trade</h3>
        <table id="facts"></table>
        <div class="trail" id="trailbox"></div>
      </div>
      <div class="pane">
        <h3>What happened</h3>
        <div class="flags" id="flags"></div>
        <p class="note" id="note"></p>
      </div>
    </div>
  </div>
</section>

<footer>
  Drawn on one-minute bars from the same feed the system trades. R is measured
  against the stop set at entry, never the trailed one, so a tightened stop
  cannot flatter a result.
</footer>
</div>

<script>
const TRADES = __DATA__;
const FLAG_TEXT = __FLAGTEXT__;
const GOOD = ["target hit"], BAD = ["stop wrong side","slipped","cut short","closed early"];
const BE_AT_R = 2.0;
const MONO = '"JetBrains Mono", monospace';
let cur = 0;

// Which trades the whole page is describing. Live is the default because it is
// the only set that answers "is this working"; practice sitting in the same
// figures would quietly change that answer.
let VIEW = [];
let curSource = "live";

function pickSource(src){
  curSource = src;
  VIEW = TRADES.filter(t => src === "all" || (t.source || "live") === src);
  document.querySelectorAll(".src").forEach(b =>
    b.setAttribute("aria-pressed", b.dataset.src === src));
  document.querySelectorAll(".pane-src, .pane-pat").forEach(p =>
    p.hidden = p.dataset.src !== src);
  cur = 0;
  pick(0);
  drawEq();
}

const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const money = v => (v<0?"-":"+") + "$" + Math.abs(v).toLocaleString(undefined,{maximumFractionDigits:0});
const px = v => v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
// A trade with no stop, or one the activity log does not cover, has no R
// at all. Null is the honest answer and it must not be drawn as zero:
// null >= 0 is true in JavaScript, so it would have shown as a win.
const rr = v => v == null ? "no R" : (v>=0?"+":"") + v.toFixed(2) + "R";
const won = t => t.got_r == null ? t.pnl >= 0 : t.got_r >= 0;

function tabs(){
  document.getElementById("tabs").innerHTML = VIEW.map((t,i)=>
    '<button class="tab" role="tab" aria-selected="' + (i===cur) + '" onclick="pick(' + i + ')">' +
      '<span>' + (i+1) + ' / ' + t.symbol + ' ' + t.side + '</span>' +
      '<span class="r ' + (won(t)?"win":"loss") + '">' + rr(t.got_r) + '</span>' +
    '</button>').join("");
}

function head(){
  const t = VIEW[cur];
  document.getElementById("chead").innerHTML =
    '<span class="who">' + t.symbol + ' ' + t.side + ' &times;' + t.qty + '</span>' +
    '<span class="when">' + t.open_t.slice(0,10) + ' &nbsp;' + t.open_t.slice(11,16) +
      ' &rarr; ' + t.close_t.slice(11,16) + '</span>' +
    '<span class="res ' + (won(t)?"win":"loss") + '">' + rr(t.got_r) + ' &nbsp; ' + money(t.pnl) + '</span>';
}

function draw(){
  // A resize can land before there is anything to draw, which on a phone
  // is simply turning it sideways on a fresh install.
  if(!VIEW.length || !VIEW[cur]) return;
  const t = VIEW[cur], cv = document.getElementById("c");
  const bars = t.bars || [];
  const dpr = window.devicePixelRatio || 1;
  const W = cv.clientWidth, H = 410;
  cv.width = W*dpr; cv.height = H*dpr;
  const x = cv.getContext("2d"); x.scale(dpr,dpr);
  x.textBaseline = "middle";
  x.clearRect(0,0,W,H);
  if(!bars.length){
    x.fillStyle = css("--muted"); x.font = '14px ' + MONO;
    x.fillText("No minute bars stored for this trade.",20,H/2); return;
  }

  const L=14, R=88, T=20, B=30, w=W-L-R, h=H-T-B;
  const ei = t.entry_i==null?0:t.entry_i, xi = t.exit_i==null?bars.length-1:t.exit_i;

  // Vertical range covers the candles, the entry and the stop. A target far
  // outside that would squash every candle flat, so it is allowed to sit off
  // the chart and is labelled instead of being drawn to scale.
  let lo = Math.min.apply(null,bars.map(b=>b.l)), hi = Math.max.apply(null,bars.map(b=>b.h));
  const span0 = hi-lo;
  [t.entry, t.stop].forEach(v=>{ if(v!=null){ lo=Math.min(lo,v); hi=Math.max(hi,v); } });
  let tgtOff = false;
  if(t.target!=null){
    if(t.target > lo-span0*0.5 && t.target < hi+span0*0.5){
      lo=Math.min(lo,t.target); hi=Math.max(hi,t.target);
    } else tgtOff = true;
  }
  const pad=(hi-lo)*0.09||1; lo-=pad; hi+=pad;
  const Y = p => T + (hi-p)/(hi-lo)*h;
  const Yc = p => Math.max(T, Math.min(T+h, Y(p)));
  const X = i => L + (i+0.5)/bars.length*w;
  const bw = Math.max(2, Math.min(11, w/bars.length*0.6));

  // --- risk and reward bands, drawn first so candles read on top of them ----
  const band=(from,to,fill,edge)=>{
    const y0=Yc(from), y1=Yc(to);
    x.fillStyle=fill; x.fillRect(L, Math.min(y0,y1), w, Math.abs(y1-y0));
    if(edge!=="none"){
      x.save(); x.setLineDash([5,4]); x.strokeStyle=edge; x.lineWidth=1.25;
      const ye=Math.round(y1)+0.5;
      x.beginPath(); x.moveTo(L,ye); x.lineTo(L+w,ye); x.stroke(); x.restore();
    }
  };
  if(t.stop!=null) band(t.entry, t.stop, css("--loss-zone"), css("--loss-faded"));
  if(t.target!=null){
    const to = tgtOff ? (t.side==="Short" ? lo : hi) : t.target;
    band(t.entry, to, css("--win-zone"), tgtOff ? "none" : css("--win-faded"));
  }

  // --- axes -----------------------------------------------------------------
  x.strokeStyle=css("--line-soft"); x.lineWidth=1;
  x.fillStyle=css("--faint"); x.font='400 10.5px ' + MONO;
  for(let k=0;k<=4;k++){
    const p=lo+(hi-lo)*k/4, y=Math.round(Y(p))+0.5;
    x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke();
    x.fillText(px(p), L+w+9, y);
  }
  const every=Math.max(1,Math.ceil(bars.length/7));
  x.textAlign="center";
  for(let i=0;i<bars.length;i+=every) x.fillText(bars[i].t, X(i), T+h+14);
  x.textAlign="left";

  // --- candles, dimmed once you are out ------------------------------------
  bars.forEach((b,i)=>{
    const up=b.c>=b.o, cx=X(i);
    x.save();
    if(i>xi) x.globalAlpha=0.3;
    x.strokeStyle = x.fillStyle = up?css("--candle-up"):css("--candle-dn");
    x.lineWidth=1;
    x.beginPath(); x.moveTo(Math.round(cx)+0.5,Y(b.h)); x.lineTo(Math.round(cx)+0.5,Y(b.l)); x.stroke();
    const y0=Y(Math.max(b.o,b.c)), y1=Y(Math.min(b.o,b.c));
    x.fillRect(cx-bw/2, y0, bw, Math.max(1.2,y1-y0));
    x.restore();
  });

  // --- entry, and the trail as the staircase it really is ------------------
  x.save(); x.strokeStyle=css("--text"); x.lineWidth=1.5;
  x.shadowColor="rgba(232,240,248,.45)"; x.shadowBlur=8;
  const ye=Math.round(Y(t.entry))+0.5;
  x.beginPath(); x.moveTo(L,ye); x.lineTo(L+w,ye); x.stroke(); x.restore();

  const steps=(t.trail||[]).map(s=>({t:s.t, sl:s.sl, kind:s.kind, fav_r:s.fav_r,
                                     i:bars.findIndex(b=>b.t===s.t.slice(0,5))}))
                           .filter(s=>s.i>=0);
  if(steps.length>1){
    x.save(); x.strokeStyle=css("--accent"); x.lineWidth=2; x.lineJoin="round";
    x.shadowColor=css("--accent"); x.shadowBlur=10;
    x.beginPath();
    steps.forEach((s,k)=>{
      const x0=X(s.i), x1=k+1<steps.length?X(steps[k+1].i):X(xi), y=Math.round(Y(s.sl))+0.5;
      if(k) x.lineTo(x0,y); else x.moveTo(x0,y);
      x.lineTo(x1,y);
    });
    x.stroke(); x.restore();
  }

  // --- the exit divider, so "after" needs no explaining --------------------
  if(xi < bars.length-1){
    x.save(); x.setLineDash([3,4]); x.strokeStyle=css("--faint"); x.lineWidth=1;
    const xe=Math.round(X(xi)+bw/2+2)+0.5;
    x.beginPath(); x.moveTo(xe,T); x.lineTo(xe,T+h); x.stroke(); x.restore();
  }

  // --- price tags on the right axis, so nothing sits over the candles -----
  const tag=(p,bg)=>{
    const y=Y(p); if(y<T-2||y>T+h+2) return;
    x.font='700 10.5px ' + MONO;
    const txt=px(p), tw=x.measureText(txt).width;
    x.fillStyle=bg; x.fillRect(L+w+2, y-8.5, tw+13, 17);
    x.fillStyle=css("--ground"); x.fillText(txt, L+w+8, y+0.5);
  };
  if(t.target!=null && !tgtOff) tag(t.target, css("--win"));
  if(t.stop!=null) tag(t.stop, css("--loss"));
  tag(t.entry, css("--text"));

  // --- in and out, as plain marks; the numbers live in the strip above -----
  const mark=(i,p,fill)=>{
    x.save(); x.shadowColor=fill; x.shadowBlur=12;
    x.beginPath(); x.arc(X(i),Y(p),4.5,0,7);
    x.fillStyle=fill; x.fill(); x.restore();
    x.strokeStyle=css("--raised"); x.lineWidth=2; x.stroke();
  };
  mark(ei, t.entry, css("--text"));
  mark(xi, t.exit, t.got_r>=0?css("--win"):css("--loss"));
}

function details(){
  const t = VIEW[cur];
  const row=(k,v)=>'<tr><td>'+k+'</td><td>'+v+'</td></tr>';
  const val=(k,v,cls)=>'<div class="val"><span class="vl">'+k+'</span>' +
      '<span class="vv '+(cls||"")+'">'+v+'</span></div>';
  document.getElementById("values").innerHTML = [
    val("entry", px(t.entry)),
    val("stop", t.stop!=null ? px(t.stop)+"<small>"+t.risk_pts+" pts</small>" : "&mdash;", "loss"),
    val("target", t.target!=null ? px(t.target) +
        (t.planned_rr!=null?"<small>"+t.planned_rr.toFixed(2)+"R</small>":"") : "&mdash;", "win"),
    val("exit", px(t.exit)+"<small>"+t.exit_type.toLowerCase()+"</small>",
        t.got_r>=0?"win":"loss"),
    val("in", t.open_t.slice(11,16)),
    val("out", t.close_t.slice(11,16)+"<small>"+t.held_min+" min</small>"),
  ].join("");

  document.getElementById("facts").innerHTML = [
    row("result", '<span class="'+(won(t)?"win":"loss")+'">'+rr(t.got_r)+'</span>'),
    row("planned", t.planned_rr!=null?t.planned_rr.toFixed(2)+"R":"&mdash;"),
    row("best it offered", t.mfe_r!=null ? t.mfe_r.toFixed(2)+"R" +
        (t.kept_pct!=null?' <span class="dim">kept '+t.kept_pct+'%</span>':"") : "&mdash;"),
    row("worst it went", t.mae_r!=null?t.mae_r.toFixed(2)+"R":"&mdash;"),
    row("risk", t.risk_pts!=null?t.risk_pts+" pts":"&mdash;"),
    row("held", t.held_min+" min"),
  ].join("");

  const steps = t.trail||[];
  document.getElementById("trailbox").innerHTML = steps.length<2 ? "" :
    '<h3>Stop moves</h3><table>' + steps.map(s=>{
      const early = s.kind!=="initial" && s.fav_r!=null && s.fav_r<BE_AT_R && s.kind!=="wrong side";
      const k = s.kind==="wrong side" ? '<span class="kind bad">wrong side</span>'
              : early ? '<span class="kind early">early</span>'
              : s.kind==="initial" ? '<span class="kind">at entry</span>' : "";
      return '<tr><td>'+s.t+k+'</td><td>'+px(s.sl)+'</td>' +
             '<td class="dim">'+(s.fav_r!=null?"after "+s.fav_r.toFixed(2)+"R":"")+'</td></tr>';
    }).join("") + '</table>';

  document.getElementById("flags").innerHTML = (t.flags||[]).map(f=>
    '<span class="chip '+(GOOD.includes(f)?"good":(BAD.includes(f)?"bad":""))+'">' +
    (FLAG_TEXT[f]||f) + '</span>').join("");
  document.getElementById("note").textContent = t.note || "";
}

const START = __START__;

function drawEq(){
  const cv = document.getElementById("eq");
  const W = cv.clientWidth, H = 250, dpr = window.devicePixelRatio || 1;
  cv.width = W*dpr; cv.height = H*dpr;
  const x = cv.getContext("2d"); x.scale(dpr,dpr);
  x.textBaseline = "middle";
  x.clearRect(0,0,W,H);

  // Equity after each trade, starting from the account balance when the
  // journal opened. Without that export it starts at zero and reads as profit.
  const base = START == null ? 0 : START;
  const eq = [base];
  VIEW.forEach(t => eq.push(eq[eq.length-1] + t.pnl));

  let run = eq[0];
  const peak = eq.map(v => (run = Math.max(run, v)));

  const L=14, R=92, T=22, B=26, w=W-L-R, h=H-T-B;
  let lo = Math.min.apply(null, eq), hi = Math.max.apply(null, eq);
  const pad = (hi-lo)*0.22 || Math.max(1, Math.abs(hi)*0.002);
  lo -= pad; hi += pad;
  const Y = v => T + (hi-v)/(hi-lo)*h;
  const X = i => L + (eq.length<2 ? w/2 : i/(eq.length-1)*w);

  // grid and the dollar axis
  x.strokeStyle=css("--line-soft"); x.lineWidth=1;
  x.fillStyle=css("--faint"); x.font='400 10.5px ' + MONO;
  for(let k=0;k<=3;k++){
    const v=lo+(hi-lo)*k/3, y=Math.round(Y(v))+0.5;
    x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke();
    x.fillText("$" + Math.round(v).toLocaleString(), L+w+9, y);
  }

  // area under the curve
  const g = x.createLinearGradient(0,T,0,T+h);
  g.addColorStop(0,"rgba(53,224,240,.20)");
  g.addColorStop(1,"rgba(53,224,240,0)");
  x.beginPath();
  eq.forEach((v,i)=> i ? x.lineTo(X(i),Y(v)) : x.moveTo(X(i),Y(v)));
  x.lineTo(X(eq.length-1), T+h); x.lineTo(X(0), T+h); x.closePath();
  x.fillStyle=g; x.fill();

  // the curve
  x.save(); x.strokeStyle=css("--accent"); x.lineWidth=2.5;
  x.lineJoin="round"; x.lineCap="round";
  x.shadowColor=css("--accent"); x.shadowBlur=14;
  x.beginPath();
  eq.forEach((v,i)=> i ? x.lineTo(X(i),Y(v)) : x.moveTo(X(i),Y(v)));
  x.stroke(); x.restore();

  // one dot per trade, in the colour of that trade
  eq.forEach((v,i)=>{
    if(!i) return;
    const t = VIEW[i-1];
    x.beginPath(); x.arc(X(i),Y(v),4,0,7);
    x.fillStyle = t.pnl>=0 ? css("--win") : css("--loss"); x.fill();
    x.strokeStyle=css("--raised"); x.lineWidth=2; x.stroke();
  });

  // trade numbers along the bottom
  x.fillStyle=css("--faint"); x.font='400 10.5px ' + MONO; x.textAlign="center";
  x.fillText("start", X(0), T+h+13);
  for(let i=1;i<eq.length;i++) x.fillText(i, X(i), T+h+13);
  x.textAlign="left";

  const m = v => "$" + Math.round(v).toLocaleString();
  document.getElementById("eqStart").textContent = m(base);
  const now = eq[eq.length-1], top = Math.max.apply(null, peak);
  const nowEl = document.getElementById("eqNow");
  nowEl.textContent = m(now);
  nowEl.className = now >= base ? "win" : "loss";
  document.getElementById("eqPeak").textContent = m(top);
}

function playCut(btn){
  const v = document.getElementById("player");
  document.querySelectorAll(".cut").forEach(b=>b.setAttribute("aria-pressed", b===btn));
  v.src = btn.dataset.src;
  v.classList.add("on");
  document.getElementById("playing").textContent =
    "Now playing: " + btn.querySelector(".cn").textContent;
  v.play().catch(()=>{
    document.getElementById("playing").textContent =
      "This player only reaches the files when the page is opened from your PC.";
  });
}

function pick(i){
  cur = i;
  tabs();
  const card = document.querySelector(".card.hud");
  if(!VIEW.length){
    document.getElementById("chead").innerHTML =
      '<span class="who">No trades in this view</span>';
    document.getElementById("values").innerHTML = "";
    document.getElementById("facts").innerHTML = "";
    document.getElementById("trailbox").innerHTML = "";
    document.getElementById("flags").innerHTML = "";
    document.getElementById("note").textContent = "";
    const cv = document.getElementById("c");
    cv.getContext("2d").clearRect(0, 0, cv.width, cv.height);
    return;
  }
  head(); details(); draw();
}
window.addEventListener("resize", ()=>{ draw(); drawEq(); });
document.fonts.ready.then(()=>{ pick(cur); drawEq(); });
const firstSrc = document.querySelector('.src[data-src="live"]')
  || document.querySelector(".src");
pickSource(firstSrc ? firstSrc.dataset.src : "live");

/* ---------------------------------------------------------------- import */
/* Six files land at once. Three are read, three are cross-checks, and the
   rest of the pipeline runs on the server before the page comes back. */
const drop = document.getElementById("drop");
const pickEl = document.getElementById("pick");
const fileList = document.getElementById("dropfiles");
const bar = document.getElementById("dropbar");
const msg = document.getElementById("dropmsg");

const KINDS = [
  [/order-history/i, "every fill, so the trades themselves"],
  [/activity-log/i, "stop moves, so R"],
  [/balance-history/i, "the opening balance"],
  [/trade-history/i, "cross-check against the broker"],
  [/orders-all|^orders/i, "cross-check"],
  [/positions/i, "cross-check"],
];

function say(text, bad){
  msg.textContent = text;
  msg.classList.toggle("bad", !!bad);
  msg.hidden = !text;
}

function preview(files){
  fileList.innerHTML = "";
  for (const f of files){
    const hit = KINDS.find(k => k[0].test(f.name));
    const li = document.createElement("li");
    li.className = hit ? "used" : "skip";
    li.innerHTML = "<b>" + f.name.replace(/^paper-trading-/, "")
      .replace(/-\d{4}-\d\d-\d\dT[\d_.]+Z?\.csv$/i, "") + "</b>"
      + (hit ? hit[1] : "not one the diary reads, ignored");
    fileList.appendChild(li);
  }
}

async function send(files){
  const csv = [...files].filter(f => /\.csv$/i.test(f.name));
  preview(files);
  if (!csv.length){ say("Those are not CSV files. Export from TradingView first.", true); return; }
  if (location.protocol === "file:"){
    say("This page is open straight from disk, so it cannot import. "
      + "Start Traders Diary and open it from there.", true);
    return;
  }
  const body = new FormData();
  for (const f of csv) body.append("file", f, f.name);
  drop.classList.add("busy"); bar.hidden = false;
  say("Reading " + csv.length + " file" + (csv.length > 1 ? "s" : "") + "...");
  try {
    const res = await fetch("/api/import", {method: "POST", body});
    const out = await res.json();
    bar.hidden = true; drop.classList.remove("busy");
    if (!res.ok || out.error){ say(out.error || "Import failed.", true); return; }
    say(out.message);
    if (out.added || out.rebuilt) setTimeout(()=>location.reload(), 1400);
  } catch (e) {
    bar.hidden = true; drop.classList.remove("busy");
    say("Could not reach Traders Diary. Is the window still open?", true);
  }
}

drop.addEventListener("click", ()=> pickEl.click());
drop.addEventListener("keydown", e => {
  if (e.key === "Enter" || e.key === " "){ e.preventDefault(); pickEl.click(); }
});
pickEl.addEventListener("change", ()=> pickEl.files.length && send(pickEl.files));
["dragenter","dragover"].forEach(n => drop.addEventListener(n, e => {
  e.preventDefault(); drop.classList.add("over");
}));
["dragleave","drop"].forEach(n => drop.addEventListener(n, e => {
  e.preventDefault(); drop.classList.remove("over");
}));
drop.addEventListener("drop", e => {
  if (e.dataTransfer && e.dataTransfer.files.length) send(e.dataTransfer.files);
});
/* Dropping anywhere else on the page must not make the browser navigate to
   the file, which looks exactly like the app crashing. */
window.addEventListener("dragover", e => e.preventDefault());
window.addEventListener("drop", e => e.preventDefault());
</script>
"""


def main():
    if not os.path.exists(STORE):
        print("No trades stored. Run `python tradejournal.py` first.")
        return
    trades = json.load(io.open(STORE, encoding="utf-8"))
    if not trades:
        print("No trades stored yet.")
        return
    html = build(trades, summarise(trades)).replace("__FLAGTEXT__", json.dumps(FLAG_TEXT))
    io.open(OUT, "w", encoding="utf-8").write(html)
    print(f"{len(trades)} trades -> {OUT}")


if __name__ == "__main__":
    main()
