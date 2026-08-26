"""Does TIME OF DAY matter, as Phase 7 and TJR both insist?

This is the biggest untested claim in the whole method. Phase 7 says the best
moves cluster at predictable hours because liquidity does, and TJR builds his
whole model around the New York open. I said that half would not transfer to
crypto, which trades 24/7 with different participants.

This measures it rather than assuming either way. If the effect is real it will
show up as certain hours being clearly better across BOTH halves of the data.
If it only shows in one half, it is noise.
"""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.fetch import binance, resample
from engine.strategy import find_setups, Config
from backtest.engine import run, Costs


def by_hour(df, cfg=None, label=""):
    setups = find_setups(df, cfg or Config())
    trades, _ = run(df, setups, Costs())
    if not trades:
        print(f"  {label}: no trades"); return None
    d = pd.DataFrame({
        "hour_utc": [t.entry_time.hour for t in trades],
        "r": [t.r for t in trades],
    })
    g = d.groupby("hour_utc")["r"].agg(["count", "mean"])
    g["win%"] = d.groupby("hour_utc")["r"].apply(lambda x: 100 * (x > 0).mean())
    return g


def show(g, label):
    print(f"\n  {label}")
    print(f"  {'UTC':>4} {'SAST':>5} {'NY':>4} {'n':>5} {'win%':>7} {'expR':>8}")
    for hr, row in g.iterrows():
        if row["count"] < 5:
            continue
        sast = (hr + 2) % 24
        ny = (hr - 4) % 24
        mark = ""
        if 13 <= hr <= 15:
            mark = "  <- NY open"
        elif 7 <= hr <= 9:
            mark = "  <- London open"
        print(f"  {hr:>4} {sast:>5} {ny:>4} {int(row['count']):>5} "
              f"{row['win%']:>6.1f}% {row['mean']:>+8.3f}{mark}")


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "5min"
    raw = binance("BTCUSDT", "1m", "2022-01-01", quiet=True)
    df = resample(raw, tf)
    cut = int(len(df) * 0.6)
    train, test = df.iloc[:cut], df.iloc[cut:]
    print(f"loaded {len(df):,} {tf} bars")

    gtr = by_hour(train, label="train")
    gte = by_hour(test, label="test")
    if gtr is None or gte is None:
        return
    show(gtr, "TRAIN  2022-01 -> 2024-10")
    show(gte, "TEST   2024-10 -> 2026-08")

    # the honest test: do the hours that were good on train stay good on test?
    both = gtr[["count", "mean"]].join(gte[["count", "mean"]],
                                       lsuffix="_tr", rsuffix="_te").dropna()
    both = both[(both["count_tr"] >= 8) & (both["count_te"] >= 5)]
    if len(both) < 5:
        print("\n  too few hours with enough trades to compare")
        return
    corr = both["mean_tr"].corr(both["mean_te"])
    print(f"\n  correlation between train and test hourly expectancy: {corr:+.2f}")
    print(f"  ({len(both)} hours compared)")
    if corr > 0.4:
        print("  A real time-of-day effect. The good hours stayed good.")
    elif corr > 0.1:
        print("  Weak, possibly real. Not enough to build on alone.")
    else:
        print("  NO time-of-day effect that survives. Hours that looked good on")
        print("  train did not stay good on test - that is what noise looks like.")

    best = both.sort_values("mean_tr", ascending=False).head(4)
    print(f"\n  best 4 hours on TRAIN, and what they did on TEST:")
    for hr, row in best.iterrows():
        print(f"    {int(hr):02d}:00 UTC ({(hr+2)%24:02d}:00 SAST)   "
              f"train {row['mean_tr']:+.3f}R   test {row['mean_te']:+.3f}R")


if __name__ == "__main__":
    main()
