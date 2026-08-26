"""What changed around 2023, and is it the market or is it us?

The strategy is positive on the first 60% of history and negative on the last
40%, on EURUSD and on QQQ, with the filter on or off. That is a structural
break, and it is the most interesting thing left to explain.

There are four candidate explanations and they have different fingerprints:

  1. THE DATA CHANGED     a vendor switch, a feed change, a different
                          contributor mix. Fingerprint: bar statistics move but
                          the second vendor does not agree.

  2. THE MARKET CHANGED   volatility, trend persistence, the character of what
                          happens after a sweep. Fingerprint: the same break
                          shows up on unrelated markets at the same time.

  3. THE EDGE DECAYED     the pattern got arbitraged away. Fingerprint: a
                          gradual fade rather than a step, concentrated in the
                          specific behaviour the strategy bets on.

  4. NOTHING CHANGED      it was never real, and the first half was the lucky
                          half. Fingerprint: the break is not shared across
                          markets and the yearly swings are as large as the
                          effect.

The fourth is the null hypothesis and the most likely, so the test has to be
capable of returning it.

The mechanistic question underneath all of this: the strategy bets that a
liquidity sweep is followed by CONTINUATION in the swept direction. If markets
became more likely to simply carry on through a swept level instead of
reversing, the bet stops paying regardless of any parameter.

    python regime_break.py --market eurusd
"""
import argparse, dataclasses, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from engine import structure as S
from backtest.engine import run as bt_run
from evaluate import get_data
from tjr_study import SESSIONS


