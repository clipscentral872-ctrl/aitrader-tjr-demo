"""A proper managed-futures universe of daily bars, downloaded free.

Trend following's claim is diversification, and testing it on four markets was
never going to settle anything. Removing one of those four inverted the result,
which told us the basket was a single Bitcoin bet in disguise rather than
telling us anything about trend following.

The honest test needs breadth across asset classes that do not move together.
This is the standard managed-futures spread: equities, bonds, commodities,
currencies, property, crypto. Roughly twenty markets in six groups.

The signals here are daily, so daily bars are all that is needed, and daily
history is free and goes back decades. The intraday depth limits that made the
five-minute work so painful do not apply.

    python data/universe.py --pull
    python data/universe.py --list
"""
import argparse, json, os, time
import urllib.request as u
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STORE = os.path.join(ROOT, "data", "store", "universe")

# ticker -> (asset class, plain name)
UNIVERSE = {
    # equities, spread across regions so they are not one bet
    "SPY":  ("equity", "US large cap"),
    "QQQ":  ("equity", "US tech"),
    "IWM":  ("equity", "US small cap"),
    "EFA":  ("equity", "Developed ex-US"),
    "EEM":  ("equity", "Emerging markets"),
    # bonds, which is where trend following historically earns its keep
    "TLT":  ("bond", "US 20yr treasury"),
    "IEF":  ("bond", "US 7-10yr treasury"),
    "LQD":  ("bond", "Investment grade credit"),
    "HYG":  ("bond", "High yield credit"),
    # commodities
    "GLD":  ("commodity", "Gold"),
    "SLV":  ("commodity", "Silver"),
    "USO":  ("commodity", "Crude oil"),
    "DBA":  ("commodity", "Agriculture"),
    "DBC":  ("commodity", "Broad commodities"),
    # currencies
    "UUP":  ("fx", "US dollar index"),
    "FXE":  ("fx", "Euro"),
    "FXY":  ("fx", "Japanese yen"),
    "FXB":  ("fx", "British pound"),
    # property and crypto
    "VNQ":  ("property", "US real estate"),
    "BTC-USD": ("crypto", "Bitcoin"),
}


def _fetch(symbol, years=25):
    """Daily bars from Yahoo's chart endpoint. No key, no account."""
    end = int(time.time())
    start = end - int(years * 365.25 * 86400)
    sym = symbol.replace("=", "%3D").replace("^", "%5E")
    url = (f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
           f"?period1={start}&period2={end}&interval=1d")
    req = u.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    j = json.loads(u.urlopen(req, timeout=60).read())
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    # adjusted closes matter here: a dividend-paying ETF's raw price drifts
    # down over time, which a trend filter would read as a downtrend
    adj = r["indicators"].get("adjclose", [{}])[0].get("adjclose")
    df = pd.DataFrame({
        "time": pd.to_datetime(r["timestamp"], unit="s", utc=True),
        "open": q["open"], "high": q["high"], "low": q["low"],
        "close": adj if adj else q["close"],
        "raw_close": q["close"], "volume": q["volume"],
    }).dropna(subset=["close"]).set_index("time").sort_index()
    return df


def pull(force=False):
    os.makedirs(STORE, exist_ok=True)
    got, failed = [], []
    for sym, (cls, name) in UNIVERSE.items():
        path = os.path.join(STORE, f"{sym.replace('-', '_')}.parquet")
        if os.path.exists(path) and not force:
            df = pd.read_parquet(path)
            got.append((sym, cls, name, len(df), df.index[0], df.index[-1]))
            continue
        try:
            df = _fetch(sym)
            if len(df) < 500:
                failed.append((sym, f"only {len(df)} days"))
                continue
            df.to_parquet(path)
            got.append((sym, cls, name, len(df), df.index[0], df.index[-1]))
            print(f"  {sym:<9} {len(df):>6,} days  {df.index[0]:%Y-%m-%d} -> "
                  f"{df.index[-1]:%Y-%m-%d}   {name}", flush=True)
            time.sleep(0.4)
        except Exception as e:
            failed.append((sym, f"{type(e).__name__}: {str(e)[:60]}"))
            print(f"  {sym:<9} FAILED  {type(e).__name__}", flush=True)
    return got, failed


def load(symbol):
    path = os.path.join(STORE, f"{symbol.replace('-', '_')}.parquet")
    if not os.path.exists(path):
        return None
    return pd.read_parquet(path)


def load_all(min_days=1000):
    """Every market we managed to download, as a dict of close series."""
    out = {}
    for sym, (cls, name) in UNIVERSE.items():
        df = load(sym)
        if df is None or len(df) < min_days:
            continue
        out[sym] = df["close"]
    return out


def classes():
    return {s: c for s, (c, _) in UNIVERSE.items()}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--list", action="store_true")
    a = ap.parse_args()

    if a.pull or a.force:
        print(f"downloading {len(UNIVERSE)} markets of daily bars ...\n")
        got, failed = pull(force=a.force)
        print(f"\n  {len(got)} markets stored, {len(failed)} failed")
        for sym, why in failed:
            print(f"    {sym}: {why}")
    if a.list or not (a.pull or a.force):
        d = load_all()
        if not d:
            print("nothing stored yet. run with --pull")
            return
        print(f"\n{len(d)} markets available\n")
        cls = classes()
        by = {}
        for s, px in d.items():
            by.setdefault(cls[s], []).append((s, len(px), px.index[0]))
        for c in sorted(by):
            print(f"  {c}")
            for s, n, start in sorted(by[c]):
                print(f"    {s:<9} {n:>6,} days from {start:%Y-%m-%d}")


if __name__ == "__main__":
    main()
