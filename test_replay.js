/**
 * Drive the real replay page outside a browser.
 *
 * The script inside replay.html is evaluated here against a stub DOM, so these
 * are the actual functions the page runs, not a second copy of the rules that
 * could drift from them. What is being checked is the part that decides whether
 * practice tells the truth: how a stop and a target get filled.
 *
 * Bars are served by the local app now rather than embedded, so the tests inject
 * a slice directly. That keeps them on the arithmetic and off the network.
 */
const fs = require("fs");
const path = require("path");

const HTML = path.join(__dirname, "journal_data", "replay.html");
const src = fs.readFileSync(HTML, "utf8");
const code = src.slice(src.lastIndexOf("<script>") + 8, src.lastIndexOf("</script>"));

// --- the smallest DOM the page will accept -------------------------------
const inputs = {slPts: "20", tpR: "2", speed: "320", sym: "NQ", jump: ""};
const el = (id) => ({
  get value() { return inputs[id] !== undefined ? inputs[id] : ""; },
  set value(v) { inputs[id] = v; },
  set innerHTML(v) { this._html = v; },
  get innerHTML() { return this._html || ""; },
  textContent: "", disabled: false, style: {}, options: [],
  setAttribute() {}, classList: {add() {}, remove() {}},
});
const cache = {};
global.document = {
  getElementById: (id) => (cache[id] = cache[id] || el(id)),
  querySelectorAll: () => [],
  addEventListener() {},
  createElement: () => ({click() {}, style: {}}),
};
global.window = {addEventListener() {}, devicePixelRatio: 1};
global.localStorage = {getItem: () => null, setItem() {}};
global.getComputedStyle = () => ({getPropertyValue: () => "#000"});
global.confirm = () => false;
global.fetch = () => Promise.reject(new Error("no network in tests"));
global.Blob = function () {};
global.URL = {createObjectURL: () => "", revokeObjectURL() {}};
global.setInterval = () => 0;
global.clearInterval = () => {};
global.setTimeout = () => 0;

const noop = new Proxy({}, {get: () => () => noop});
cache.c = {
  clientWidth: 1000, width: 0, height: 0,
  getContext: () => noop,
  addEventListener() {}, removeEventListener() {},
  getBoundingClientRect: () => ({left: 0, top: 0, width: 1000, height: 490}),
  classList: {add() {}, remove() {}},
};

const exportsLine =
  "\nreturn {step, place, close, closeNow, checkFills, fillPrice, bar," +
  " get pos(){return pos}, set pos(v){pos=v}," +
  " get trades(){return trades}, set trades(v){trades=v}," +
  " get ci(){return ci}, set ci(v){ci=v}," +
  " get B(){return B}, set B(v){B=v}," +
  " get mode(){return mode}, set mode(v){mode=v}," +
  " get right(){return right}, set right(v){right=v}};";
const R = new Function(code + exportsLine)();

let failed = 0;
const check = (name, got, want) => {
  const ok = Math.abs(got - want) < 0.001;
  if (!ok) failed++;
  console.log(`  ${ok ? "pass" : "FAIL"}  ${name}  got ${got}, want ${want}`);
};

// a slice of bars in the shape the app serves
function chunk(bars, cut) {
  return {
    sym: "NQ", tf: "5m", cut,
    t: bars.map((b) => b.t), o: bars.map((b) => b.o),
    h: bars.map((b) => b.h), l: bars.map((b) => b.l), c: bars.map((b) => b.c),
  };
}
const flat = (n, price) =>
  Array.from({length: n}, (_, k) => ({
    t: "2026-08-20 " + String(9 + Math.floor((k * 5) / 60)).padStart(2, "0") +
       ":" + String((k * 5) % 60).padStart(2, "0"),
    o: price, h: price + 1, l: price - 1, c: price,
  }));

R.B = chunk(flat(40, 100), 20);
R.ci = 20;
R.right = 20;
R.mode = "replay";

// --- fillPrice: a bar that opens past the level fills at the open ---------
console.log("\nfill price when a bar gaps through the level");
check("long stop, no gap", R.fillPrice({o: 100}, 95, true), 95);
check("long stop, gapped below", R.fillPrice({o: 90}, 95, true), 90);
check("short stop, no gap", R.fillPrice({o: 100}, 105, false), 105);
check("short stop, gapped above", R.fillPrice({o: 110}, 105, false), 110);

