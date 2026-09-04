"""One window for the three tools: Demo, Diary, Replay.

WHY THIS IS A SERVER AND NOT JUST A PAGE
----------------------------------------
Demo trading needs live prices, and a page opened from disk cannot fetch
anything: browsers refuse cross-origin requests from file:// URLs. So a small
local server sits in front, serves the three pages from one origin, and exposes
the few endpoints the demo tab needs. Nothing leaves the machine except the
price request that already ran when you built a chart.

The Diary and Replay tabs load the pages that already exist, untouched, in
frames. They are working pages and rewriting them into a single document would
have risked both to gain nothing.

    python app.py            then open http://127.0.0.1:8730
    python app.py --port N   if something already holds that port
"""
import argparse
import functools
import io
import json
import os
import subprocess
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

print = functools.partial(print, flush=True)

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
DATA = os.path.join(ROOT, "journal_data")
PAPER = os.path.join(DATA, "paper_state.json")

FEED = {"NQ": "NQ=F", "ES": "ES=F"}
POINT = {"NQ": 20.0, "ES": 50.0}

# Continuous history per timeframe, served in slices rather than embedded.
# An hourly chart only means anything across days and weeks, so the replay
# cannot be built out of single sessions: the hourly lows a setup is drawn to
# formed long before the day being traded.
# Sources in order of preference. The collected store is dense but young; the
# older stores are sparse but reach back years. Both are used, and where they
# overlap the collected bars win, so recent history is whole and the deep past
# is still there rather than being thrown away for being imperfect.
SERIES = {
    ("NQ", "1m"): ["data/collected/NQ_1m.parquet", "data/store/nasdaq_duka_1m.parquet"],
    ("NQ", "5m"): ["data/collected/NQ_5m.parquet", "data/store/nasdaq_duka_5m.parquet"],
    ("NQ", "1h"): ["data/collected/NQ_1h.parquet", "data/cache/yahoo_NQF_1h_730d.parquet"],
    ("NQ", "1d"): ["data/collected/NQ_1d.parquet",
                     "data/cache/yahoo_NQF_1d_2y.parquet"],
    ("ES", "1m"): ["data/collected/ES_1m.parquet", "data/store/sp500_duka_1m.parquet"],
    ("ES", "5m"): ["data/collected/ES_5m.parquet", "data/store/sp500_duka_5m.parquet"],
    ("ES", "1h"): ["data/collected/ES_1h.parquet", "data/cache/yahoo_ESF_1h_730d.parquet"],
    ("ES", "1d"): ["data/collected/ES_1d.parquet",
                     "data/cache/yahoo_ESF_1d_2y.parquet"],
}
# folded from the timeframe on the right, on clock boundaries
DERIVED = {"15m": ("5m", "15min"), "4h": ("1h", "4h")}
TF_ORDER = ["1m", "5m", "15m", "1h", "4h", "1d"]

_frames = {}


def series(sym, tf):
    """The continuous frame for a symbol and timeframe, loaded once."""
    import pandas as pd
    key = (sym, tf)
    if key in _frames:
        return _frames[key]

    if tf in DERIVED:
        base, rule = DERIVED[tf]
        src = series(sym, base)
        if src is None:
            _frames[key] = None
            return None
        d = src.resample(rule, label="left", closed="left").agg(
            {"open": "first", "high": "max", "low": "min", "close": "last"}).dropna()
    else:
        parts = []
        for rel in SERIES.get(key, []):
            full = os.path.join(ROOT, rel)
            if not os.path.exists(full):
                continue
            f = pd.read_parquet(full)[["open", "high", "low", "close"]].dropna()
            if f.index.tz is None:
                f.index = f.index.tz_localize("UTC")
            parts.append(f)
        if not parts:
            _frames[key] = None
            return None
        # concat in preference order, then drop later duplicates: the first
        # source to carry a timestamp is the one that keeps it
        d = pd.concat(parts)
        d = d[~d.index.duplicated(keep="first")].sort_index()
    _frames[key] = d
    return d


def _pack(sym, tf, d, cut_i=None):
    return {
        "sym": sym, "tf": tf, "cut": cut_i,
        "t": [ts.strftime("%Y-%m-%d %H:%M") for ts in d.index],
        "o": [round(float(v), 2) for v in d["open"]],
        "h": [round(float(v), 2) for v in d["high"]],
        "l": [round(float(v), 2) for v in d["low"]],
        "c": [round(float(v), 2) for v in d["close"]],
    }


