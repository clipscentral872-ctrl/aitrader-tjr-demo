"""Measure how stale the live feed actually is, rather than assuming.

Every live result is worth exactly as much as the feed behind it. A strategy
that enters on a liquidity sweep is deciding on an event measured in seconds; if
the bars arrive fifteen minutes late, the sweep it is reacting to is long over
and the entry price is fiction.

We had this written down as a caveat. A caveat nobody measures becomes a caveat
nobody believes, so this measures it and refuses to run when it is too stale.

    python data/freshness.py
    python data/freshness.py --symbol SPY --watch 5
"""
import argparse, os, sys, time
import datetime as dt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import pandas as pd


def measure(symbol="QQQ", feed="iex"):
    """Returns (age_seconds, last_bar_time, is_market_open) or None."""
    from data.alpaca_pull import latest, _req, PAPER
    try:
        clock = _req("https://paper-api.alpaca.markets/v2/clock")
        is_open = bool(clock.get("is_open"))
    except Exception:
        is_open = None

    # widen the window until something comes back. Over a weekend the last bar
    # can be three days old, which is not staleness, just a closed market.
    df = None
    for window in (600, 2000, 6000, 20000):
        df = latest(symbol, minutes=window, feed=feed)
        if df is not None and not df.empty:
            break
    if df is None or df.empty:
        return None
    last = df.index[-1]
    now = pd.Timestamp.now(tz=last.tz)
    # a five-minute bar stamped 14:30 covers 14:30 to 14:35, so it cannot exist
    # before 14:35. Age is measured from when the bar could first have been sent.
    age = (now - (last + pd.Timedelta(minutes=5))).total_seconds()
    return max(age, 0.0), last, is_open


def verdict(age, is_open):
    if is_open is False:
        return "market closed", "the age below is time since the close, not a delay"
    if age is None:
        return "unknown", "no bars came back"
    if age < 90:
        return "real time", "fast enough to act on a sweep as it happens"
    if age < 400:
        return "slightly behind", "acceptable for five-minute decisions"
    if age < 1200:
        return "DELAYED", ("the entry price is already history. Fills here are "
                           "fiction and results mean nothing")
    return "VERY STALE", "the feed is not usable for live decisions"


def check(symbol="QQQ", verbose=True):
    r = measure(symbol)
    if r is None:
        if verbose:
            print("  no data returned at all")
        return None
    age, last, is_open = r
    tag, note = verdict(age, is_open)
    if verbose:
        print(f"  {symbol}  last bar {last:%Y-%m-%d %H:%M %Z}")
        print(f"  age {age/60:.1f} minutes   market {'open' if is_open else 'closed'}")
        print(f"  {tag}: {note}")
    return {"age_sec": round(age, 1), "last_bar": str(last),
            "market_open": is_open, "verdict": tag}


def usable_for_live(symbol="QQQ", max_age_sec=400):
    """The gate. Live trading on a stale feed produces numbers that look like
    results and are not."""
    r = measure(symbol)
    if r is None:
        return False, "no data"
    age, last, is_open = r
    if is_open is False:
        return False, "market is closed"
    if age > max_age_sec:
        return False, f"feed is {age/60:.0f} minutes behind"
    return True, f"feed is {age:.0f}s behind"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="QQQ")
    ap.add_argument("--watch", type=int, default=0, help="repeat N times, a minute apart")
    a = ap.parse_args()
    print("=" * 60)
    print("  LIVE FEED FRESHNESS")
    print("=" * 60)
    for i in range(max(1, a.watch)):
        if i:
            time.sleep(60)
        check(a.symbol)
        print()
    print("  Alpaca's free tier serves IEX only. IEX is a small share of US")
    print("  volume, so even when it is fast it is not the whole market. A")
    print("  clean live result here still needs a paid consolidated feed to")
    print("  mean what it appears to mean.")
    print("=" * 60)


if __name__ == "__main__":
    main()