// --- checkFills: the rule that decides whether practice is honest --------
const fire = (side, entry, stop, target, b) => {
  R.trades = [];
  R.pos = {side, entry, stop, target, risk: Math.abs(entry - stop), planned: 2,
           t: "2026-08-20 10:00", i: 0};
  R.checkFills(b);
  return R.trades[0];
};

console.log("\nboth levels touched inside one bar counts as the loss");
let t = fire("long", 100, 95, 110, {o: 100, h: 112, l: 94, c: 105, t: "2026-08-20 10:05"});
check("long, both hit -> R", t.got_r, -1);
check("long, both hit -> exit at stop", t.exit, 95);
t = fire("short", 100, 105, 90, {o: 100, h: 106, l: 89, c: 95, t: "2026-08-20 10:05"});
check("short, both hit -> R", t.got_r, -1);

console.log("\nclean outcomes");
t = fire("long", 100, 95, 110, {o: 100, h: 111, l: 99, c: 110, t: "2026-08-20 10:05"});
check("long, target only", t.got_r, 2);
t = fire("long", 100, 95, 110, {o: 100, h: 101, l: 94, c: 95, t: "2026-08-20 10:05"});
check("long, stop only", t.got_r, -1);
t = fire("short", 100, 105, 90, {o: 100, h: 101, l: 89, c: 90, t: "2026-08-20 10:05"});
check("short, target only", t.got_r, 2);

console.log("\na gap through the stop costs more than 1R, as it does live");
t = fire("long", 100, 95, 110, {o: 90, h: 91, l: 88, c: 90, t: "2026-08-20 10:05"});
check("long, gapped stop fills at open", t.exit, 90);
check("long, gapped stop loses more than 1R", t.got_r, -2);

console.log("\nP&L uses the contract's point value, not the raw points");
check("NQ, 5 points on a win", t.pnl, -10 * 20);

console.log("\nneither level touched");
R.trades = [];
R.pos = {side: "long", entry: 100, stop: 95, target: 110, risk: 5, planned: 2,
         t: "2026-08-20 10:00", i: 0};
R.checkFills({o: 100, h: 105, l: 98, c: 103, t: "2026-08-20 10:05"});
check("still open", R.trades.length, 0);
check("position kept", R.pos ? 1 : 0, 1);

// --- browsing must never let you trade -----------------------------------
console.log("\nbrowsing refuses to trade, because the future is on screen");
R.pos = null; R.trades = [];
R.mode = "browse";
R.place("long");
check("no trade while browsing", R.pos ? 1 : 0, 0);

// --- a walk through a slice ----------------------------------------------
console.log("\nstepping through a slice after the cut");
R.mode = "replay";
R.B = chunk(flat(40, 100), 10);
R.ci = 10; R.right = 10;
R.pos = null; R.trades = [];
R.place("short");
check("a trade opens after the cut", R.pos ? 1 : 0, 1);
const entry = R.pos ? R.pos.entry : null;

// walk into a bar that reaches the target
R.B.l[15] = 55;                     // a deep low, well past a 2R short target
R.step(30);
check("the trade resolved", R.trades.length, 1);
if (R.trades[0]) {
  const done = R.trades[0];
  console.log(`  short ${entry} -> ${done.exit} by ${done.exit_type}, ` +
              `${done.got_r >= 0 ? "+" : ""}${done.got_r}R`);
  check("R agrees with points over risk", done.got_r,
        +(done.got_pts / done.risk_pts).toFixed(2));
  check("never beyond the planned target", done.got_r <= done.planned_rr + 0.001 ? 1 : 0, 1);
  check("the day is recorded", done.day === "2026-08-20" ? 1 : 0, 1);
}

// --- stepping stops at the end of the slice ------------------------------
console.log("\nstepping cannot run off the end of the data");
R.B = chunk(flat(12, 100), 5);
R.ci = 5; R.right = 5; R.pos = null; R.trades = [];
R.step(500);
check("stops at the last bar", R.ci, 11);

console.log(failed ? `\n${failed} check(s) failed` : "\nall checks passed");
process.exit(failed ? 1 : 0);