def bars(sym, tf, end=None, n=400, after=0):
    """Bars around a moment.

    `end` is the playhead. `n` bars before it come back for the chart, and
    `after` more come back so the replay has something to step into without a
    round trip per bar. The page never draws past the playhead; the extra bars
    are a buffer, exactly as they are in any charting platform where the data
    is already in the browser.

    `cut` in the reply is the index of the playhead inside the returned arrays.
    """
    import pandas as pd
    d = series(sym, tf)
    if d is None or d.empty:
        return None

    cut_i = None
    if end:
        try:
            ts = pd.Timestamp(end)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            pos = int(d.index.searchsorted(ts, side="right")) - 1
            if pos < 0:
                pos = 0
            lo = max(0, pos - int(n) + 1)
            hi = min(len(d), pos + int(after) + 1)
            cut_i = pos - lo
            d = d.iloc[lo:hi]
            return _pack(sym, tf, d, cut_i)
        except (ValueError, TypeError):
            pass

    d = d.tail(max(1, min(int(n), 2000)))
    return _pack(sym, tf, d, len(d) - 1)


_levels = {}

# What each level is called on the chart, and the colour family it belongs to.
LEVEL_NAMES = [
    ("asia_h", "Asia High", "asia"), ("asia_l", "Asia Low", "asia"),
    ("london_h", "London High", "london"), ("london_l", "London Low", "london"),
    ("ny_h", "New York High", "ny"), ("ny_l", "New York Low", "ny"),
    ("pdh", "Prev Day High", "day"), ("pdl", "Prev Day Low", "day"),
]


def levels_at(sym, at=None):
    """The session highs and lows a trader would already know at that moment.

    Computed by the same `session_levels` the strategy uses, so the lines on the
    chart are the levels the system is actually reasoning about rather than a
    second, slightly different idea of where Asia ended.

    Each session only appears once it has CLOSED. A level you could not have
    known yet is not drawn, which is the whole point of replaying blind.
    """
    import numpy as np
    import pandas as pd
    from engine import structure as S

    d = series(sym, "5m")
    if d is None or d.empty:
        return None
    if sym not in _levels:
        _levels[sym] = S.session_levels(d.index, d["high"].values, d["low"].values)
    lv = _levels[sym]

    pos = len(d) - 1
    if at:
        try:
            ts = pd.Timestamp(at)
            if ts.tz is None:
                ts = ts.tz_localize("UTC")
            pos = max(0, int(d.index.searchsorted(ts, side="right")) - 1)
        except (ValueError, TypeError):
            pass

    out = []
    for key, label, family in LEVEL_NAMES:
        arr = lv.get(key)
        if arr is None or pos >= len(arr):
            continue
        v = arr[pos]
        if v is None or (isinstance(v, float) and np.isnan(v)):
            continue
        out.append({"key": key, "label": label, "family": family,
                    "price": round(float(v), 2)})
    return {"sym": sym, "at": str(d.index[pos]), "levels": out}


def load_paper():
    if os.path.exists(PAPER):
        try:
            return json.load(io.open(PAPER, encoding="utf-8"))
        except ValueError:
            pass
    return {"position": None, "trades": []}


def save_paper(st):
    json.dump(st, io.open(PAPER, "w", encoding="utf-8"), indent=1)


def quote(sym):
    """Latest price for a contract.

    Yahoo's futures quotes run roughly ten minutes behind, which is fine for
    practice but is stated on the page rather than hidden, because a delayed
    price that looks live is how you learn the wrong lesson about your fills.
    """
    from data.fetch import yahoo
    d = yahoo(FEED[sym], "1m", "1d", max_age=45)
    if d is None or d.empty:
        return None
    last = d.iloc[-1]
    return {"symbol": sym, "price": round(float(last["close"]), 2),
            "high": round(float(last["high"]), 2),
            "low": round(float(last["low"]), 2),
            "at": str(d.index[-1]), "point": POINT[sym]}


