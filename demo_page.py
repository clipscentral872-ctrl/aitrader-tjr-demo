"""Build the Demo tab: a live chart you can paper trade, beside the system's own.

Two things share this tab. Your manual paper trades, placed at whatever the feed
last printed, and the state of the automated demo that runs on GitHub. Over
enough trades they are the comparison that decides whether the system is worth
anything next to your own hand.

The feed is stated as delayed on the page rather than quietly presented as live.
A price that lags ten minutes but looks current teaches the wrong lesson about
fills, and that lesson is expensive to unlearn.

The session levels are drawn by the same code the strategy reasons with, so the
lines are the ones the system is actually looking at. Each appears only once its
session has CLOSED, which is why New York is missing from the chart at eleven in
the morning: nobody knows where that high is yet.
"""
import functools
import io
import os

print = functools.partial(print, flush=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(ROOT, "journal_data", "demo.html")


def main():
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    io.open(OUT, "w", encoding="utf-8", newline="\n").write(PAGE)
    print(f"demo tab -> {OUT}  ({os.path.getsize(OUT)/1024:.0f} KB)")


PAGE = r"""<!doctype html>
<html><head><meta charset="utf-8"><title>Demo</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800;900&family=Chakra+Petch:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap">
<style>
:root{
  --ground:#05070C; --raised:#0A0F17; --lift:#111A26;
  --line:#1B2838; --line-soft:#121A26;
  --text:#E8F0F8; --muted:#7E90A8; --faint:#4A5A70;
  --accent:#35E0F0; --win:#2BE08A; --loss:#FF5C6E;
  --win-faded:#177A4C; --loss-faded:#8E2F3A;
  --win-zone:rgba(43,224,138,.085); --loss-zone:rgba(255,92,110,.085);
  --candle-up:#22B877; --candle-dn:#C4485A;
  --asia:#4DB98A; --london:#35E0F0; --ny:#C9D4E4; --day:#B08CE0;
}
*{box-sizing:border-box}
body{
  margin:0; color:var(--text); font-family:"Chakra Petch",system-ui,sans-serif;
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
h2{font-family:"Orbitron",sans-serif; font-weight:800; font-size:13px; margin:0 0 13px;
  letter-spacing:.13em; text-transform:uppercase; display:flex; align-items:center; gap:12px}
h2::before{content:""; width:24px; height:2px; background:var(--accent);
  box-shadow:0 0 12px var(--accent); flex:none}
h3{font-family:"Orbitron",sans-serif; font-size:9.5px; text-transform:uppercase;
  letter-spacing:.15em; color:var(--accent); margin:0 0 12px; font-weight:700}
section{margin-bottom:26px}
.lead{color:var(--muted); font-size:12px; margin:0 0 14px; max-width:78ch}
.warn{border-left:2px solid var(--accent); background:var(--raised); padding:10px 15px;
  font-size:11px; color:var(--muted); text-transform:uppercase; letter-spacing:.1em;
  margin:0 0 16px}

label{font-size:9px; text-transform:uppercase; letter-spacing:.17em; color:var(--faint);
  font-weight:600; display:block; margin-bottom:5px}
select,input{background:var(--lift); border:1px solid var(--line); color:var(--text);
  font-family:"JetBrains Mono",monospace; font-size:14px; padding:8px 10px; width:100%}
select:focus,input:focus{outline:2px solid var(--accent); outline-offset:1px}
button{background:var(--lift); border:1px solid var(--line); color:var(--text);
  font-family:"Chakra Petch",sans-serif; font-weight:600; font-size:11.5px;
  text-transform:uppercase; letter-spacing:.11em; padding:9px 14px; cursor:pointer;
  transition:border-color .13s, background .13s, box-shadow .13s}
button:hover:not(:disabled){border-color:var(--accent)}
button:disabled{opacity:.32; cursor:not-allowed}
button:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
button.on{border-color:var(--accent); background:var(--lift);
  box-shadow:0 0 20px rgba(53,224,240,.22)}
button.buy{border-color:var(--win-faded); color:var(--win)}
button.buy:hover:not(:disabled){border-color:var(--win)}
button.sell{border-color:var(--loss-faded); color:var(--loss)}
button.sell:hover:not(:disabled){border-color:var(--loss)}

.chartcard{background:var(--raised); border:1px solid var(--line)}
.bar{display:flex; flex-wrap:wrap; gap:14px; align-items:baseline; padding:11px 16px;
  border-bottom:1px solid var(--line-soft)}
.bar .k{font-size:9px; text-transform:uppercase; letter-spacing:.15em; color:var(--faint);
  font-weight:600}
.bar .v{font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
  font-size:15px; font-weight:700; margin-left:6px}
.big{font-size:26px !important}
canvas{display:block; width:100%; height:430px; cursor:crosshair}
canvas.grabbing{cursor:grabbing}
.controls{display:flex; flex-wrap:wrap; gap:7px; align-items:center; padding:11px 16px;
  border-top:1px solid var(--line-soft)}
.controls .spacer{flex:1}
.hint{font-size:10px; color:var(--faint); text-transform:uppercase; letter-spacing:.1em}
.tfrow{display:flex; gap:4px}
.tfrow button{padding:8px 11px; letter-spacing:.06em}

.deck{display:grid; grid-template-columns:minmax(0,1fr) minmax(0,1.25fr); gap:16px;
  margin-top:16px}
@media(max-width:900px){ .deck{grid-template-columns:1fr} }
.panel{background:var(--raised); border:1px solid var(--line); padding:15px 17px}
.grid3{display:grid; grid-template-columns:repeat(3,1fr); gap:10px; margin-bottom:11px}
.rrbox{display:flex; flex-wrap:wrap; gap:15px; align-items:baseline; background:var(--lift);
  border:1px solid var(--line); padding:10px 13px; margin-bottom:12px}
.rrbox .k{font-size:8.5px; text-transform:uppercase; letter-spacing:.15em;
  color:var(--faint); font-weight:600}
.rrbox .v{font-family:"JetBrains Mono",monospace; font-variant-numeric:tabular-nums;
  font-size:15px; font-weight:700; margin-left:6px}
.rrbox.bad{border-color:var(--loss-faded)}
.rrwarn{flex-basis:100%; font-size:11px; color:var(--loss); text-transform:uppercase;
  letter-spacing:.1em; font-weight:600; margin-top:2px}
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
.win{color:var(--win)} .loss{color:var(--loss)} .dim{color:var(--faint)}
.sysrow{display:flex; flex-wrap:wrap; gap:24px}
.sysrow span{font-size:9px; text-transform:uppercase; letter-spacing:.16em;
  color:var(--faint); font-weight:600}
.sysrow b{font-family:"JetBrains Mono",monospace; font-size:16px; margin-left:8px}
</style></head><body>
<div class="wrap">

<p class="warn">Yahoo's futures quotes run roughly ten minutes behind. Good enough
to practise on, not good enough to judge a fill by.</p>

<div class="chartcard hud">
  <div class="bar">
    <select id="sym" style="width:auto" onchange="switchSym()">
      <option>NQ</option><option>ES</option>
    </select>
    <span class="v big" id="bPrice">&mdash;</span>
    <span><span class="k">As of</span><span class="v" id="bAt">&mdash;</span></span>
    <span style="margin-left:auto" class="tfrow" id="tfrow"></span>
  </div>
  <canvas id="c"></canvas>
  <div class="controls">
    <button id="btnLevels" onclick="toggleLevels()">Session levels</button>
    <button onclick="zoom(-1)">Zoom in</button>
    <button onclick="zoom(1)">Zoom out</button>
    <button onclick="resetView()">Reset</button>
    <span class="spacer"></span>
    <span class="hint">Two fingers sideways pans &middot; scroll zooms &middot;
      drag the price axis to stretch</span>
  </div>
</div>

<div class="deck">
  <div class="panel hud">
    <h3>Ticket</h3>
    <div class="grid3">
      <div>
        <label for="qty">Contracts</label>
        <input id="qty" type="number" step="1" min="1" value="1" oninput="ticket()">
      </div>
      <div>
        <label for="slPts">Stop, pts</label>
        <input id="slPts" type="number" step="0.25" value="20" oninput="fromPts()">
      </div>
      <div>
        <label for="tpR">Target, R</label>
        <input id="tpR" type="number" step="0.1" value="2" oninput="fromPts()">
      </div>
    </div>
    <div class="grid3" style="grid-template-columns:1fr 1fr">
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
      <button class="buy"  id="bBuy"  onclick="open_('long')">Buy</button>
      <button class="sell" id="bSell" onclick="open_('short')">Sell</button>
    </div>
    <p class="lead" style="margin-top:9px; font-size:11.5px">
      Prices shown for a long. Sell flips them.
    </p>
    <div id="posBox" style="margin-top:14px"></div>
  </div>

  <div class="panel hud">
    <h3>Your paper trades</h3>
    <div id="logBox"><p class="flat">Nothing yet.</p></div>
    <div style="display:flex; gap:9px; margin-top:14px">
      <button onclick="clearAll()">Clear all</button>
    </div>
    <p class="lead" style="margin-top:12px">These sit in the Diary under Demo,
    never inside your live figures.</p>
  </div>
</div>

<section style="margin-top:26px">
  <h2>The automated system</h2>
  <div class="panel hud">
    <div class="sysrow" id="sysRow"><span>Loading&hellip;</span></div>
    <p class="lead" id="sysNote" style="margin-top:14px"></p>
  </div>
</section>
</div>

<script>
const POINT = {NQ:20, ES:50};
const TFS = ["1m","5m","15m","1h"];
let tf = "5m", B = null, quote = null, paper = {position:null, trades:[]};
let levels = [], showLevels = true;
let span = 120, right = 0, pzoom = 1;
let drag = null, axisDrag = null, vscale = null, holding = null;

const px = v => v.toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const money = v => (v<0?"-":"+") + "$" + Math.abs(v).toLocaleString(undefined,{maximumFractionDigits:0});
const rr = v => (v>=0?"+":"") + v.toFixed(2) + "R";
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const symOf = () => document.getElementById("sym").value;
const bar = k => ({t:B.t[k], o:B.o[k], h:B.h[k], l:B.l[k], c:B.c[k]});
const hhmm = s => (s||"").slice(11);

// ---------------------------------------------------------------- data ----
function drawTfs(){
  document.getElementById("tfrow").innerHTML = TFS.map(x =>
    `<button class="${x===tf?"on":""}" onclick="setTf('${x}')">${x}</button>`).join("");
}

async function setTf(next){ tf = next; drawTfs(); await pullBars(); render(); }
async function switchSym(){ B = null; levels = []; await pullAll(); }

async function pullBars(){
  try{
    const d = await (await fetch("/api/bars?sym=" + symOf() + "&tf=" + tf + "&n=500")).json();
    if(!d.error && d.t && d.t.length){
      const atEnd = !B || right >= B.t.length - 2;   // stay pinned to live unless panned away
      B = d;
      if(atEnd) right = B.t.length - 1;
      right = Math.min(right, B.t.length - 1);
      span = Math.min(span, B.t.length);
    }
  }catch(e){}
}

async function pullLevels(){
  try{
    const d = await (await fetch("/api/levels?sym=" + symOf())).json();
    levels = (d && d.levels) ? d.levels : [];
  }catch(e){ levels = []; }
}

async function pullQuote(){
  try{
    const d = await (await fetch("/api/quote?sym=" + symOf())).json();
    if(!d.error) quote = d;
  }catch(e){}
}

async function pullPaper(){
  try{ paper = await (await fetch("/api/paper")).json(); }catch(e){}
}

async function pullSystem(){
  let d = {};
  try{ d = await (await fetch("/api/demo")).json(); }catch(e){ return; }

  // Two books run against the same feed, differing only in how far the target
  // sits from the stop. Shown side by side because that difference is the whole
  // question, and a single blended equity figure would hide it.
  const books = [
    {name: "0.6-0.8R", b: d},
    {name: "1.3-2.2R", b: d.wide || null},
  ];
  document.getElementById("sysRow").innerHTML = books.map(x=>{
    if(!x.b) return '<span>'+x.name+'<b class="dim">not started</b></span>';
    const ts = x.b.trades || [];
    const eq = x.b.equity == null ? "—" : "$" + Number(x.b.equity).toLocaleString();
    const wins = ts.filter(t=>t.pnl>0).length;
    const rate = ts.length ? Math.round(wins/ts.length*100) + "%" : "—";
    const net = x.b.equity != null ? x.b.equity - 50000 : 0;
    return '<span>'+x.name+'<b class="'+(net>=0?"win":"loss")+'">'+eq+'</b></span>' +
           '<span>Trades<b>'+ts.length+'</b></span>' +
           '<span>Won<b>'+rate+'</b></span>';
  }).join("") + '<span>Polls<b>'+(d.polls||0)+'</b></span>';

  const n = (d.trades||[]).length;
  const w = ((d.wide||{}).trades||[]).length;
  document.getElementById("sysNote").textContent =
    "Both books see the same bars at the same moment and differ only in how far "
    + "the target sits from the stop, so what separates them is the shape of the "
    + "trade rather than the luck of different entries. The tight book wins far "
    + "more often and each win is small enough that costs take a large bite; the "
    + "wide book will win less often for more. Neither has enough trades yet to "
    + "settle it: " + n + " and " + w + " so far, against the few hundred it "
    + "would take. They appear in the Diary under System.";
}

async function pullAll(){
  await Promise.all([pullBars(), pullQuote(), pullPaper(), pullLevels()]);
  if(!paper.position) fromPts();
  render();
}

// -------------------------------------------------------------- ticket ----
const val = id => parseFloat(document.getElementById(id).value);
const refPrice = () => (quote ? quote.price : (B && B.t.length ? bar(B.t.length-1).c : null));
const pts = () => Math.abs(val("slPts") || 0);
const rmul = () => Math.abs(val("tpR") || 0);
const qtyOf = () => Math.max(1, parseInt(document.getElementById("qty").value, 10) || 1);

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
  const p = pts(), r = rmul(), q = qtyOf(), pv = POINT[symOf()] || 1;
  if(e == null || !p){
    box.innerHTML = '<span class="k">Waiting for a price</span>';
    box.className = "rrbox"; return;
  }
  const risk = p * pv * q, reward = p * r * pv * q, bad = r < 1;
  box.className = "rrbox" + (bad ? " bad" : "");
  box.innerHTML =
    '<span><span class="k">Risking</span><span class="v loss">' + money(-risk) + '</span></span>' +
    '<span><span class="k">To make</span><span class="v win">' + money(reward) + '</span></span>' +
    '<span><span class="k">R:R</span><span class="v">' + r.toFixed(2) + '</span></span>' +
    (bad ? '<span class="rrwarn">Risking more than you stand to make</span>' : "");
  draw();
}

async function open_(side){
  const sym = symOf();
  if(!quote || paper.position) return;
  const slPts = pts(), rM = rmul();
  if(!slPts || !rM) return;
  const e = quote.price;
  const body = {
    symbol: sym, side, entry: e, at: quote.at, risk_pts: slPts, planned_rr: rM,
    qty: qtyOf(),
    stop:   side==="long" ? e - slPts : e + slPts,
    target: side==="long" ? e + slPts*rM : e - slPts*rM,
  };
  const r = await fetch("/api/paper/open",
    {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  paper = await r.json();
  render();
}

async function closeNow(){
  const p = paper.position;
  if(!p || !quote) return;
  const moved = p.side==="long" ? quote.price - p.entry : p.entry - quote.price;
  const n = p.qty || 1;
  const body = Object.assign({}, p, {
    exit: quote.price, closed_at: quote.at,
    got_pts: +moved.toFixed(2),
    got_r: +(moved / p.risk_pts).toFixed(2),
    pnl: +(moved * (POINT[p.symbol]||1) * n).toFixed(2),
  });
  const r = await fetch("/api/paper/close",
    {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify(body)});
  paper = await r.json();
  fromPts();
  render();
}

async function clearAll(){
  if(!confirm("Delete every paper trade on record?")) return;
  await fetch("/api/paper/clear", {method:"POST"});
  paper = {position:null, trades:[]};
  render();
}

function toggleLevels(){
  showLevels = !showLevels;
  document.getElementById("btnLevels").classList.toggle("on", showLevels);
  draw();
}

function zoom(dir){
  if(!B) return;
  span = Math.max(25, Math.min(B.t.length, Math.round(span * (dir>0?1.35:0.74))));
  draw();
}

function resetView(){
  if(!B) return;
  span = 120; right = B.t.length - 1; pzoom = 1; draw();
}

// -------------------------------------------------------------- render ----
function render(){ draw(); panels(); }
function geom(W,H){ const L=14,R=96,T=18,Bm=28; return {L,R,T,B:Bm,w:W-L-R,h:H-T-Bm}; }

function draw(){
  const cv = document.getElementById("c");
  const W = cv.clientWidth, H = 430, dpr = window.devicePixelRatio || 1;
  cv.width = W*dpr; cv.height = H*dpr;
  const x = cv.getContext("2d"); x.scale(dpr,dpr);
  x.textBaseline = "middle"; x.clearRect(0,0,W,H);
  if(!B || !B.t.length){
    x.fillStyle=css("--faint"); x.font='14px "Chakra Petch"';
    x.fillText("Loading bars...", 22, H/2); return;
  }

  const g = geom(W,H), {L,T,w,h} = g;
  right = Math.min(right, B.t.length-1);
  const lo0 = Math.max(0, right - span + 1);
  const shown = [];
  for(let k=lo0;k<=right;k++) shown.push(bar(k));
  if(!shown.length) return;

  let lo = Math.min.apply(null, shown.map(b=>b.l));
  let hi = Math.max.apply(null, shown.map(b=>b.h));
  const p = paper.position;
  if(p) [p.entry,p.stop,p.target].forEach(v=>{ if(v!=null){ lo=Math.min(lo,v); hi=Math.max(hi,v); } });
  if(showLevels) levels.forEach(L2=>{ lo=Math.min(lo,L2.price); hi=Math.max(hi,L2.price); });
  const pad=(hi-lo)*0.08||1; lo-=pad; hi+=pad;
  if(pzoom !== 1){ const m=(lo+hi)/2, half=(hi-lo)/2/pzoom; lo=m-half; hi=m+half; }

  const Y = v => T + (hi-v)/(hi-lo)*h;
  const Yc = v => Math.max(T, Math.min(T+h, Y(v)));
  const X = k => L + (k-lo0+0.5)/span*w;
  const bw = Math.max(1.2, Math.min(13, w/span*0.62));
  vscale = {lo,hi,T,h,L,w};

  if(p){
    const band=(a,b2,f)=>{ const y0=Yc(a),y1=Yc(b2);
      x.fillStyle=f; x.fillRect(L,Math.min(y0,y1),w,Math.abs(y1-y0)); };
    if(p.stop!=null) band(p.entry,p.stop,css("--loss-zone"));
    if(p.target!=null) band(p.entry,p.target,css("--win-zone"));
  }

  x.strokeStyle=css("--line-soft"); x.lineWidth=1;
  x.fillStyle=css("--faint"); x.font='400 10.5px "JetBrains Mono"';
  for(let k=0;k<=4;k++){
    const v=lo+(hi-lo)*k/4, y=Math.round(Y(v))+0.5;
    x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke();
    x.fillText(px(v), L+w+9, y);
  }
  const wide = shown[0].t.slice(0,10) !== shown[shown.length-1].t.slice(0,10);
  const every = Math.max(1, Math.ceil(shown.length/9));
  x.textAlign="center";
  shown.forEach((b,k)=>{ if(!(k%every))
    x.fillText(wide ? b.t.slice(5,10) : hhmm(b.t), X(lo0+k), T+h+14); });
  x.textAlign="left";

  shown.forEach((b,k)=>{
    const up=b.c>=b.o, cx=X(lo0+k);
    x.strokeStyle = x.fillStyle = up?css("--candle-up"):css("--candle-dn");
    x.lineWidth=1;
    x.beginPath(); x.moveTo(Math.round(cx)+0.5,Y(b.h)); x.lineTo(Math.round(cx)+0.5,Y(b.l)); x.stroke();
    const y0=Y(Math.max(b.o,b.c)), y1=Y(Math.min(b.o,b.c));
    x.fillRect(cx-bw/2,y0,bw,Math.max(1.2,y1-y0));
  });

  // Session highs and lows, each labelled where it sits. Drawn under the price
  // tags so a level never hides the thing you are trading.
  if(showLevels){
    x.font='600 10px "Chakra Petch"';
    levels.forEach(L2=>{
      if(L2.price < lo || L2.price > hi) return;
      const col = css("--" + L2.family) || css("--muted");
      const y = Math.round(Y(L2.price))+0.5;
      x.save(); x.setLineDash([6,5]); x.strokeStyle=col; x.globalAlpha=.8; x.lineWidth=1.4;
      x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke(); x.restore();
      const tw = x.measureText(L2.label).width;
      x.fillStyle=css("--raised"); x.globalAlpha=.9;
      x.fillRect(L+6, y-14, tw+9, 13); x.globalAlpha=1;
      x.fillStyle=col; x.fillText(L2.label, L+10, y-7.5);
    });
  }

  const line=(v,color,dash)=>{
    if(v==null||v<lo||v>hi) return;
    x.save(); x.setLineDash(dash); x.strokeStyle=color; x.lineWidth=1.6;
    const y=Math.round(Y(v))+0.5;
    x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke(); x.restore();
  };
  if(p){
    line(p.target, css("--win-faded"), [7,6]);
    line(p.stop, css("--loss-faded"), [7,6]);
    line(p.entry, css("--text"), []);
  } else {
    // where the pending order would sit
    const e = refPrice(), sp = pts();
    if(e!=null && sp){
      x.save(); x.setLineDash([2,5]); x.strokeStyle=css("--faint"); x.lineWidth=1;
      [e-sp, e+sp].forEach(v=>{ if(v<lo||v>hi) return;
        const y=Math.round(Y(v))+0.5;
        x.beginPath(); x.moveTo(L,y); x.lineTo(L+w,y); x.stroke(); });
      x.restore();
    }
  }

  const tag=(v,bg)=>{
    if(v==null||v<lo||v>hi) return;
    const y=Y(v);
    x.font='700 10.5px "JetBrains Mono"';
    const txt=px(v), tw=x.measureText(txt).width;
    x.fillStyle=bg; x.fillRect(L+w+2, y-8.5, tw+13, 17);
    x.fillStyle=css("--ground"); x.fillText(txt, L+w+8, y+0.5);
  };
  if(quote) tag(quote.price, css("--accent"));
  if(p){ tag(p.target, css("--win")); tag(p.stop, css("--loss")); tag(p.entry, css("--text")); }
}

function panels(){
  document.getElementById("bPrice").textContent = quote ? px(quote.price) : "—";
  document.getElementById("bAt").textContent = quote ? hhmm(quote.at).slice(0,5)+" UTC" : "—";
  document.getElementById("btnLevels").classList.toggle("on", showLevels);

  const p = paper.position, box = document.getElementById("posBox");
  if(p){
    const n = p.qty || 1;
    let live = "";
    if(quote){
      const moved = p.side==="long" ? quote.price - p.entry : p.entry - quote.price;
      const r = moved / p.risk_pts;
      live = '<tr><td>open</td><td class="'+(r>=0?"win":"loss")+'">'+rr(r)+
             ' &nbsp; '+money(moved*(POINT[p.symbol]||1)*n)+'</td></tr>';
    }
    box.innerHTML = '<h3 style="margin-bottom:9px">Open '+p.side+' &middot; '+
      p.symbol+' &times;'+n+'</h3><table class="pos">' +
      '<tr><td>entry</td><td>'+px(p.entry)+'</td></tr>' +
      '<tr><td>stop</td><td class="loss">'+px(p.stop)+'</td></tr>' +
      '<tr><td>target</td><td class="win">'+px(p.target)+'</td></tr>' + live +
      '</table><button style="width:100%; margin-top:11px" onclick="closeNow()">Close at market</button>';
  } else {
    box.innerHTML = '<p class="flat">Flat. Buy or sell to open at the price above.</p>';
  }
  document.getElementById("bBuy").disabled  = !!p || !quote;
  document.getElementById("bSell").disabled = !!p || !quote;

  const log = document.getElementById("logBox"), ts = paper.trades || [];
  if(!ts.length){ log.innerHTML = '<p class="flat">Nothing yet.</p>'; return; }
  const tot = ts.reduce((a,t)=>a+t.pnl,0), wins = ts.filter(t=>t.pnl>0).length;
  log.innerHTML = '<table class="log"><tr><th>Sym</th><th>Side</th><th>In</th>' +
    '<th>Out</th><th>R</th><th>P&amp;L</th></tr>' +
    ts.slice().reverse().slice(0,12).map(t =>
      '<tr><td>'+t.symbol+'</td><td>'+t.side+'</td><td>'+px(t.entry)+'</td>' +
      '<td>'+px(t.exit)+'</td>' +
      '<td class="'+(t.got_r>=0?"win":"loss")+'">'+rr(t.got_r)+'</td>' +
      '<td class="'+(t.pnl>=0?"win":"loss")+'">'+money(t.pnl)+'</td></tr>').join("") +
    '</table><p class="lead" style="margin-top:11px">'+ts.length+' trades &middot; '+
    wins+' won &middot; net <b class="'+(tot>=0?"win":"loss")+'">'+money(tot)+'</b></p>';
}

// ------------------------------------------------------- pointer + keys ----
function overAxis(ev){
  if(!vscale) return false;
  const r = document.getElementById("c").getBoundingClientRect();
  return (ev.clientX - r.left) > vscale.L + vscale.w;
}
function panBy(dir, bars){
  if(!B) return;
  right = Math.max(Math.min(span-1, B.t.length-1),
                   Math.min(B.t.length-1, right + dir*bars));
  draw();
}

(function pointer(){
  const cv = document.getElementById("c");
  cv.addEventListener("mousedown", e=>{
    if(!B) return;
    if(overAxis(e)){ axisDrag={y:e.clientY, from:pzoom}; cv.classList.add("grabbing"); return; }
    drag={x:e.clientX, right}; cv.classList.add("grabbing");
  });
  cv.addEventListener("mousemove", e=>{
    if(!B) return;
    if(axisDrag){
      const dy = e.clientY - axisDrag.y;
      pzoom = Math.max(0.25, Math.min(8, axisDrag.from * Math.exp(-dy/220)));
      draw(); return;
    }
    if(drag){
      const r = cv.getBoundingClientRect(), g = geom(r.width, 430);
      const moved = Math.round((drag.x - e.clientX)/g.w*span);
      right = Math.max(Math.min(span-1, B.t.length-1),
                       Math.min(B.t.length-1, drag.right + moved));
      draw();
    }
  });
  window.addEventListener("mouseup", ()=>{
    drag = null; axisDrag = null;
    document.getElementById("c").classList.remove("grabbing");
  });
  cv.addEventListener("wheel", e=>{
    if(!B) return;
    e.preventDefault();
    if(Math.abs(e.deltaX) > Math.abs(e.deltaY)){
      panBy(e.deltaX > 0 ? 1 : -1, Math.max(1, Math.round(span*0.05)));
      return;
    }
    zoom(e.deltaY > 0 ? 1 : -1);
  }, {passive:false});
  cv.addEventListener("dblclick", e=>{ if(overAxis(e)){ pzoom=1; draw(); } });
})();

document.addEventListener("keydown", e=>{
  if(/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) return;
  if(e.key === "ArrowLeft"){ e.preventDefault(); panBy(-1,1); }
  else if(e.key === "ArrowRight"){ e.preventDefault(); panBy(1,1); }
  else if(e.key === "ArrowUp"){ e.preventDefault(); pzoom=Math.min(8,pzoom*1.25); draw(); }
  else if(e.key === "ArrowDown"){ e.preventDefault(); pzoom=Math.max(0.25,pzoom/1.25); draw(); }
  else if(e.key.toLowerCase() === "l"){ toggleLevels(); }
});
window.addEventListener("resize", draw);

drawTfs();
pullAll();
pullSystem();
setInterval(async ()=>{ await Promise.all([pullBars(), pullQuote()]); render(); }, 30000);
setInterval(pullLevels, 300000);
setInterval(pullSystem, 60000);
</script>
</body></html>
"""


if __name__ == "__main__":
    main()
