"""Build the bar replay page: step through history and trade it blind.

WHY THIS IS ANCHORED TO A MOMENT, NOT A SESSION
-----------------------------------------------
The first version of this built each day separately, and it could never show an
hourly chart: one trading day is about seven hourly bars. But the high timeframe
levels a setup is drawn to were formed days or weeks earlier, and TJR switches
up to the hourly mid-replay to look at exactly those before dropping back to the
five for an entry.

So the playhead is a TIMESTAMP in one continuous history, not an index into a
day. Switching timeframe keeps the moment and re-reads the same instant at a
different resolution. Bars are served in slices by the local app rather than
embedded, which is what makes 172,000 five-minute bars practical at all.

WHAT YOU CAN SEE
----------------
It opens in BROWSE, showing history up to the end of the data, because you
cannot choose where a trade is worth taking without reading the shape first.
Click a bar and everything after it is cut away. From that moment you are in
REPLAY and cannot see past the playhead, on any timeframe.

Stops and targets fill on the same rules the backtester uses:

  both levels touched inside one bar  ->  counted as the loss
  price gapped through the stop       ->  filled at the open, not the stop

Inside a single bar there is no way to know which side came first, and assuming
the good one turns a losing method into a winning one on paper.
"""
import functools
import io
import os

print = functools.partial(print, flush=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "journal_data", "replay.html")


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(TEMPLATE)
    print(f"replay -> {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB, bars served live)")