def bar_stats_by_year(df):
    """Has the data itself changed shape?"""
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    rng = h - l
    body = np.abs(c - o)
    wick = np.clip(rng - body, 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        wr = np.where(rng > 0, wick / rng, np.nan)
    ret = np.zeros(len(c))
    ret[1:] = np.diff(c) / c[:-1]

    out = {}
    for y, idx in pd.Series(range(len(df)), index=df.index).groupby(df.index.year):
        i = idx.to_numpy()
        if len(i) < 500:
            continue
        r = ret[i]
        out[y] = {
            "bars": len(i),
            "wick": float(np.nanmean(wr[i])),
            "range_pct": float(np.nanmean(rng[i] / c[i]) * 100),
            # autocorrelation of returns: positive means trends persist,
            # negative means moves get faded
            "autocorr": float(np.corrcoef(r[:-1], r[1:])[0, 1]) if len(r) > 100 else np.nan,
        }
    return out


def sweep_outcome_by_year(df, cfg, lookahead=24):
    """The mechanism itself, measured without any strategy attached.

    After price sweeps a recent swing high, does it CONTINUE up or REVERSE
    down? The strategy bets on reversal. This counts what actually happened,
    with no entry rules, no filters and no costs in the way.
    """
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    sw = S.find_swings(h, l, cfg.swing_left, cfg.swing_right)

    rows = []
    n = len(df)
    for i in range(100, n - lookahead):
        known = S.known_tail(sw, i, 12)
        highs = [x for x in known if x.kind == "high"]
        lows = [x for x in known if x.kind == "low"]
        if highs and h[i] > highs[-1].price >= h[i - 1]:
            fwd = c[i + lookahead] - c[i]
            rows.append((df.index[i].year, "high", -fwd / c[i] * 100))
        elif lows and l[i] < lows[-1].price <= l[i - 1]:
            fwd = c[i + lookahead] - c[i]
            rows.append((df.index[i].year, "low", fwd / c[i] * 100))
    if not rows:
        return {}
    d = pd.DataFrame(rows, columns=["year", "kind", "reversal_pct"])
    out = {}
    for y, g in d.groupby("year"):
        if len(g) < 100:
            continue
        out[y] = {"sweeps": len(g),
                  "reverted_pct": float((g.reversal_pct > 0).mean() * 100),
                  "mean_move": float(g.reversal_pct.mean())}
    return out


def strategy_by_year(df, costs, cfg, filt):
    s = find_setups(df, cfg, session_filter=filt)
    if not s:
        return {}
    tr, _ = bt_run(df, s, costs)
    if not tr:
        return {}
    rows = [(t.entry_time.year, t.r, abs(t.entry - t.stop) / t.entry * 100,
             t.rr_planned, t.bars_held) for t in tr]
    d = pd.DataFrame(rows, columns=["year", "r", "stop_pct", "rr", "held"])
    out = {}
    for y, g in d.groupby("year"):
        if len(g) < 15:
            continue
        out[y] = {"trades": len(g), "mean_r": float(g.r.mean()),
                  "win": float((g.r > 0).mean() * 100),
                  "stop_pct": float(g.stop_pct.mean()),
                  "held": float(g.held.mean())}
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="eurusd")
    ap.add_argument("--session", default="engine default (09:30-12:30 NY)")
    ap.add_argument("--compare", default=None,
                    help="a second vendor for the SAME market, to separate a "
                         "data change from a market change")
    a = ap.parse_args()

    df, costs, ms, _ = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return
    filt = SESSIONS.get(a.session)
    cfg = Config(min_stop_pct=ms, max_stop_pct=1.5, min_rr=1.0, max_rr=5.0,
                 htf_bias=True, require_real_draw=True, require_premium=True)

    print("=" * 78)
    print(f"  WHAT CHANGED   {a.market.upper()}")
    print("=" * 78)

    strat = strategy_by_year(df, costs, cfg, filt)
    bars = bar_stats_by_year(df)
    print("\n1. THE STRATEGY, YEAR BY YEAR")
    print(f"   {'year':>6} {'trades':>7} {'mean R':>9} {'win %':>7} "
          f"{'stop %':>8} {'bars held':>10}")
    for y in sorted(strat):
        s = strat[y]
        print(f"   {y:>6} {s['trades']:>7} {s['mean_r']:>+9.3f} {s['win']:>7.1f} "
              f"{s['stop_pct']:>8.3f} {s['held']:>10.1f}")

    print("\n2. THE DATA ITSELF")
    print("   If these move at the break, the feed changed, not the market.")
    print(f"   {'year':>6} {'bars':>9} {'wick/range':>12} {'range %':>10} "
          f"{'autocorr':>10}")
    for y in sorted(bars):
        b = bars[y]
        print(f"   {y:>6} {b['bars']:>9,} {b['wick']:>12.3f} "
              f"{b['range_pct']:>10.4f} {b['autocorr']:>10.4f}")

    print("\n3. THE MECHANISM, WITH NO STRATEGY ATTACHED")
    print("   After a swing high is swept, does price reverse? The strategy")
    print("   bets it does. This just counts what happened.")
    sweeps = sweep_outcome_by_year(df, cfg)
    print(f"   {'year':>6} {'sweeps':>8} {'reversed %':>12} {'mean move %':>13}")
    for y in sorted(sweeps):
        s = sweeps[y]
        print(f"   {y:>6} {s['sweeps']:>8,} {s['reverted_pct']:>12.1f} "
              f"{s['mean_move']:>13.4f}")

    # ---- the split that started this --------------------------------------
    yrs = sorted(strat)
    if len(yrs) >= 4:
        mid = yrs[len(yrs) // 2]
        early = [strat[y]["mean_r"] for y in yrs if y < mid]
        late = [strat[y]["mean_r"] for y in yrs if y >= mid]
        se = [sweeps[y]["reverted_pct"] for y in sorted(sweeps) if y < mid]
        sl = [sweeps[y]["reverted_pct"] for y in sorted(sweeps) if y >= mid]
        print("\n" + "-" * 78)
        print(f"  BEFORE {mid} versus {mid} ONWARD")
        print(f"    strategy expectancy   {np.mean(early):+.3f}R  ->  "
              f"{np.mean(late):+.3f}R")
        if se and sl:
            print(f"    sweeps that reversed  {np.mean(se):.1f}%  ->  "
                  f"{np.mean(sl):.1f}%")
        yr_sd = float(np.std([strat[y]["mean_r"] for y in yrs], ddof=1))
        gap = abs(float(np.mean(early)) - float(np.mean(late)))
        print(f"\n    year-to-year spread is {yr_sd:.3f}R; the gap between")
        print(f"    halves is {gap:.3f}R.")
        if gap < yr_sd:
            print("    The gap is SMALLER than the ordinary year-to-year swing.")
            print("    That is not a regime change, that is noise with a")
            print("    convenient split point.")
        else:
            print("    The gap exceeds the usual yearly swing, so something")
            print("    may genuinely have shifted. Check whether the mechanism")
            print("    above moved with it before believing a story about it.")

    if a.compare:
        print("\n" + "-" * 78)
        print(f"  SAME MARKET, DIFFERENT VENDOR: {a.compare}")
        df2, c2, ms2, _ = get_data(a.compare)
        if df2 is not None and not df2.empty:
            b2 = bar_stats_by_year(df2)
            print(f"   {'year':>6} {'wick/range':>12} {'range %':>10}")
            for y in sorted(b2):
                print(f"   {y:>6} {b2[y]['wick']:>12.3f} "
                      f"{b2[y]['range_pct']:>10.4f}")
            print("\n   If this vendor shows the same shift, the market moved.")
            print("   If it does not, our feed changed and the break is ours.")

    print("\n" + "=" * 78)


if __name__ == "__main__":
    main()
