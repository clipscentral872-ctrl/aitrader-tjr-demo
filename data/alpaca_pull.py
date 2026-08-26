"""Alpaca: years of free US equity bars, and a real paper-trading account.

Why this matters more than another data source:

  * FREE, and unlike Databento it needs NO CARD to claim
  * years of 5-minute history on QQQ / SPY / IWM, which is what settles the
    cash-session question that 16 trades could not
  * a genuine paper-trading API, so the system can trade a real broker account
    instead of my simulated one

Free accounts get the IEX feed. That is a single exchange rather than the full
consolidated tape, so volume is a fraction of the real figure and the odd bar
will be thin. For testing STRUCTURE - highs, lows, gaps, sweeps - it is fine,
and it is honest to note the limitation rather than pretend otherwise.

    python data/alpaca_pull.py --test              # check the keys work
    python data/alpaca_pull.py --pull              # download and store
    python data/alpaca_pull.py --pull --start 2016-01-01
"""
import argparse, json, os, sys, time
import urllib.request as u
import urllib.parse as up
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = os.path.join(ROOT, "data", "store")
KEYFILE = os.path.join(ROOT, "config", "alpaca.key")
os.makedirs(STORE, exist_ok=True)

DATA = "https://data.alpaca.markets/v2/stocks/{sym}/bars"
PAPER = "https://paper-api.alpaca.markets/v2/account"

# the cash-session instruments the ETF test could not settle on 16 trades
SYMBOLS = ["QQQ", "SPY", "IWM", "DIA"]


def keys():
    """Read key_id / secret from the key file or the environment."""
    kid = os.environ.get("ALPACA_KEY_ID")
    sec = os.environ.get("ALPACA_SECRET")
    if kid and sec:
        return kid.strip(), sec.strip()
    if os.path.exists(KEYFILE):
        d = {}
        for line in open(KEYFILE, encoding="utf-8"):
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            d[k.strip().lower()] = v.strip()
        kid = d.get("key_id") or d.get("api_key_id") or d.get("key")
        sec = d.get("secret") or d.get("secret_key")
        if kid and sec:
            return kid, sec
    return None, None


def _req(url):
    kid, sec = keys()
    if not kid:
        return None
    r = u.Request(url, headers={
        "APCA-API-KEY-ID": kid,
        "APCA-API-SECRET-KEY": sec,
        "User-Agent": "AITrader/1.0",
    })
    return json.loads(u.urlopen(r, timeout=40).read())


def test():
    kid, sec = keys()
    if not kid:
        print("No Alpaca keys found.")
        print(f"  Create {KEYFILE} containing:")
        print("     key_id=YOUR_KEY_ID")
        print("     secret=YOUR_SECRET_KEY")
        print("  (or set ALPACA_KEY_ID and ALPACA_SECRET)")
        return False
    print(f"key id: {kid[:6]}...{kid[-4:]}")
    try:
        a = _req(PAPER)
        print(f"  paper account OK")
        print(f"    status        {a.get('status')}")
        print(f"    buying power  ${float(a.get('buying_power', 0)):,.0f}")
        print(f"    equity        ${float(a.get('equity', 0)):,.0f}")
    except Exception as e:
        print(f"  paper account FAILED: {type(e).__name__}: {str(e)[:80]}")
        return False
    try:
        q = up.urlencode({"timeframe": "5Min", "limit": 5,
                          "start": "2024-01-02T14:30:00Z", "feed": "iex"})
        b = _req(DATA.format(sym="QQQ") + "?" + q)
        n = len(b.get("bars") or [])
        print(f"  historical data OK, {n} sample bars returned")
        if n:
            print(f"    first: {b['bars'][0]['t']}  close {b['bars'][0]['c']}")
    except Exception as e:
        print(f"  historical data FAILED: {type(e).__name__}: {str(e)[:80]}")
        return False
    return True


def pull(symbols, start, end=None, timeframe="5Min", feed="iex"):
    end = end or (pd.Timestamp.now("UTC") - pd.Timedelta(minutes=20)).strftime("%Y-%m-%dT%H:%M:%SZ")
    if len(start) == 10:
        start += "T00:00:00Z"
    for sym in symbols:
        print(f"downloading {sym} ...", flush=True)
        rows, page, calls = [], None, 0
        while True:
            q = {"timeframe": timeframe, "start": start, "end": end,
                 "limit": 10000, "feed": feed, "adjustment": "all"}
            if page:
                q["page_token"] = page
            try:
                d = _req(DATA.format(sym=sym) + "?" + up.urlencode(q))
            except Exception as e:
                print(f"  failed: {type(e).__name__}: {str(e)[:90]}")
                break
            bars = d.get("bars") or []
            rows.extend(bars)
            page = d.get("next_page_token")
            calls += 1
            if calls % 10 == 0:
                print(f"    {len(rows):,} bars ...", flush=True)
            if not page:
                break
            time.sleep(0.25)          # stay inside the free rate limit

        if not rows:
            print("  nothing returned")
            continue
        df = pd.DataFrame(rows)
        df = df.rename(columns={"o": "open", "h": "high", "l": "low",
                                "c": "close", "v": "volume", "t": "time"})
        df["time"] = pd.to_datetime(df["time"], utc=True)
        df = df.set_index("time")[["open", "high", "low", "close", "volume"]]
        df = df[~df.index.duplicated(keep="first")].sort_index()

        path = os.path.join(STORE, f"{sym.lower()}_5m.parquet")
        if os.path.exists(path):
            df = pd.concat([pd.read_parquet(path), df])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        df.to_parquet(path)
        yrs = (df.index[-1] - df.index[0]).days / 365
        print(f"  {len(df):,} bars  {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}"
              f"  ({yrs:.1f} years)  ->  {os.path.basename(path)}")



def latest(sym="QQQ", minutes=1200, timeframe="5Min", feed="iex"):
    """The most recent bars, for live decisions.

    The free IEX feed is delayed by fifteen minutes and covers only IEX volume,
    so a live result here proves the plumbing works, not that the edge is real.
    That distinction is worth keeping in view.
    """
    start = (pd.Timestamp.now("UTC") - pd.Timedelta(minutes=minutes)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = up.urlencode({"timeframe": timeframe, "limit": 10000,
                      "start": start, "feed": feed, "adjustment": "raw"})
    try:
        b = _req(DATA.format(sym=sym.upper()) + "?" + q)
    except Exception:
        return pd.DataFrame()
    rows = b.get("bars") or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], utc=True).dt.tz_convert("America/New_York")
    df = df.set_index("t").rename(columns={"o": "open", "h": "high", "l": "low",
                                           "c": "close", "v": "volume"})
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def load(sym="qqq"):
    p = os.path.join(STORE, f"{sym.lower()}_5m.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--start", default="2018-01-01")
    ap.add_argument("--symbols", default=",".join(SYMBOLS))
    a = ap.parse_args()

    if a.pull:
        if not test():
            sys.exit(1)
        print()
        pull([s.strip().upper() for s in a.symbols.split(",") if s.strip()], a.start)
    else:
        test()