TEMPLATE = r"""<title>Bar Replay</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800;900&family=Chakra+Petch:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap">
<style>
:root{
  --ground:#05070C; --raised:#0A0F17; --lift:#111A26;
  --line:#1B2838; --line-soft:#121A26;
  --text:#E8F0F8; --muted:#7E90A8; --faint:#4A5A70;
  --accent:#35E0F0;
  --win:#2BE08A; --loss:#FF5C6E;
  --win-faded:#177A4C; --loss-faded:#8E2F3A;
  --win-zone:rgba(43,224,138,.085); --loss-zone:rgba(255,92,110,.085);
  --candle-up:#22B877; --candle-dn:#C4485A;
  --asia:#4DB98A; --london:#35E0F0; --ny:#C9D4E4; --day:#B08CE0;
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
.wrap{max-width:1290px; margin:0 auto; padding:26px 18px 70px}
.hud{position:relative}
.hud::before,.hud::after{content:""; position:absolute; width:17px; height:17px; pointer-events:none}
.hud::before{top:-1px; left:-1px; border-top:2px solid var(--accent); border-left:2px solid var(--accent)}
.hud::after{bottom:-1px; right:-1px; border-bottom:2px solid var(--accent); border-right:2px solid var(--accent)}

h1{
  font-family:"Orbitron",sans-serif; font-weight:900; font-size:30px;
  margin:0 0 6px; letter-spacing:.012em; text-transform:uppercase;
  background:linear-gradient(178deg,#FFFFFF 8%,#9DE9F6 92%);
  -webkit-background-clip:text; background-clip:text; color:transparent;
  filter:drop-shadow(0 0 22px rgba(53,224,240,.34));
}
.sub{color:var(--muted); font-size:11px; margin:0 0 18px; text-transform:uppercase;
  letter-spacing:.18em; font-weight:500}
h3{font-family:"Orbitron",sans-serif; font-size:9.5px; text-transform:uppercase;
  letter-spacing:.15em; color:var(--accent); margin:0 0 12px; font-weight:700}

label{font-size:9px; text-transform:uppercase; letter-spacing:.17em; color:var(--faint);
  font-weight:600; display:block; margin-bottom:5px}
select,input{
  background:var(--lift); border:1px solid var(--line); color:var(--text);
  font-family:"JetBrains Mono",monospace; font-size:14px; padding:8px 10px; width:100%;
}
select:focus,input:focus{outline:2px solid var(--accent); outline-offset:1px}

.setup{display:flex; flex-wrap:wrap; gap:12px; align-items:flex-end;
  background:var(--raised); border:1px solid var(--line); padding:14px 16px;
  margin-bottom:16px}
button{
  background:var(--lift); border:1px solid var(--line); color:var(--text);
  font-family:"Chakra Petch",sans-serif; font-weight:600; font-size:11.5px;
  text-transform:uppercase; letter-spacing:.11em; padding:9px 14px; cursor:pointer;
  transition:border-color .13s, background .13s, box-shadow .13s, color .13s;
}
button:hover:not(:disabled){border-color:var(--accent); background:var(--raised)}
button:disabled{opacity:.32; cursor:not-allowed}
button:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
button.on{border-color:var(--accent); background:var(--lift);
  box-shadow:0 0 20px rgba(53,224,240,.22)}
button.buy{border-color:var(--win-faded); color:var(--win)}
button.buy:hover:not(:disabled){border-color:var(--win); background:rgba(43,224,138,.08)}
button.sell{border-color:var(--loss-faded); color:var(--loss)}
button.sell:hover:not(:disabled){border-color:var(--loss); background:rgba(255,92,110,.08)}
.tfrow{display:flex; gap:4px}
.tfrow button{padding:9px 11px; flex:1; letter-spacing:.06em}

.chartcard{background:var(--raised); border:1px solid var(--line)}
.bar{display:flex; flex-wrap:wrap; gap:15px; align-items:baseline; padding:11px 16px;
  border-bottom:1px solid var(--line-soft)}
.bar .k{font-size:9px; text-transform:uppercase; letter-spacing:.15em; color:var(--faint);
  font-weight:600}
.bar .v{font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
  font-size:15px; font-weight:700; margin-left:6px}
.mode{font-family:"Orbitron",sans-serif; font-size:9px; letter-spacing:.16em;
  padding:3px 9px; border:1px solid var(--accent); color:var(--accent); font-weight:700}
canvas{display:block; width:100%; height:490px; cursor:crosshair}
canvas.grabbing{cursor:grabbing}
.controls{display:flex; flex-wrap:wrap; gap:7px; align-items:center; padding:11px 16px;
  border-top:1px solid var(--line-soft)}
.controls .spacer{flex:1}
.hint{font-size:10px; color:var(--faint); text-transform:uppercase; letter-spacing:.1em}

.deck{display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.3fr); gap:16px;
  margin-top:16px}
@media(max-width:900px){ .deck{grid-template-columns:1fr} }
.panel{background:var(--raised); border:1px solid var(--line); padding:15px 17px}
.ticket{display:grid; grid-template-columns:1fr 1fr; gap:11px; margin-bottom:12px}
.rrbox{
  display:flex; flex-wrap:wrap; gap:16px; align-items:baseline;
  background:var(--lift); border:1px solid var(--line); padding:10px 13px;
  margin-bottom:12px;
}
.rrbox .k{font-size:8.5px; text-transform:uppercase; letter-spacing:.15em;
  color:var(--faint); font-weight:600}
.rrbox .v{font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
  font-size:15px; font-weight:700; margin-left:6px}
.rrbox.bad{border-color:var(--loss-faded)}
.rrwarn{
  flex-basis:100%; font-size:11px; color:var(--loss); text-transform:uppercase;
  letter-spacing:.1em; font-weight:600; margin-top:2px;
}
.sides{display:flex; gap:9px}
.sides button{flex:1}
.pos{font-family:"JetBrains Mono",monospace; font-size:13px; width:100%}
.pos td{padding:4px 0}
.pos td:first-child{color:var(--muted); font-family:"Chakra Petch",sans-serif}
.pos td:last-child{text-align:right; font-weight:700}
.flat{color:var(--faint); font-size:13px; margin:0}
table.log{width:100%; border-collapse:collapse; font-size:11.5px}
table.log th{font-size:8.5px; text-transform:uppercase; letter-spacing:.13em;
  color:var(--faint); text-align:left; font-weight:600; padding:0 6px 7px 0;
  border-bottom:1px solid var(--line)}
table.log td{padding:5px 6px 5px 0; border-bottom:1px solid var(--line-soft);
  font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums}
table.log td:last-child, table.log th:last-child{text-align:right; padding-right:0}
.tot{display:flex; flex-wrap:wrap; gap:18px; margin-top:12px; padding-top:11px;
  border-top:1px solid var(--line)}
.tot span{font-size:8.5px; text-transform:uppercase; letter-spacing:.15em;
  color:var(--faint); font-weight:600}
.tot b{font-family:"JetBrains Mono",monospace; font-size:14px; margin-left:6px}
.note{font-size:11.5px; color:var(--muted); margin:12px 0 0; line-height:1.6}
.win{color:var(--win)} .loss{color:var(--loss)}
</style>

<div class="wrap">
<h1>Bar Replay</h1>
<p class="sub">Read the higher timeframe, cut the chart, then trade it blind</p>

<div class="setup hud">
  <div style="flex:0 1 110px">
    <label for="sym">Symbol</label>
    <select id="sym" onchange="reload(true)">
      <option>NQ</option><option>ES</option>
    </select>
  </div>
  <div style="flex:2 1 210px">
    <label>Timeframe</label>
    <div class="tfrow" id="tfrow"></div>
  </div>
  <div style="flex:0 1 165px">
    <label for="jump">Jump to date</label>
    <input id="jump" type="date">
  </div>
  <div style="flex:0 0 auto">
    <label>&nbsp;</label>
    <button onclick="jumpTo()">Go</button>
  </div>
  <div style="flex:0 0 auto">
    <label>&nbsp;</label>
    <button onclick="toBrowse()">Browse</button>
  </div>
</div>

<div class="chartcard hud">
  <div class="bar">
    <span class="mode" id="mMode">BROWSE</span>
    <span><span class="k">At</span><span class="v" id="bTime">&mdash;</span></span>
    <span><span class="k">Price</span><span class="v" id="bPrice">&mdash;</span></span>
    <span><span class="k">TF</span><span class="v" id="bTf">&mdash;</span></span>
    <span style="margin-left:auto"><span class="k">Booked</span><span class="v" id="bPnl">&mdash;</span></span>
  </div>
  <canvas id="c"></canvas>
  <div class="controls">
    <button id="btnPlay" onclick="togglePlay()" disabled>Play</button>
    <button id="btnStep" onclick="step(1)" disabled>Step &rarr;</button>
    <button id="btnJump" onclick="step(10)" disabled>+10</button>
    <select id="speed" style="width:auto" onchange="if(playing){stopPlay();startPlay();}">
      <option value="700">Slow</option>
      <option value="320" selected>Normal</option>
      <option value="120">Fast</option>
      <option value="40">Very fast</option>
    </select>
    <button id="btnLevels" class="on" onclick="toggleLevels()">Session levels</button>
    <button onclick="zoom(-1)">Zoom in</button>
    <button onclick="zoom(1)">Zoom out</button>
    <span class="spacer"></span>
    <span class="hint" id="hint">Click a bar to cut the chart there</span>
  </div>
</div>

<div class="deck">
  <div class="panel hud">
    <h3>Order ticket</h3>
    <div class="ticket" style="grid-template-columns:1fr 1fr 1fr">
      <div>
        <label for="qty">Contracts</label>
        <input id="qty" type="number" step="1" min="1" value="1" oninput="ticket()">
      </div>
      <div>
        <label for="slPts">Stop, points</label>
        <input id="slPts" type="number" step="0.25" value="20" oninput="fromPts()">
      </div>
      <div>
        <label for="tpR">Target, R</label>
        <input id="tpR" type="number" step="0.1" value="2" oninput="fromPts()">
      </div>
    </div>
    <div class="ticket">
      <div>
        <label for="slPx">Stop price</label>
        <input id="slPx" type="number" step="0.25" oninput="fromPx()">
      </div>
      <div>
        <label for="tpPx">Target price</label>
        <input id="tpPx" type="number" step="0.25" oninput="fromPx()">
      </div>
    </div>
    <div class="rrbox" id="rrBox"></div>
    <div class="sides">
      <button class="buy" id="btnBuy" onclick="place('long')" disabled>Buy</button>
      <button class="sell" id="btnSell" onclick="place('short')" disabled>Sell</button>
    </div>
    <p class="note" id="sideNote" style="margin-top:9px">
      Prices are shown for a long. Sell flips them.
    </p>
    <div id="posBox" style="margin-top:14px"></div>
  </div>

  <div class="panel hud">
    <h3>Trades</h3>
    <div id="logBox"><p class="flat">No trades yet.</p></div>
    <div class="tot" id="totBox" style="display:none">
      <span>Trades<b id="tCount">0</b></span>
      <span>Won<b id="tWon">0</b></span>
      <span>R<b id="tR">0.00</b></span>
      <span>P&amp;L<b id="tPnl">$0</b></span>
    </div>
    <p class="note">
      Both levels touched inside one bar is scored as the loss. Inside a single
      bar there is no way to know which came first, and assuming the good one
      makes a losing method look profitable.
    </p>
    <div style="display:flex; gap:9px; margin-top:12px">
      <button onclick="exportTrades()" id="btnExport" disabled>Save for the diary</button>
      <button onclick="clearTrades()">Clear all</button>
    </div>
  </div>
</div>
</div>

<script>
const KEY = "replayTrades";
const POINT = {NQ:20, ES:50};
const BEFORE = 420, AFTER = 260;      // bars fetched behind and ahead of the cut

let TFS = [];              // what the server actually has for this symbol
let B = null;              // the loaded slice {t,o,h,l,c}
let ci = 0;                // playhead index inside B
let cursor = null;         // the playhead as a timestamp, the thing that persists
let tf = "5m";
let mode = "browse";
let span = 130, right = 0;
let pos = null, trades = [], playing = false, timer = null;
let hover = null, drag = null, busy = false;
let vscale = null;        // the last render's price scale, for pointer work
let holding = null;       // "stop" or "target" while a level is being dragged
// How stretched the price axis is. Above one squeezes the range and the candles
// stand taller; below one opens it out and they go flat. Dragging the price
// axis changes it, double clicking the axis puts it back.
let pzoom = 1;
let axisDrag = null;
// Session highs and lows AS OF THE PLAYHEAD. Fetched at the cut and whenever it
// crosses into a new session, never for "now", because a level that had not
// formed yet must not be on the chart you are practising against.
let levels = [], showLevels = true, levelsAt = null;

const px = v => v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const money = v => (v<0?"-":"+") + "$" + Math.abs(v).toLocaleString(undefined,{maximumFractionDigits:0});
const rr = v => (v>=0?"+":"") + v.toFixed(2) + "R";
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const sym = () => document.getElementById("sym").value;
const bar = k => ({t:B.t[k], o:B.o[k], h:B.h[k], l:B.l[k], c:B.c[k]});
const hhmm = s => (s || "").slice(11);

try { trades = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch(e) { trades = []; }

// ------------------------------------------------------------- fetching ----
async function loadTfs(){
  try{
    TFS = await (await fetch("/api/tfs?sym=" + sym())).json();
  }catch(e){ TFS = []; }
  if(!TFS.some(x => x.tf === tf) && TFS.length) tf = TFS.find(x=>x.tf==="5m") ? "5m" : TFS[0].tf;
  drawTfs();
}

function drawTfs(){
  document.getElementById("tfrow").innerHTML = TFS.map(x =>
    `<button class="${x.tf===tf?"on":""}" onclick="setTf('${x.tf}')" ` +
    `title="${x.n.toLocaleString()} bars, ${x.first} to ${x.last}">${x.tf}</button>`
  ).join("") || '<span class="hint">no data</span>';
}

// The moment is what carries across a timeframe change, never the bar number.
// The levels a trader would already know at the playhead. Refetched only when
// the playhead moves into a different hour, since a session boundary can never
// fall inside one and this saves a request per bar while stepping.
async function fetchLevels(){
  if(!cursor) return;
  const hour = cursor.slice(0, 13);
  if(hour === levelsAt) return;
  levelsAt = hour;
  try{
    const d = await (await fetch("/api/levels?sym=" + sym() +
                                 "&at=" + encodeURIComponent(cursor))).json();
    levels = (d && d.levels) ? d.levels : [];
  }catch(e){ levels = []; }
}

function toggleLevels(){
  showLevels = !showLevels;
  const b = document.getElementById("btnLevels");
  if(b) b.classList.toggle("on", showLevels);
  draw();
}

async function fetchAround(at){
  busy = true;
  const q = "/api/bars?sym=" + sym() + "&tf=" + tf +
            "&n=" + BEFORE + "&after=" + (mode === "browse" ? 0 : AFTER) +
            (at ? "&end=" + encodeURIComponent(at) : "");
  try{
    const d = await (await fetch(q)).json();
    if(d.error || !d.t || !d.t.length){ busy=false; return false; }
    B = d;
    ci = (d.cut == null) ? d.t.length - 1 : d.cut;
    cursor = B.t[ci];
    right = mode === "browse" ? B.t.length - 1 : ci;
    span = Math.min(span, right + 1);
  }catch(e){ busy=false; return false; }
  busy = false;
  await fetchLevels();
  return true;
}

async function reload(resetSym){
  stopPlay();
  if(resetSym){ await loadTfs(); mode = "browse"; pos = null; cursor = null; }
  await fetchAround(cursor);
  render();
}

async function setTf(next){
  if(next === tf) return;
  tf = next;
  drawTfs();
  await fetchAround(cursor);          // same instant, different resolution
  render();
}

async function jumpTo(){
  const v = document.getElementById("jump").value;
  if(!v) return;
  mode = "browse"; pos = null; stopPlay();
  await fetchAround(v + " 23:59");
  render();
}

// ------------------------------------------------------------- the snip ----
async function snipAt(k){
  if(!B) return;
  cursor = B.t[Math.max(0, Math.min(B.t.length-1, k))];
  mode = "replay"; pos = null;
  span = Math.min(130, span);
  await fetchAround(cursor);
  render();
}

async function toBrowse(){
  stopPlay();
  mode = "browse"; pos = null;
  await fetchAround(cursor);
  render();
}

// ------------------------------------------------------------ the replay ---
function step(n){
  if(!B || mode === "browse") return;
  for(let k=0;k<n;k++){
    if(ci >= B.t.length - 1) break;
    ci++;
    cursor = B.t[ci];
    if(pos) checkFills(bar(ci));
  }
  right = ci;
  fetchLevels().then(()=>{ if(showLevels) draw(); });
  // top the buffer up before it runs out, so stepping never stalls
  if(ci > B.t.length - 30 && !busy) fetchAround(cursor).then(render);
  render();
}

// Fills are resolved exactly the way the backtester resolves them, so a session
// traded here can be compared with a backtest without adjusting for optimism.
function checkFills(b){
  const long = pos.side === "long";
  const hitStop = long ? b.l <= pos.stop : b.h >= pos.stop;
  const hitTgt  = long ? b.h >= pos.target : b.l <= pos.target;
  if(hitStop && hitTgt){ close(fillPrice(b, pos.stop, long), b.t, "stop"); return; }
  if(hitStop){ close(fillPrice(b, pos.stop, long), b.t, "stop"); return; }
  if(hitTgt){ close(fillPrice(b, pos.target, !long), b.t, "target"); return; }
}

// a bar that opens beyond the level fills at the open, not at the level
function fillPrice(b, level, worseIsBelow){
  if(worseIsBelow) return b.o < level ? b.o : level;
  return b.o > level ? b.o : level;
}

// ---------------------------------------------------------- the ticket ----
// Stop and target can be typed either way round: as a distance in points, or as
// the price itself. The two stay in step. What matters more than either is the
// line underneath them, which says what you are risking against what you stand
// to make, in money, before you commit. That readout is the whole reason a
// two-to-one against you is obvious rather than something you discover later.
const val = id => parseFloat(document.getElementById(id).value);
const refPrice = () => (B && B.t.length ? bar(ci).c : null);
const pts = () => Math.abs(val("slPts") || 0);
const rmul = () => Math.abs(val("tpR") || 0);
const qty = () => Math.max(1, parseInt(document.getElementById("qty").value, 10) || 1);
const pointValue = () => POINT[(B && B.sym) || sym()] || 1;

function fromPts(){
  const e = refPrice();
  if(e != null){
    document.getElementById("slPx").value = (e - pts()).toFixed(2);
    document.getElementById("tpPx").value = (e + pts() * rmul()).toFixed(2);
  }
  ticket();
}

function fromPx(){
  const e = refPrice();
  if(e != null){
    const sl = val("slPx"), tp = val("tpPx");
    if(isFinite(sl) && Math.abs(e - sl) > 0.0001)
      document.getElementById("slPts").value = Math.abs(e - sl).toFixed(2);
    const p = pts();
    if(isFinite(tp) && p)
      document.getElementById("tpR").value = (Math.abs(tp - e) / p).toFixed(2);
  }
  ticket();
}

function ticket(){
  const e = refPrice(), box = document.getElementById("rrBox");
  const p = pts(), r = rmul(), q = qty(), pv = pointValue();
  if(e == null || !p){ box.innerHTML = ""; box.className = "rrbox"; draw(); return; }
  const risk = p * pv * q, reward = p * r * pv * q;
  const bad = r < 1;
  box.className = "rrbox" + (bad ? " bad" : "");
  box.innerHTML =
    '<span><span class="k">Risking</span><span class="v loss">' + money(-risk) + '</span></span>' +
    '<span><span class="k">To make</span><span class="v win">' + money(reward) + '</span></span>' +
    '<span><span class="k">R:R</span><span class="v">' + r.toFixed(2) + '</span></span>' +
    (bad ? '<span class="rrwarn">Risking more than you stand to make</span>' : "");
  draw();
}

function place(side){
  if(!B || pos || mode === "browse") return;
  const b = bar(ci);
  const slPts = pts(), rMult = rmul();
  if(!slPts || !rMult) return;
  const entry = b.c;
  pos = {side, entry, t: b.t, i: ci, risk: slPts, planned: rMult, qty: qty(),
         stop:   side==="long" ? entry - slPts : entry + slPts,
         target: side==="long" ? entry + slPts*rMult : entry - slPts*rMult};
  render();
}

function closeNow(){
  if(!pos || !B) return;
  const b = bar(ci);
  close(b.c, b.t, "manual");
  render();
}

function close(price, t, why){
  const long = pos.side === "long";
  const pts = long ? price - pos.entry : pos.entry - price;
  const s = B.sym || sym();
  const q = pos.qty || 1;
  trades.push({
    source: "replay", symbol: s, tf: B.tf || tf, day: (pos.t || t).slice(0,10),
    side: long ? "Long" : "Short", qty: q,
    entry: pos.entry, exit: +price.toFixed(2),
    stop: +pos.stop.toFixed(2), target: +pos.target.toFixed(2),
    open_t: hhmm(pos.t), close_t: hhmm(t), bars: ci - pos.i,
    risk_pts: pos.risk, planned_rr: pos.planned,
    got_r: +(pts / pos.risk).toFixed(2),
    got_pts: +pts.toFixed(2),
    pnl: +(pts * (POINT[s] || 1) * q).toFixed(2),
    exit_type: why,
  });
  pos = null;
  save();
}

function save(){ try{ localStorage.setItem(KEY, JSON.stringify(trades)); }catch(e){} }

function clearTrades(){
  if(!trades.length || !confirm("Delete every replay trade on record?")) return;
  trades = []; save(); render();
}

function exportTrades(){
  const blob = new Blob([JSON.stringify(trades, null, 1)], {type:"application/json"});
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "replay_trades.json";
  a.click();
  setTimeout(()=>URL.revokeObjectURL(a.href), 2000);
}

// ------------------------------------------------------------- playback ----
function startPlay(){
  if(!B || mode === "browse") return;
  playing = true;
  document.getElementById("btnPlay").textContent = "Pause";
  timer = setInterval(()=>step(1), parseInt(document.getElementById("speed").value,10));
}
function stopPlay(){
  playing = false;
  const b = document.getElementById("btnPlay");
  if(b) b.textContent = "Play";
  if(timer) clearInterval(timer);
  timer = null;
}
function togglePlay(){ playing ? stopPlay() : startPlay(); }

function zoom(dir){
  if(!B) return;
  span = Math.max(25, Math.min(right + 1, Math.round(span * (dir > 0 ? 1.35 : 0.74))));
  render();
}

// ---------------------------------------------------------------- render ---
function render(){ draw(); panels(); }
function geom(W, H){ const L=14,R=92,T=18,B2=30; return {L,R,T,B:B2,w:W-L-R,h:H-T-B2}; }

function draw(){
  const cv = document.getElementById("c");
  const W = cv.clientWidth, H = 490, dpr = window.devicePixelRatio || 1;
  cv.width = W*dpr; cv.height = H*dpr;
  const x = cv.getContext("2d"); x.scale(dpr,dpr);
  x.textBaseline = "middle";
  x.clearRect(0,0,W,H);
  if(!B || !B.t.length){
    x.fillStyle = css("--faint"); x.font = '14px "Chakra Petch"';
    x.fillText("Loading bars...", 22, H/2);
    return;
  }

  const g = geom(W,H), {L,T,w,h} = g;
  const last = mode === "browse" ? B.t.length - 1 : ci;
  right = Math.min(right, last);
  const lo0 = Math.max(0, right - span + 1);
  const shown = [];
  for(let k=lo0;k<=right;k++) shown.push(bar(k));
  if(!shown.length) return;

  let lo = Math.min.apply(null, shown.map(b=>b.l));
  let hi = Math.max.apply(null, shown.map(b=>b.h));
  if(pos) [pos.entry,pos.stop,pos.target].forEach(v=>{ lo=Math.min(lo,v); hi=Math.max(hi,v); });
  if(showLevels) levels.forEach(L2=>{ lo=Math.min(lo,L2.price); hi=Math.max(hi,L2.price); });
  const pad=(hi-lo)*0.08||1; lo-=pad; hi+=pad;
  if(pzoom !== 1){
    const mid = (lo + hi) / 2, half = (hi - lo) / 2 / pzoom;
    lo = mid - half; hi = mid + half;
  }

  const Y = p => T + (hi-p)/(hi-lo)*h;
  const Yc = p => Math.max(T, Math.min(T+h, Y(p)));
  const X = k => L + (k - lo0 + 0.5)/span*w;
  const bw = Math.max(1.2, Math.min(13, w/span*0.62));
  // kept so the pointer can turn a y position back into a price, which is what
  // makes the stop and target draggable
  vscale = {lo, hi, T, h, L, w};

  if(pos){
    const band=(a,b2,f)=>{ const y0=Yc(a),y1=Yc(b2);
      x.fillStyle=f; x.fillRect(L, Math.min(y0,y1), w, Math.abs(y1-y0)); };
    band(pos.entry, pos.stop, css("--loss-zone"));
    band(pos.entry, pos.target, css("--win-zone"));
  }

  x.strokeStyle=css("--line-soft"); x.lineWidth=1;
  x.fillStyle=css("--faint"); x.font='400 10.5px "JetBrains Mono"';
  for(let k=0;k<=4;k++){
    const p=lo+(hi-lo)*k/4, y=Math.round(Y(p))+0.5;
    x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke();
    x.fillText(px(p), L+w+9, y);
  }
  // date on the axis when the window spans more than a day, time when it does not
  const wide = shown[0].t.slice(0,10) !== shown[shown.length-1].t.slice(0,10);
  const every=Math.max(1,Math.ceil(shown.length/9));
  x.textAlign="center";
  shown.forEach((b,k)=>{
    if(k%every) return;
    x.fillText(wide ? b.t.slice(5,10) : hhmm(b.t), X(lo0+k), T+h+14);
  });
  x.textAlign="left";

  shown.forEach((b,k)=>{
    const up=b.c>=b.o, cx=X(lo0+k);
    x.strokeStyle = x.fillStyle = up?css("--candle-up"):css("--candle-dn");
    x.lineWidth=1;
    x.beginPath(); x.moveTo(Math.round(cx)+0.5,Y(b.h)); x.lineTo(Math.round(cx)+0.5,Y(b.l)); x.stroke();
    const y0=Y(Math.max(b.o,b.c)), y1=Y(Math.min(b.o,b.c));
    x.fillRect(cx-bw/2, y0, bw, Math.max(1.2,y1-y0));
  });

  // Session highs and lows as they stood at the playhead, drawn under the
  // position lines so a level never hides the trade you are managing.
  if(showLevels && levels.length){
    x.font='600 10px "Chakra Petch"';
    levels.forEach(L2=>{
      if(L2.price < lo || L2.price > hi) return;
      const col = css("--" + L2.family) || css("--muted");
      const y = Math.round(Y(L2.price))+0.5;
      x.save(); x.setLineDash([6,5]); x.strokeStyle=col; x.globalAlpha=.8; x.lineWidth=1.4;
      x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke(); x.restore();
      const tw = x.measureText(L2.label).width;
      x.save(); x.globalAlpha=.9; x.fillStyle=css("--raised");
      x.fillRect(L+6, y-14, tw+9, 13); x.restore();
      x.fillStyle=col; x.fillText(L2.label, L+10, y-7.5);
    });
  }

  const tail = shown[shown.length-1];
  if(!pos && tail && mode === "replay"){
    const slPts = Math.abs(parseFloat(document.getElementById("slPts").value)||0);
    if(slPts){
      x.save(); x.setLineDash([2,5]); x.strokeStyle=css("--faint"); x.lineWidth=1;
      [tail.c-slPts, tail.c+slPts].forEach(p=>{
        if(p<lo||p>hi) return;
        const y=Math.round(Y(p))+0.5;
        x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke();
      });
      x.restore();
    }
  }

  const line=(p,color,dash)=>{
    if(p<lo||p>hi) return;
    x.save(); x.setLineDash(dash); x.strokeStyle=color; x.lineWidth=1.6;
    const y=Math.round(Y(p))+0.5;
    x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke(); x.restore();
  };
  if(pos){
    line(pos.target, css("--win-faded"), [7,6]);
    line(pos.stop, css("--loss-faded"), [7,6]);
    line(pos.entry, css("--text"), []);
  }

  if(mode === "replay" && right >= ci && ci >= lo0){
    x.save(); x.strokeStyle=css("--accent"); x.lineWidth=1.5;
    const xe=Math.round(X(ci)+bw/2+3)+0.5;
    x.beginPath(); x.moveTo(xe,T); x.lineTo(xe,T+h); x.stroke(); x.restore();
    const t = wide ? B.t[ci].slice(5) : hhmm(B.t[ci]);
    x.font='700 10.5px "JetBrains Mono"';
    const tw = x.measureText(t).width;
    const bx = Math.min(L+w-tw-12, Math.max(L, X(ci)-tw/2-6));
    x.fillStyle=css("--accent"); x.fillRect(bx, T+h+5, tw+12, 17);
    x.fillStyle=css("--ground"); x.fillText(t, bx+6, T+h+14);
  }

  if(mode === "browse" && hover != null && hover >= lo0 && hover <= right){
    const b = bar(hover);
    x.save(); x.setLineDash([3,4]); x.strokeStyle="rgba(53,224,240,.55)"; x.lineWidth=1;
    const cx = Math.round(X(hover))+0.5;
    x.beginPath(); x.moveTo(cx,T); x.lineTo(cx,T+h); x.stroke(); x.restore();
    x.font='700 10.5px "JetBrains Mono"';
    const lab = b.t.slice(5) + "  cut here";
    const tw = x.measureText(lab).width;
    const bx = Math.min(L+w-tw-12, Math.max(L, X(hover)-tw/2-6));
    x.fillStyle=css("--accent"); x.fillRect(bx, T+h+5, tw+12, 17);
    x.fillStyle=css("--ground"); x.fillText(lab, bx+6, T+h+14);
  }

  const tag=(p,bg)=>{
    if(p<lo||p>hi) return;
    const y=Y(p);
    x.font='700 10.5px "JetBrains Mono"';
    const txt=px(p), tw=x.measureText(txt).width;
    x.fillStyle=bg; x.fillRect(L+w+2, y-8.5, tw+13, 17);
    x.fillStyle=css("--ground"); x.fillText(txt, L+w+8, y+0.5);
  };
  if(tail) tag(tail.c, css("--accent"));
  if(pos){ tag(pos.target, css("--win")); tag(pos.stop, css("--loss")); tag(pos.entry, css("--text")); }
  if(pos && pos.i >= lo0 && pos.i <= right){
    x.beginPath(); x.arc(X(pos.i),Y(pos.entry),4.5,0,7);
    x.fillStyle=css("--text"); x.fill();
    x.strokeStyle=css("--raised"); x.lineWidth=2; x.stroke();
  }
}

function panels(){
  const b = B && B.t.length ? bar(mode === "browse" ? B.t.length-1 : ci) : null;
  document.getElementById("mMode").textContent = mode === "browse" ? "BROWSE" : "REPLAY";
  document.getElementById("bTime").textContent = b ? b.t : "—";
  document.getElementById("bPrice").textContent = b ? px(b.c) : "—";
  document.getElementById("bTf").textContent = tf;
  document.getElementById("hint").textContent = mode === "browse"
    ? "Click a bar to cut the chart there"
    : "Space plays / → steps / B buys / S sells / drag to pan / Esc to browse";

  const net = trades.reduce((a,t)=>a+t.pnl,0);
  const el = document.getElementById("bPnl");
  el.textContent = trades.length ? money(net) : "—";
  el.style.color = trades.length ? (net>=0?css("--win"):css("--loss")) : "";

  const box = document.getElementById("posBox");
  if(pos && b){
    const long = pos.side==="long";
    const moved = long ? b.c - pos.entry : pos.entry - b.c;
    const r = moved / pos.risk, col = r>=0 ? "var(--win)" : "var(--loss)";
    const q = pos.qty || 1;
    box.innerHTML = '<h3 style="margin-bottom:9px">Open ' + (long?"long":"short") +
      ' &times;' + q + '</h3>' +
      '<table class="pos">' +
      '<tr><td>entry</td><td>'+px(pos.entry)+'</td></tr>' +
      '<tr><td>stop</td><td class="loss">'+px(pos.stop)+'</td></tr>' +
      '<tr><td>target</td><td class="win">'+px(pos.target)+'</td></tr>' +
      '<tr><td>open</td><td style="color:'+col+'">'+rr(r)+' &nbsp; '+
        money(moved*(POINT[B.sym||sym()]||1)*q)+'</td></tr></table>' +
      '<p class="note" style="margin-top:8px">Drag the red or green line on the '
      + 'chart to move the stop or target.</p>' +
      '<button style="width:100%; margin-top:10px" onclick="closeNow()">Close at market</button>';
  } else if(mode === "browse"){
    box.innerHTML = '<p class="flat">Cut the chart first. You cannot trade a stretch '
      + 'of history you can already see the end of.</p>';
  } else {
    box.innerHTML = '<p class="flat">Flat. Buy or sell to open at the price on screen.</p>';
  }
  // While flat, the price fields track the bar you are standing on, so they are
  // always a real order rather than a stale one. Skipped if you are typing in
  // them, since overwriting a half-entered price is maddening.
  const editing = document.activeElement &&
                  ["slPx","tpPx","slPts","tpR"].indexOf(document.activeElement.id) >= 0;
  if(!pos && b && !editing){
    const e = b.c;
    document.getElementById("slPx").value = (e - pts()).toFixed(2);
    document.getElementById("tpPx").value = (e + pts() * rmul()).toFixed(2);
  }

  const canTrade = !!B && mode === "replay" && !pos;
  document.getElementById("btnBuy").disabled = !canTrade;
  document.getElementById("btnSell").disabled = !canTrade;
  ["btnPlay","btnStep","btnJump"].forEach(id=>{
    const e = document.getElementById(id);
    if(e) e.disabled = !B || mode === "browse";
  });

  const log = document.getElementById("logBox");
  if(!trades.length){
    log.innerHTML = '<p class="flat">No trades yet.</p>';
    document.getElementById("totBox").style.display = "none";
    document.getElementById("btnExport").disabled = true;
  } else {
    const rows = trades.slice().reverse().slice(0,12).map(t=>
      '<tr><td>'+t.day.slice(5)+'</td><td>'+t.symbol+'</td><td>'+t.tf+'</td>' +
      '<td>'+t.side+'</td><td>'+t.open_t+'</td><td>'+t.exit_type+'</td>' +
      '<td class="'+(t.got_r>=0?"win":"loss")+'">'+rr(t.got_r)+'</td>' +
      '<td class="'+(t.pnl>=0?"win":"loss")+'">'+money(t.pnl)+'</td></tr>').join("");
    log.innerHTML = '<table class="log"><tr><th>Day</th><th>Sym</th><th>TF</th>' +
      '<th>Side</th><th>In</th><th>Out</th><th>R</th><th>P&amp;L</th></tr>' + rows +
      '</table>' + (trades.length>12 ?
        '<p class="note">Showing the last 12 of '+trades.length+'.</p>' : "");
    const wins = trades.filter(t=>t.pnl>0).length;
    const totR = trades.reduce((a,t)=>a+t.got_r,0);
    const totP = trades.reduce((a,t)=>a+t.pnl,0);
    document.getElementById("tCount").textContent = trades.length;
    document.getElementById("tWon").textContent =
      wins + " / " + trades.length + "  (" + Math.round(wins/trades.length*100) + "%)";
    const rEl = document.getElementById("tR");
    rEl.textContent = rr(totR); rEl.style.color = totR>=0?"var(--win)":"var(--loss)";
    const pEl = document.getElementById("tPnl");
    pEl.textContent = money(totP); pEl.style.color = totP>=0?"var(--win)":"var(--loss)";
    document.getElementById("totBox").style.display = "flex";
    document.getElementById("btnExport").disabled = false;
  }
}

// ------------------------------------------------------- pointer + keys ----
function barAt(ev){
  const cv = document.getElementById("c");
  const r = cv.getBoundingClientRect();
  const g = geom(r.width, 490);
  const rel = (ev.clientX - r.left - g.L) / g.w;
  const lo0 = Math.max(0, right - span + 1);
  return Math.round(lo0 + rel * span - 0.5);
}

// y on the canvas back to a price, using the scale the last render used
function priceAt(ev){
  if(!vscale) return null;
  const r = document.getElementById("c").getBoundingClientRect();
  const y = ev.clientY - r.top;
  return vscale.hi - (y - vscale.T) / vscale.h * (vscale.hi - vscale.lo);
}

// which of the open position's levels the pointer is sitting on, if any
function levelUnder(ev){
  if(!pos || !vscale) return null;
  const p = priceAt(ev);
  if(p == null) return null;
  const tol = (vscale.hi - vscale.lo) * 0.012;
  if(Math.abs(p - pos.stop) < tol) return "stop";
  if(Math.abs(p - pos.target) < tol) return "target";
  return null;
}

(function pointer(){
  const cv = document.getElementById("c");
  cv.addEventListener("mousemove", e=>{
    if(!B) return;
    if(axisDrag){
      // pulling down opens the range out and flattens the candles, pulling up
      // squeezes it and stands them up
      const dy = e.clientY - axisDrag.y;
      pzoom = Math.max(0.25, Math.min(8, axisDrag.from * Math.exp(-dy / 220)));
      draw();
      return;
    }
    if(holding){
      // A stop may be tightened or widened freely, but it can never be moved to
      // the wrong side of the entry: there it is already triggered, which is the
      // exact mistake that cost trade 4 in the diary.
      const p = priceAt(e);
      if(p != null){
        const long = pos.side === "long";
        if(holding === "stop"){
          pos.stop = long ? Math.min(p, pos.entry - 0.25) : Math.max(p, pos.entry + 0.25);
        } else {
          pos.target = long ? Math.max(p, pos.entry + 0.25) : Math.min(p, pos.entry - 0.25);
        }
        render();
      }
      return;
    }
    if(drag){
      const r = cv.getBoundingClientRect(), g = geom(r.width, 490);
      const moved = Math.round((drag.x - e.clientX) / g.w * span);
      const cap = mode === "browse" ? B.t.length - 1 : ci;
      right = Math.max(Math.min(span - 1, cap), Math.min(cap, drag.right + moved));
      draw();
      return;
    }
    const k = barAt(e);
    hover = (k >= 0 && k < B.t.length) ? k : null;
    if(mode === "browse") draw();
  });
  cv.addEventListener("mouseleave", ()=>{ hover=null; if(mode==="browse") draw(); });
  cv.addEventListener("mousedown", e=>{
    if(!B) return;
    if(overAxis(e)){
      axisDrag = {y: e.clientY, from: pzoom};
      cv.classList.add("grabbing");
      return;
    }
    const lvl = levelUnder(e);
    if(lvl){ holding = lvl; cv.classList.add("grabbing"); return; }
    drag = {x:e.clientX, right}; cv.classList.add("grabbing");
  });
  window.addEventListener("mouseup", e=>{
    const cv2 = document.getElementById("c");
    if(axisDrag){
      axisDrag = null;
      cv2.classList.remove("grabbing");
      return;
    }
    if(holding){
      holding = null;
      cv2.classList.remove("grabbing");
      render();
      return;
    }
    if(!drag) return;
    const still = Math.abs(e.clientX - drag.x) < 4;
    drag = null;
    cv2.classList.remove("grabbing");
    if(still && mode === "browse" && B){
      const k = barAt(e);
      if(k >= 0 && k < B.t.length) snipAt(k);
    }
  });
  cv.addEventListener("wheel", e=>{
    if(!B) return;
    e.preventDefault();
    // A two finger sideways swipe on a trackpad arrives as deltaX, and that
    // pans time: fingers right moves forward, fingers left moves back. Vertical
    // is zoom, which is what every charting platform does. A pinch arrives as a
    // wheel with ctrlKey set, so it lands on zoom too.
    if(Math.abs(e.deltaX) > Math.abs(e.deltaY)){
      panBy(e.deltaX > 0 ? 1 : -1, Math.max(1, Math.round(span * 0.05)));
      return;
    }
    zoom(e.deltaY > 0 ? 1 : -1);
  }, {passive:false});

  // Dragging the price axis stretches or flattens the candles. Double clicking
  // it puts the scale back to fitting whatever is on screen.
  cv.addEventListener("dblclick", e=>{
    if(overAxis(e)){ pzoom = 1; render(); }
  });
})();

function panBy(dir, bars){
  if(!B) return;
  const cap = mode === "browse" ? B.t.length - 1 : ci;
  right = Math.max(Math.min(span - 1, cap), Math.min(cap, right + dir * bars));
  draw();
}

function overAxis(ev){
  if(!vscale) return false;
  const r = document.getElementById("c").getBoundingClientRect();
  return (ev.clientX - r.left) > vscale.L + vscale.w;
}

document.addEventListener("keydown", e=>{
  if(/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
  if(e.key === " "){ e.preventDefault(); togglePlay(); }
  else if(e.key === "ArrowRight"){ e.preventDefault(); step(1); }
  else if(e.key === "ArrowLeft"){ e.preventDefault(); panBy(-1, 1); }
  else if(e.key === "ArrowUp"){ e.preventDefault(); pzoom = Math.min(8, pzoom*1.25); draw(); }
  else if(e.key === "ArrowDown"){ e.preventDefault(); pzoom = Math.max(0.25, pzoom/1.25); draw(); }
  else if(e.key.toLowerCase() === "b"){ place("long"); }
  else if(e.key.toLowerCase() === "s"){ place("short"); }
  else if(e.key.toLowerCase() === "c"){ closeNow(); }
  else if(e.key.toLowerCase() === "l"){ toggleLevels(); }
  else if(e.key === "Escape"){ toBrowse(); }
});
window.addEventListener("resize", draw);

reload(true);
</script>
"""


if __name__ == "__main__":
    main()
