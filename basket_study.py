"""Trend following across twenty markets, tested the way it is actually run.

The four-market version failed its own robustness check: removing Bitcoin
inverted the result, which meant the basket was one bet wearing a costume. Two
things were wrong with that test and both are fixed here.

FIRST, AND IT MATTERS MOST: equal DOLLAR weight is not equal risk. Bitcoin runs
at roughly 60% annualised volatility and bonds at 6%. Weighting them equally by
dollars gives Bitcoin ten times the influence on the portfolio, which is exactly
why removing it changed everything. Real managed futures scale every market to
the same volatility target so each contributes the same risk. That is not a
tweak, it is the difference between a diversified portfolio and a crypto fund
with decoration.

SECOND: four markets cannot test a diversification claim. This uses twenty,
across six asset classes, most with twenty-five years of history.

Trend following also goes short. Long-only cannot profit from a bond bear
market or a falling currency, and those are where the strategy historically
earns its diversification. Both are tested.

The check that killed the last version is run again here, market by market:
if dropping any single one changes the conclusion, it was never a basket.

    python basket_study.py
"""
import argparse, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.universe import load_all, classes, UNIVERSE

TARGET_VOL = 0.10          # annualised, per market
LOOKBACKS = [20, 40, 60, 100, 150, 200, 250]


def ann_sharpe(r, periods=252):
    r = pd.Series(r).dropna()
    if len(r) < 100:
        return None
    v = r.std(ddof=1)
    return float(r.mean() / v * np.sqrt(periods)) if v > 0 else None


def max_dd(r):
    eq = (1 + pd.Series(r).dropna()).cumprod()
    return float(((eq.cummax() - eq) / eq.cummax()).max() * 100)


def ann_return(r, periods=252):
    r = pd.Series(r).dropna()
    return float(r.mean() * periods * 100)


def market_returns(px, lb, long_only, cost_bps, vol_window=60):
    """One market's contribution, scaled to a common risk target.

    Every step uses only information available before the return it earns:
    the signal and the volatility estimate are both shifted forward a day.
    """
    ret = px.pct_change()
    vol = ret.rolling(vol_window).std() * np.sqrt(252)
    size = (TARGET_VOL / vol).clip(0, 3.0)

    raw = px.pct_change(lb)
    sig = (raw > 0).astype(float) if long_only else np.sign(raw)
    pos = (pd.Series(sig, index=px.index) * size).shift(1)

    turn = pos.diff().abs().fillna(0)
    return (pos * ret - turn * cost_bps / 10_000).dropna()


def hold_returns(px, cost_bps=0.0, vol_window=60):
    """The benchmark, scaled the same way so the comparison is fair."""
    ret = px.pct_change()
    vol = ret.rolling(vol_window).std() * np.sqrt(252)
    size = (TARGET_VOL / vol).clip(0, 3.0).shift(1)
    return (size * ret).dropna()