def demo_state():
    p = os.path.join(ROOT, "state", "demo_state.json")
    if not os.path.exists(p):
        return {"equity": None, "position": None, "trades": [], "polls": 0}
    return json.load(io.open(p, encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass                      # the console is for our own output

    def _send(self, code, body, ctype="application/json"):
        raw = body if isinstance(body, bytes) else body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def _file(self, name, ctype="text/html; charset=utf-8"):
        p = os.path.join(DATA, name)
        if not os.path.exists(p):
            self._send(404, f"<h1>{name} has not been built yet.</h1>",
                       "text/html; charset=utf-8")
            return
        self._send(200, io.open(p, "rb").read(), ctype)

    def do_GET(self):
        u = urlparse(self.path)
        path, q = u.path, parse_qs(u.query)

        if path in ("/", "/index.html"):
            self._send(200, SHELL, "text/html; charset=utf-8")
        elif path == "/journal.html":
            self._file("journal.html")
        elif path == "/replay.html":
            self._file("replay.html")
        elif path == "/demo.html":
            self._file("demo.html")
        elif path.startswith("/For Learning/"):
            rel = path[1:].replace("/", os.sep)
            p = os.path.join(ROOT, rel)
            if os.path.exists(p) and p.lower().endswith(".mp4"):
                self._send(200, io.open(p, "rb").read(), "video/mp4")
            else:
                self._send(404, "not found", "text/plain")
        elif path == "/api/quote":
            sym = (q.get("sym") or ["NQ"])[0].upper()
            if sym not in FEED:
                self._send(400, json.dumps({"error": "unknown symbol"}))
                return
            try:
                data = quote(sym)
            except Exception as e:
                self._send(502, json.dumps({"error": f"{type(e).__name__}"}))
                return
            self._send(200, json.dumps(data or {"error": "no data"}))
        elif path == "/api/bars":
            sym = (q.get("sym") or ["NQ"])[0].upper()
            tf = (q.get("tf") or ["5m"])[0]
            end = (q.get("end") or [None])[0]
            n = (q.get("n") or ["400"])[0]
            after = (q.get("after") or ["0"])[0]
            try:
                data = bars(sym, tf, end, int(n), int(after))
            except Exception as e:
                self._send(502, json.dumps({"error": type(e).__name__}))
                return
            self._send(200, json.dumps(data or {"error": "no data"}))
        elif path == "/api/levels":
            sym = (q.get("sym") or ["NQ"])[0].upper()
            at = (q.get("at") or [None])[0]
            try:
                data = levels_at(sym, at)
            except Exception as e:
                self._send(502, json.dumps({"error": type(e).__name__}))
                return
            self._send(200, json.dumps(data or {"error": "no data"}))
        elif path == "/api/tfs":
            sym = (q.get("sym") or ["NQ"])[0].upper()
            out = []
            for tf in TF_ORDER:
                d = series(sym, tf)
                if d is None or d.empty:
                    continue
                out.append({"tf": tf, "n": len(d),
                            "first": d.index[0].strftime("%Y-%m-%d"),
                            "last": d.index[-1].strftime("%Y-%m-%d")})
            self._send(200, json.dumps(out))
        elif path == "/api/paper":
            self._send(200, json.dumps(load_paper()))
        elif path == "/api/demo":
            self._send(200, json.dumps(demo_state()))
        else:
            self._send(404, "not found", "text/plain")

    def do_POST(self):
        u = urlparse(self.path)
        n = int(self.headers.get("Content-Length") or 0)

        # The import posts files, not JSON, so it is handled before the body is
        # parsed. Everything else on this server speaks JSON.
        if u.path == "/api/import":
            self._import(n)
            return

        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except ValueError:
            self._send(400, json.dumps({"error": "bad json"}))
            return

        if u.path == "/api/paper/open":
            st = load_paper()
            if st["position"]:
                self._send(409, json.dumps({"error": "already in a position"}))
                return
            st["position"] = body
            save_paper(st)
            self._send(200, json.dumps(st))
        elif u.path == "/api/paper/close":
            st = load_paper()
            if not st["position"]:
                self._send(409, json.dumps({"error": "flat"}))
                return
            st["trades"].append(body)
            st["position"] = None
            save_paper(st)
            self._send(200, json.dumps(st))
        elif u.path == "/api/paper/clear":
            save_paper({"position": None, "trades": []})
            self._send(200, json.dumps({"ok": True}))
        else:
            self._send(404, json.dumps({"error": "not found"}))

    # -----------------------------------------------------------------
    def _import(self, length):
        """Take the six exports the browser sent and run the whole pipeline.

        Saving the files rather than parsing them in memory is deliberate: the
        journal has always worked by accumulating exports in a folder, and
        keeping that true means a file dropped here and a file copied in by
        hand behave identically.
        """
        import cgi_lite
        try:
            parts = cgi_lite.parse_multipart(
                self.rfile, self.headers.get("Content-Type", ""), length)
        except Exception as e:
            self._send(400, json.dumps(
                {"error": f"could not read the upload ({type(e).__name__})"}))
            return

        saved, skipped = [], []
        for name, data in parts:
            base = os.path.basename(name.replace("\\", "/"))
            if not base.lower().endswith(".csv"):
                skipped.append(base)
                continue
            io.open(os.path.join(DATA, base), "wb").write(data)
            saved.append(base)

        if not saved:
            self._send(400, json.dumps(
                {"error": "None of those were CSV files. Export from "
                          "TradingView first, then drop what it gives you."}))
            return

        steps = [("reading your exports", "tradejournal.py"),
                 ("building the diary", "journal_render.py")]
        log = []
        for label, script in steps:
            r = subprocess.run([sys.executable, os.path.join(ROOT, script)],
                               cwd=ROOT, capture_output=True, text=True)
            log.append(r.stdout or "")
            if r.returncode:
                self._send(500, json.dumps(
                    {"error": f"{label} failed:\n"
                              + (r.stderr or r.stdout or "")[-600:]}))
                return

        text = "".join(log)
        added = 0
        for line in text.splitlines():
            if "new this run" in line:
                try:
                    added = int(line.split("(")[1].split()[0])
                except (IndexError, ValueError):
                    pass
        msg = [f"Read {len(saved)} file(s)."]
        msg.append(f"{added} new trade(s) added." if added
                   else "Nothing new. Those trades were already on record.")
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("DOES NOT MATCH") or line.startswith("matches the"):
                msg.append(line)
        if skipped:
            msg.append(f"Ignored: {', '.join(skipped)}.")
        self._send(200, json.dumps(
            {"message": "\n".join(msg), "added": added, "rebuilt": True}))


SHELL = r"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Traders Diary</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Orbitron:wght@600;800;900&family=Chakra+Petch:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500;700&display=swap">
<style>
:root{
  --ground:#05070C; --raised:#0A0F17; --lift:#111A26;
  --line:#1B2838; --text:#E8F0F8; --muted:#7E90A8; --faint:#4A5A70;
  --accent:#35E0F0;
}
*{box-sizing:border-box}
html,body{height:100%}
body{
  margin:0; background:var(--ground); color:var(--text);
  font-family:"Chakra Petch",system-ui,sans-serif;
  display:flex; flex-direction:column; overflow:hidden;
}
header{
  display:flex; align-items:center; gap:26px; padding:14px 24px;
  border-bottom:1px solid var(--line); background:var(--raised); flex:none;
}
.brand{
  font-family:"Orbitron",sans-serif; font-weight:900; font-size:19px;
  letter-spacing:.05em; text-transform:uppercase;
  background:linear-gradient(178deg,#FFFFFF 10%,#9DE9F6 92%);
  -webkit-background-clip:text; background-clip:text; color:transparent;
  filter:drop-shadow(0 0 16px rgba(53,224,240,.34));
}
nav{display:flex; gap:8px}
nav button{
  background:transparent; border:1px solid var(--line); color:var(--muted);
  font-family:"Orbitron",sans-serif; font-weight:700; font-size:11px;
  text-transform:uppercase; letter-spacing:.15em; padding:10px 20px;
  cursor:pointer; transition:border-color .14s,color .14s,background .14s,box-shadow .14s;
}
nav button:hover{border-color:var(--faint); color:var(--text)}
nav button[aria-selected="true"]{
  border-color:var(--accent); color:var(--text); background:var(--lift);
  box-shadow:0 0 22px rgba(53,224,240,.18);
}
nav button:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
.spacer{flex:1}
.hint{font-size:10.5px; color:var(--faint); text-transform:uppercase; letter-spacing:.13em}
main{flex:1; position:relative}
iframe{
  position:absolute; inset:0; width:100%; height:100%; border:0;
  background:var(--ground);
}
iframe[hidden]{display:none}
</style></head><body>
<header>
  <span class="brand">Traders Diary</span>
  <nav role="tablist">
    <button role="tab" data-tab="demo"    onclick="show('demo')">Demo</button>
    <button role="tab" data-tab="journal" onclick="show('journal')">Diary</button>
    <button role="tab" data-tab="replay"  onclick="show('replay')">Replay</button>
  </nav>
  <span class="spacer"></span>
  <span class="hint" id="hint">1 2 3 switch tabs</span>
</header>
<main>
  <iframe id="f-demo"    src="/demo.html"    title="Demo"></iframe>
  <iframe id="f-journal" src="/journal.html" title="Diary" hidden></iframe>
  <iframe id="f-replay"  src="/replay.html"  title="Replay" hidden></iframe>
</main>
<script>
const TABS = ["demo","journal","replay"];
function show(which){
  TABS.forEach(t => document.getElementById("f-"+t).hidden = (t !== which));
  document.querySelectorAll("nav button").forEach(b =>
    b.setAttribute("aria-selected", b.dataset.tab === which));
  location.hash = which;
}
document.addEventListener("keydown", e => {
  if(/^[123]$/.test(e.key) && !/^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName))
    show(TABS[+e.key - 1]);
});
show(TABS.includes(location.hash.slice(1)) ? location.hash.slice(1) : "demo");
</script>
</body></html>
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8730)
    ap.add_argument("--no-open", action="store_true")
    a = ap.parse_args()

    missing = [f for f in ("journal.html", "replay.html", "demo.html")
               if not os.path.exists(os.path.join(DATA, f))]
    if missing:
        print(f"  note: not built yet: {', '.join(missing)}")
        print("  run build_all.py to make them")

    url = f"http://127.0.0.1:{a.port}"
    srv = ThreadingHTTPServer(("127.0.0.1", a.port), Handler)
    print(f"\n  Traders Diary is running at {url}")
    print("  Demo, Diary and Replay are the three tabs.")
    print("  Ctrl+C here closes it.\n")
    if not a.no_open:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("  stopped")


if __name__ == "__main__":
    main()
