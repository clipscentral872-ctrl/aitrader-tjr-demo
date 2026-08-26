"""Dukascopy tick data - an independent check on the HistData forex result.

Why this source: Dukascopy is a Swiss bank publishing its own feed. It is free,
needs no account, and crucially it has NO relationship to HistData. After the
HistData index feed turned out to manufacture the exact pattern this strategy
hunts for, "independent" is the only property that matters.

Format, per hour, per instrument:
    https://datafeed.dukascopy.com/datafeed/{SYM}/{YYYY}/{MM-1:02}/{DD:02}/{HH:02}h_ticks.bi5

The month is ZERO-INDEXED, which is a classic way to silently fetch the wrong
month. The payload is raw LZMA holding 20-byte records:
    uint32be  milliseconds since the hour
    uint32be  ask, in points
    uint32be  bid, in points
    float32be ask volume
    float32be bid volume

    python data/dukascopy_pull.py --test
    python data/dukascopy_pull.py --pull --start 2024-01-01 --end 2026-01-01
"""
import argparse, io, lzma, os, struct, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
import urllib.request as u
import datetime as dt
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = os.path.join(ROOT, "data", "store")
CACHE = os.path.join(HERE, "cache", "duka")
os.makedirs(STORE, exist_ok=True)
os.makedirs(CACHE, exist_ok=True)

BASE = "https://datafeed.dukascopy.com/datafeed"
UA = {"User-Agent": "Mozilla/5.0"}
POINT = {"EURUSD": 1e-5, "GBPUSD": 1e-5, "USDJPY": 1e-3}


def hour_url(sym, d, h):
    return f"{BASE}/{sym}/{d.year}/{d.month - 1:02d}/{d.day:02d}/{h:02d}h_ticks.bi5"


def fetch_hour(sym, d, h, retries=2):
    """Return a DataFrame of ticks for one hour, or None if there are none."""
    try:
        raw = u.urlopen(u.Request(hour_url(sym, d, h), headers=UA), timeout=25).read()
    except Exception:
        if retries:
            time.sleep(1.0)
            return fetch_hour(sym, d, h, retries - 1)
        return None
    if not raw:
        return None
    try:
        dec = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        data = dec.decompress(raw)
    except Exception:
        return None
    n = len(data) // 20
    if n == 0:
        return None

    pt = POINT.get(sym, 1e-5)
    base = dt.datetime(d.year, d.month, d.day, h, tzinfo=dt.timezone.utc)
    recs = struct.unpack(">" + "IIIff" * n, data[:n * 20])
    ms = recs[0::5]
    ask = recs[1::5]
    bid = recs[2::5]
    df = pd.DataFrame({
        "time": [base + dt.timedelta(milliseconds=m) for m in ms],
        # mid price: the strategy works on structure, and using mid avoids
        # baking one side of the spread into every high and low
        "price": [(a + b) / 2 * pt for a, b in zip(ask, bid)],
    })
    return df.set_index("time")


def to_bars(ticks, rule="5min"):
    o = ticks["price"].resample(rule).ohlc().dropna()
    o["volume"] = ticks["price"].resample(rule).count()
    return o


def pull(sym, start, end, rule="5min", workers=32, quiet=False):
    """Fetch a date range. The hourly files are independent, so they are pulled
    concurrently - sequentially this is 12,000 round trips and over an hour."""
    cache_file = os.path.join(CACHE, f"{sym}_{start}_{end}_{rule}.parquet")
    if os.path.exists(cache_file):
        return pd.read_parquet(cache_file)

    d0 = dt.date.fromisoformat(start)
    d1 = dt.date.fromisoformat(end)
    jobs, day = [], d0
    while day < d1:
        if day.weekday() < 5:            # Dukascopy has no weekend ticks
            jobs.extend((day, h) for h in range(24))
        day += dt.timedelta(days=1)

    frames, done = [], 0
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futs = {ex.submit(fetch_hour, sym, d, h): (d, h) for d, h in jobs}
        for f in as_completed(futs):
            done += 1
            try:
                t = f.result()
            except Exception:
                t = None
            if t is not None and len(t):
                frames.append(t)
            if not quiet and done % 1000 == 0:
                got = sum(len(x) for x in frames)
                print(f"    {done:,}/{len(jobs):,} hours   {got:,} ticks", flush=True)

    if not frames:
        return pd.DataFrame()
    ticks = pd.concat(frames).sort_index()
    ticks = ticks[~ticks.index.duplicated(keep="first")]
    bars = to_bars(ticks, rule)
    bars.index.name = "time"
    bars.to_parquet(cache_file)
    return bars


def load(sym="eurusd"):
    p = os.path.join(STORE, f"{sym.lower()}_5m_duka.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--test", action="store_true")
    ap.add_argument("--pull", action="store_true")
    ap.add_argument("--symbol", default="EURUSD")
    ap.add_argument("--start", default="2024-01-01")
    ap.add_argument("--end", default="2026-01-01")
    a = ap.parse_args()

    if a.test:
        d = dt.date(2024, 3, 5)
        t = fetch_hour(a.symbol, d, 14)
        if t is None or t.empty:
            print("no ticks returned - check the symbol or the date")
        else:
            print(f"{len(t):,} ticks for {a.symbol} on {d} 14:00 UTC")
            print(f"  price range {t['price'].min():.5f} - {t['price'].max():.5f}")
            b = to_bars(t)
            print(f"  -> {len(b)} five-minute bars")
            print(b.head(3).to_string())
    else:
        print(f"pulling {a.symbol} {a.start} -> {a.end}", flush=True)
        bars = pull(a.symbol, a.start, a.end)
        if bars.empty:
            print("  nothing returned")
        else:
            p = os.path.join(STORE, f"{a.symbol.lower()}_5m_duka.parquet")
            if os.path.exists(p):
                bars = pd.concat([pd.read_parquet(p), bars])
                bars = bars[~bars.index.duplicated(keep="last")].sort_index()
            bars.to_parquet(p)
            print(f"  {len(bars):,} bars  {bars.index[0]:%Y-%m-%d} -> "
                  f"{bars.index[-1]:%Y-%m-%d}  ->  {os.path.basename(p)}")
