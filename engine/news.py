"""News gate, backed by the ForexFactory calendar.

Chris asked for two things: avoid trading around big releases, and ideally read
which way the news pushes the market. Those are very different problems.

  AVOIDING is reliable. A high-impact release at a known time produces a known
  hazard: spreads widen, stops get taken on noise, and the setup you were
  watching gets destroyed by something that has nothing to do with structure.
  Blocking a window around it is simple and it works.

  PREDICTING DIRECTION is not reliable. "Worse than forecast" does not map
  cleanly to a direction, because what moves price is the surprise relative to
  what was already priced in, and we cannot see that. This module therefore
  reports the surprise and leaves direction alone. If that changes later it will
  be because a measured test said so, not because it sounded plausible.

Free feed, no key: https://nfs.faireconomy.media/ff_calendar_thisweek.json
"""
import json, os, time
import urllib.request as u
import datetime as dt

CACHE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     "data", "cache")
os.makedirs(CACHE, exist_ok=True)
UA = {"User-Agent": "Mozilla/5.0"}

WEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
NEXT = "https://nfs.faireconomy.media/ff_calendar_nextweek.json"

# which calendar currencies matter for which instrument
RELEVANT = {
    "BTCUSDT": {"USD"},
    "ETHUSDT": {"USD"},
    "NQ": {"USD"},
    "MNQ": {"USD"},
    "ES": {"USD"},
    "EURUSD": {"USD", "EUR"},
    "GBPUSD": {"USD", "GBP"},
}


def _fetch(url, max_age=3600):
    path = os.path.join(CACHE, "ff_" + url.rsplit("/", 1)[-1])
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < max_age:
        return json.load(open(path, encoding="utf-8"))
    data = json.loads(u.urlopen(u.Request(url, headers=UA), timeout=25).read())
    json.dump(data, open(path, "w", encoding="utf-8"))
    return data


def calendar(include_next=True):
    """All events, normalised, with UTC timestamps."""
    out = []
    for url in ([WEEK, NEXT] if include_next else [WEEK]):
        try:
            raw = _fetch(url)
        except Exception:
            continue
        for e in raw:
            when = e.get("date")
            if not when:
                continue
            try:
                ts = dt.datetime.fromisoformat(when.replace("Z", "+00:00"))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=dt.timezone.utc)
            except ValueError:
                continue
            out.append({
                "time": ts.astimezone(dt.timezone.utc),
                "currency": e.get("country", ""),
                "title": e.get("title", ""),
                "impact": str(e.get("impact", "")).lower(),
                "forecast": e.get("forecast", ""),
                "previous": e.get("previous", ""),
                "actual": e.get("actual", ""),
            })
    return sorted(out, key=lambda x: x["time"])


def blocked(now, symbol="BTCUSDT", before_min=15, after_min=30, impacts=("high",)):
    """Is trading blocked right now? Returns (True, event) or (False, None).

    Default window: 15 minutes before a high-impact release through 30 after.
    Crypto is less news-sensitive than forex but USD releases still move it,
    which is why BTC maps to USD above.
    """
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.timezone.utc)
    want = RELEVANT.get(symbol.upper(), {"USD"})
    for e in calendar():
        if e["impact"] not in impacts or e["currency"] not in want:
            continue
        lo = e["time"] - dt.timedelta(minutes=before_min)
        hi = e["time"] + dt.timedelta(minutes=after_min)
        if lo <= now <= hi:
            return True, e
    return False, None


def upcoming(symbol="BTCUSDT", hours=24, impacts=("high", "medium")):
    """What is coming, so the dashboard can warn before the window closes."""
    now = dt.datetime.now(dt.timezone.utc)
    want = RELEVANT.get(symbol.upper(), {"USD"})
    return [e for e in calendar()
            if e["impact"] in impacts and e["currency"] in want
            and now <= e["time"] <= now + dt.timedelta(hours=hours)]


def surprise(event):
    """How far actual missed forecast, as a signed ratio. Reported, NOT traded.

    Returns None when the numbers cannot be parsed, which is often.
    """
    def num(x):
        if not x:
            return None
        s = str(x).strip().replace("%", "").replace("K", "e3").replace("M", "e6").replace("B", "e9")
        try:
            return float(s)
        except ValueError:
            return None
    a, f = num(event.get("actual")), num(event.get("forecast"))
    if a is None or f is None or f == 0:
        return None
    return (a - f) / abs(f)


if __name__ == "__main__":
    now = dt.datetime.now(dt.timezone.utc)
    ev = calendar()
    print(f"{len(ev)} events loaded")
    hi = [e for e in ev if e["impact"] == "high"]
    print(f"{len(hi)} high impact\n")
    b, e = blocked(now, "BTCUSDT")
    print(f"trading blocked right now: {b}" + (f"  ({e['title']})" if e else ""))
    print("\nnext 48h that would block BTC:")
    for e in upcoming("BTCUSDT", 48, ("high",)):
        sast = e["time"] + dt.timedelta(hours=2)
        print(f"  {sast:%a %d %b %H:%M} SAST  {e['currency']}  {e['title']}")
