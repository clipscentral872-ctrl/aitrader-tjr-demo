"""Pack the historical bars the replay page needs into one embedded payload.

Why embedded rather than fetched: the page is opened from disk, and browsers
refuse fetch() against file:// URLs. Everything the replay can show therefore
has to travel inside the HTML.

What is available, and it is worth knowing before you plan a session:
  5 minute   NQ and ES back to June, from the store the backtests use
  1 minute   only the last few days, because that is all Yahoo keeps free

Sessions are cut on New York dates so a session is the trading day you actually
sat through, not a UTC calendar day that splits the overnight in half.
"""
import functools
import io
import json
import os
import sys

print = functools.partial(print, flush=True)

import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
OUT = os.path.join(ROOT, "journal_data", "replay_bars.json")

NY = "America/New_York"

# where each symbol and timeframe comes from, best source first
SOURCES = {
    ("NQ", "5m"): ["data/store/nq_5m.parquet", "data/cache/yahoo_NQF_5m_60d.parquet"],
    ("ES", "5m"): ["data/store/es_5m.parquet", "data/cache/yahoo_ESF_5m_60d.parquet"],
    ("NQ", "1m"): ["data/cache/yahoo_NQF_1m_5d.parquet"],
    ("ES", "1m"): ["data/cache/yahoo_ESF_1m_5d.parquet"],
}
# a replay session runs from the Asia open through the New York close, which is
# the whole window TJR's method looks at
START_H, END_H = 18, 16


def load(paths):
    frames = []
    for p in paths:
        full = os.path.join(ROOT, p)
        if not os.path.exists(full):
            continue
        d = pd.read_parquet(full)
        d = d[[c for c in ("open", "high", "low", "close") if c in d.columns]]
        if len(d.columns) == 4:
            frames.append(d)
    if not frames:
        return None
    d = pd.concat(frames)
    d = d[~d.index.duplicated(keep="first")].sort_index()
    if d.index.tz is None:
        d.index = d.index.tz_localize("UTC")
    return d.tz_convert(NY)


def sessions(d, tf):
    """Split into trading days, each running 18:00 the evening before to 16:00."""
    out = {}
    if d is None or d.empty:
        return out
    # a bar at or after 18:00 belongs to the NEXT trading day
    day = d.index.normalize()
    roll = day + pd.Timedelta(days=1)
    owner = pd.Series(day, index=d.index)
    owner[d.index.hour >= START_H] = roll[d.index.hour >= START_H]

    for date, chunk in d.groupby(owner.dt.date):
        chunk = chunk[chunk.index.hour < END_H + 1]
        if len(chunk) < 20:
            continue
        out[str(date)] = {
            "t": [ts.strftime("%H:%M") for ts in chunk.index],
            "o": [round(float(v), 2) for v in chunk["open"]],
            "h": [round(float(v), 2) for v in chunk["high"]],
            "l": [round(float(v), 2) for v in chunk["low"]],
            "c": [round(float(v), 2) for v in chunk["close"]],
        }
    return out


def main():
    payload = {"tick": {"NQ": 0.25, "ES": 0.25},
               "point": {"NQ": 20.0, "ES": 50.0},
               "sessions": {}}
    for (sym, tf), paths in SOURCES.items():
        d = load(paths)
        if d is None:
            print(f"  {sym} {tf}: no source found")
            continue
        s = sessions(d, tf)
        payload["sessions"].setdefault(sym, {})[tf] = s
        if s:
            days = sorted(s)
            bars = sum(len(v["t"]) for v in s.values())
            print(f"  {sym} {tf}: {len(s)} sessions, {bars} bars, "
                  f"{days[0]} to {days[-1]}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(payload, io.open(OUT, "w", encoding="utf-8"), separators=(",", ":"))
    mb = os.path.getsize(OUT) / 1048576
    print(f"\n{OUT}  ({mb:.1f} MB)")


if __name__ == "__main__":
    main()
