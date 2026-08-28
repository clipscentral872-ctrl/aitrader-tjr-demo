"""Pull historical candles and cache them locally, one month per file.

Chunking by month matters more than it sounds. The first version cached a whole
multi-year range as a single file, so when the write failed at the very end the
entire download was lost. Per-month chunks mean an interrupted run resumes from
where it stopped, and any date range is just an assembly of chunks.
"""
import os, time, json
import urllib.request as u
import pandas as pd

CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache")
os.makedirs(CACHE, exist_ok=True)

BINANCE = "https://api.binance.com/api/v3/klines"
UA = {"User-Agent": "Mozilla/5.0"}
COLS = ["open", "high", "low", "close", "volume"]


def _get(url, tries=5):
    for i in range(tries):
        try:
            return json.loads(u.urlopen(u.Request(url, headers=UA), timeout=30).read())
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2 * (i + 1))


def _to_frame(rows):
    df = pd.DataFrame(rows, columns=[
        "open_time", "open", "high", "low", "close", "volume", "close_time",
        "qv", "trades", "tbb", "tbq", "ignore"])[["open_time"] + COLS]
    for c in COLS:
        df[c] = df[c].astype(float)
    df["time"] = pd.to_datetime(df["open_time"], unit="ms", utc=True)
    return df.drop(columns=["open_time"]).set_index("time").sort_index()


def _month(symbol, interval, year, month, quiet=True):
    """One calendar month, cached. Returns a DataFrame (possibly empty)."""
    path = os.path.join(CACHE, f"{symbol}_{interval}_{year}{month:02d}.parquet")
    if os.path.exists(path):
        return pd.read_parquet(path)

    start = pd.Timestamp(year=year, month=month, day=1, tz="UTC")
    end = start + pd.offsets.MonthBegin(1)
    now = pd.Timestamp.now("UTC")
    if start > now:
        return pd.DataFrame(columns=COLS)

    t0, t1 = int(start.timestamp() * 1000), int(end.timestamp() * 1000)
    rows, cursor = [], t0
    while cursor < t1:
        batch = _get(f"{BINANCE}?symbol={symbol}&interval={interval}"
                     f"&startTime={cursor}&endTime={t1}&limit=1000")
        if not batch:
            break
        rows.extend(batch)
        nxt = batch[-1][0] + 1
        if nxt <= cursor:
            break
        cursor = nxt
        time.sleep(0.05)

    df = _to_frame(rows) if rows else pd.DataFrame(columns=COLS)
    df = df[~df.index.duplicated(keep="first")]
    # only cache a month that is fully in the past, so the current month stays fresh
    if end < now:
        df.to_parquet(path)
    if not quiet:
        print(f"    {year}-{month:02d}: {len(df):,} bars", flush=True)
    return df


def binance(symbol="BTCUSDT", interval="1m", start="2021-01-01", end=None, quiet=False):
    """Assemble a date range from monthly chunks, downloading only what is missing."""
    s = pd.Timestamp(start, tz="UTC")
    e = pd.Timestamp(end, tz="UTC") if end else pd.Timestamp.now("UTC")
    parts, cur = [], pd.Timestamp(year=s.year, month=s.month, day=1, tz="UTC")
    while cur < e:
        parts.append(_month(symbol, interval, cur.year, cur.month, quiet))
        cur += pd.offsets.MonthBegin(1)
    if not parts:
        return pd.DataFrame(columns=COLS)
    df = pd.concat([p for p in parts if len(p)])
    df = df[~df.index.duplicated(keep="first")].sort_index()
    return df.loc[(df.index >= s) & (df.index < e)]


def yahoo(symbol="NQ=F", interval="5m", rng="60d", max_age=3600):
    """Shallow futures history. Free, but Yahoo caps intraday depth hard.

    `max_age` is the cache lifetime in seconds. The default of an hour suits
    research, where the same series is requested repeatedly and a stale copy is
    harmless. It is WRONG for live trading: the runner polls every sixty
    seconds and was handed the same cached frame for an hour, so it saw one new
    bar an hour and idled through the rest of the session. Live callers must
    pass a short max_age.
    """
    tag = f"yahoo_{symbol}_{interval}_{rng}".replace("=", "").replace("^", "")
    path = os.path.join(CACHE, tag + ".parquet")
    if max_age and os.path.exists(path) and (time.time() - os.path.getmtime(path)) < max_age:
        return pd.read_parquet(path)
    sym = symbol.replace("=", "%3D").replace("^", "%5E")
    j = _get(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}"
             f"?range={rng}&interval={interval}")
    r = j["chart"]["result"][0]
    q = r["indicators"]["quote"][0]
    df = pd.DataFrame({
        "time": pd.to_datetime(r["timestamp"], unit="s", utc=True),
        "open": q["open"], "high": q["high"], "low": q["low"],
        "close": q["close"], "volume": q["volume"],
    }).dropna().set_index("time").sort_index()
    df.to_parquet(path)
    return df


def resample(df, rule):
    """1m -> any higher timeframe, using the bar's own OHLC rules."""
    return df.resample(rule, label="left", closed="left").agg(
        {"open": "first", "high": "max", "low": "min",
         "close": "last", "volume": "sum"}).dropna()


if __name__ == "__main__":
    import sys
    start = sys.argv[1] if len(sys.argv) > 1 else "2022-01-01"
    print(f"fetching BTCUSDT 1m from {start} (monthly chunks) ...", flush=True)
    d = binance("BTCUSDT", "1m", start, quiet=False)
    print(f"  {len(d):,} bars   {d.index[0]:%Y-%m-%d} -> {d.index[-1]:%Y-%m-%d}")