def build(series, lb, long_only, cost_bps, drop=None, lo=None, hi=None):
    """The portfolio and its benchmark, equal RISK weighted."""
    tcols, hcols = {}, {}
    for s, px in series.items():
        if drop and s == drop:
            continue
        p = px
        if lo is not None:
            p = p[p.index >= lo]
        if hi is not None:
            p = p[p.index < hi]
        if len(p) < lb + 200:
            continue
        tcols[s] = market_returns(p, lb, long_only, cost_bps)
        hcols[s] = hold_returns(p)
    if len(tcols) < 3:
        return None, None
    trend = pd.DataFrame(tcols).mean(axis=1, skipna=True).dropna()
    hold = pd.DataFrame(hcols).reindex(trend.index).mean(axis=1, skipna=True)
    return trend, hold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--long-only", action="store_true")
    a = ap.parse_args()
    long_only = a.long_only

    series = load_all()
    if len(series) < 8:
        print("not enough markets stored. run: python data/universe.py --pull")
        return
    cls = classes()

    print("=" * 86)
    print(f"  TREND FOLLOWING ACROSS {len(series)} MARKETS")
    print(f"  {'long only' if long_only else 'long and short'}, "
          f"each market scaled to {TARGET_VOL:.0%} volatility, "
          f"{a.cost_bps:g}bp round trip")
    print("=" * 86)

    by_cls = {}
    for s in series:
        by_cls.setdefault(cls[s], []).append(s)
    print("\n  " + "   ".join(f"{c}: {len(v)}" for c, v in sorted(by_cls.items())))

    # ---- the whole sample, every lookback ---------------------------------
    print("\n" + "-" * 86)
    print("  WHOLE SAMPLE")
    print(f"    {'lookback':>9} {'trend Sharpe':>14} {'hold Sharpe':>13} "
          f"{'excess':>8} {'trend DD':>10} {'hold DD':>9} {'trend ann':>11}")
    for lb in LOOKBACKS:
        t, h = build(series, lb, long_only, a.cost_bps)
        if t is None:
            continue
        st, sh = ann_sharpe(t), ann_sharpe(h)
        if st is None or sh is None:
            continue
        print(f"    {lb:>9} {st:>+14.2f} {sh:>+13.2f} {st - sh:>+8.2f} "
              f"{max_dd(t):>9.1f}% {max_dd(h):>8.1f}% {ann_return(t):>+10.2f}%")

    # ---- held out ----------------------------------------------------------
    idx = sorted(set().union(*[set(p.index) for p in series.values()]))
    cut = idx[int(len(idx) * 0.6)]
    print("\n" + "-" * 86)
    print(f"  HELD OUT   lookback chosen before {cut:%Y-%m-%d}, applied once after")
    best_lb, best_ex = None, -9e9
    for lb in LOOKBACKS:
        t, h = build(series, lb, long_only, a.cost_bps, hi=cut)
        if t is None:
            continue
        st, sh = ann_sharpe(t), ann_sharpe(h)
        if st is None or sh is None:
            continue
        if st - sh > best_ex:
            best_lb, best_ex = lb, st - sh
    print(f"    chosen {best_lb}-day, excess {best_ex:+.2f} in training")

    t, h = build(series, best_lb, long_only, a.cost_bps, lo=cut)
    held_ex = None
    if t is not None:
        st, sh = ann_sharpe(t), ann_sharpe(h)
        if st is not None and sh is not None:
            held_ex = st - sh
            print(f"    HELD OUT  trend {st:+.2f}  hold {sh:+.2f}  "
                  f"excess {held_ex:+.2f}")
            print(f"              trend drawdown {max_dd(t):.1f}%  "
                  f"hold drawdown {max_dd(h):.1f}%")
            print(f"              trend return {ann_return(t):+.2f}% a year")

    # ---- the check that killed the last version ---------------------------
    print("\n" + "-" * 86)
    print("  LEAVE ONE OUT")
    print("  Excess Sharpe with each market removed in turn. If any single")
    print("  removal changes the conclusion, this is not a basket.\n")
    t0, h0 = build(series, best_lb, long_only, a.cost_bps)
    base = ann_sharpe(t0) - ann_sharpe(h0)
    rows = []
    for s in sorted(series):
        t, h = build(series, best_lb, long_only, a.cost_bps, drop=s)
        if t is None:
            continue
        st, sh = ann_sharpe(t), ann_sharpe(h)
        if st is None or sh is None:
            continue
        rows.append((s, st - sh))
    rows.sort(key=lambda x: x[1])
    print(f"    full basket: {base:+.2f}")
    print(f"    {'worst drops':<16}{'':<6}{'best drops':<16}")
    for i in range(min(4, len(rows))):
        lo_s, lo_v = rows[i]
        hi_s, hi_v = rows[-(i + 1)]
        print(f"    without {lo_s:<8} {lo_v:>+5.2f}    "
              f"without {hi_s:<8} {hi_v:>+5.2f}")
    span = rows[-1][1] - rows[0][1]
    print(f"\n    range across all removals: {span:.2f}")
    if rows[0][1] > 0 and base > 0:
        print("    Every single removal stays positive. The result does not")
        print("    depend on any one market, which is what a basket means.")
    else:
        print("    At least one removal flips the sign. Still one bet.")

    # ---- by asset class ----------------------------------------------------
    print("\n" + "-" * 86)
    print("  BY ASSET CLASS   (each group traded on its own)\n")
    for c in sorted(by_cls):
        sub = {s: series[s] for s in by_cls[c]}
        if len(sub) < 2:
            continue
        t, h = build(sub, best_lb, long_only, a.cost_bps)
        if t is None:
            continue
        st, sh = ann_sharpe(t), ann_sharpe(h)
        if st is None or sh is None:
            continue
        print(f"    {c:<11} {len(sub):>2} markets   trend {st:>+5.2f}   "
              f"hold {sh:>+5.2f}   excess {st - sh:>+5.2f}")

    print("\n" + "=" * 86)
    if held_ex is not None and held_ex > 0.15 and rows and rows[0][1] > 0:
        print("  This survived a real diversification test: twenty markets, six")
        print("  asset classes, held-out data, and no single market carrying it.")
        print("  Run evaluate-style scrutiny on it before anything else.")
    elif held_ex is not None and held_ex > 0:
        print("  Positive out of sample but not decisively. Better than anything")
        print("  else in this project; not yet something to fund.")
    else:
        print("  Did not hold out of sample.")
    print("=" * 86)


if __name__ == "__main__":
    main()
