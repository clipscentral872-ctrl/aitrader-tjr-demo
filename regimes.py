"""Break results down by market condition instead of one blended average.

An average of +0.00R can hide a strategy that makes +0.20R in trending markets
and loses that back in quiet ones. That is a useful thing to know even when the
overall number is nothing, because it points at a filter rather than a rewrite.

The honest caveat, and it matters: slicing results into buckets is running more
hypotheses. Twelve buckets means twelve chances for one to look good by luck.
Every bucket reported here is charged to the hypothesis ledger, and a bucket is
only called interesting if it clears the bar AFTER that correction. Most will
not, and that is the correct outcome.

    python regimes.py --market qqq
"""
import argparse, dataclasses, os, sys
from collections import defaultdict
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backtest.engine import run as bt_run
from backtest.guard import assess, Ledger, expected_best_by_luck
from engine.strategy import find_setups
from live import Runner, ny_window
from evaluate import get_data


def label_regimes(df, atr_window=48, trend_window=200):
    """Tag every bar with the conditions in force at the time.

    Everything is computed from bars already closed. A regime label that peeks
    at the future would quietly leak the answer into the buckets.
    """
    h, l, c = df["high"], df["low"], df["close"]
    prev = c.shift(1)
    tr = pd.concat([h - l, (h - prev).abs(), (l - prev).abs()], axis=1).max(axis=1)
    atr = tr.rolling(atr_window).mean()
    atr_pct = (atr / c) * 100

    # thresholds from the trailing distribution, not the whole sample
    lo = atr_pct.rolling(2000, min_periods=300).quantile(0.33)
    hi = atr_pct.rolling(2000, min_periods=300).quantile(0.67)
    vol = pd.Series("mid", index=df.index)
    vol[atr_pct <= lo] = "quiet"
    vol[atr_pct >= hi] = "volatile"

    ma = c.rolling(trend_window).mean()
    slope = ma.diff(trend_window // 4) / c
    trend = pd.Series("flat", index=df.index)
    trend[slope > 0.002] = "up"
    trend[slope < -0.002] = "down"

    hour = pd.Series(df.index.hour, index=df.index)
    dow = pd.Series(df.index.dayofweek, index=df.index)

    return pd.DataFrame({"vol": vol, "trend": trend, "hour": hour, "dow": dow,
                         "atr_pct": atr_pct})


def bucket(trades, regimes, key):
    out = defaultdict(list)
    for t in trades:
        ts = getattr(t, "opened_at", None) or getattr(t, "entry_time", None)
        if ts is None:
            continue
        try:
            row = regimes.loc[regimes.index.asof(ts)]
        except Exception:
            continue
        v = row[key]
        if pd.isna(v):
            continue
        out[v].append(t.r)
    return out


def show(name, groups, led, dataset, min_n=25):
    print(f"\n  by {name}")
    print(f"    {'bucket':<12} {'trades':>7} {'mean R':>9} {'win %':>7}   verdict")
    rows = sorted(groups.items(), key=lambda kv: str(kv[0]))
    interesting = []
    for k, rs in rows:
        if not rs:
            continue
        a = np.array(rs)
        wr = (a > 0).mean() * 100
        if len(a) < min_n:
            verdict = f"too few to read"
        else:
            v = assess(list(a), dataset=dataset, label=f"{name}={k}", ledger=led)
            verdict = "clears the bar" if v.is_edge else "inside its own noise"
            if v.is_edge:
                interesting.append((k, float(a.mean()), len(a)))
        print(f"    {str(k):<12} {len(a):>7} {a.mean():>+9.3f} {wr:>7.1f}   {verdict}")
    return interesting


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="qqq")
    ap.add_argument("--reset-ledger", action="store_true")
    a = ap.parse_args()

    df, costs, ms, hours = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return

    led = Ledger()
    if a.reset_ledger:
        led.reset()

    cfg = dataclasses.replace(Runner._tuned(), min_stop_pct=ms)
    setups = find_setups(df, cfg, session_filter=ny_window)
    trades, _ = bt_run(df, setups, costs)
    if not trades:
        print("no trades to break down")
        return

    r = np.array([t.r for t in trades])
    print("=" * 68)
    print(f"  REGIME BREAKDOWN  {a.market.upper()}   {len(trades)} trades   "
          f"overall {r.mean():+.3f}R")
    print("=" * 68)

    reg = label_regimes(df)
    found = []
    for key, label in (("vol", "volatility"), ("trend", "trend direction"),
                       ("hour", "hour of day"), ("dow", "day of week")):
        found += show(label, bucket(trades, reg, key), led, a.market)

    print("\n" + "=" * 68)
    if not found:
        print("  Nothing survives once every bucket is charged for being tested.")
        print("  That is the expected result on a strategy with no overall edge:")
        print("  slicing a zero finds pieces that look positive, and they are noise.")
    else:
        sd = float(r.std(ddof=1))
        k = led.count(a.market)
        luck = expected_best_by_luck(k, sd, max(len(r) // 6, 20))
        print(f"  {len(found)} bucket(s) cleared the corrected bar:")
        for name, m, n in found:
            tag = "still below what luck produces" if m < luck else "worth a closer look"
            print(f"    {name}: {m:+.3f}R on {n} trades   ({tag})")
        print(f"\n  best-by-luck across {k} tested slices is {luck:+.3f}R.")
        print("  A bucket only means something if it beats that AND repeats on")
        print("  data it was not found in. Re-test before believing it.")
    print("=" * 68)


if __name__ == "__main__":
    main()
