"""Trend following, tested the way it is actually deployed.

One result from the broader sweep was worth chasing. On Bitcoin, a 60-day trend
filter produced a similar return to holding with a much better Sharpe and half
the drawdown, and it held up out of sample. That is the first thing in this
project to beat its own benchmark on data it was not chosen on.

Two reasons to take it more seriously than anything that came before:

  * It has a mechanism with decades of evidence behind it across futures,
    currencies and equities, rather than a shape someone noticed on a chart.
  * It is slow. Positions are held for weeks, so the trading costs that
    destroyed every five-minute result become a rounding error.

And two reasons for caution:

  * A long-only rule on an asset that rose 59% a year will look good against
    zero. The benchmark here is buy and hold, never cash.
  * It failed out of sample on QQQ. A single market working is a coin flip
    with extra steps.

So this tests it the way it is genuinely used: across many markets at once.
Trend following is a diversification strategy. Its claim is not that it calls
any one market well, it is that a basket of trends across unrelated markets
produces a smoother line than any of them alone. That claim is testable here
and it is the one that matters.

    python trend_study.py
"""
import argparse, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate import get_data
from collector import load as cload

MARKETS = ["spy", "qqq", "btc", "eurusd", "nq", "es", "gc"]
LOOKBACKS = [20, 40, 60, 100, 150, 200]


def load_daily(name):
    """Daily closes for anything we hold, from whichever source has it."""
    try:
        df, _, _, _ = get_data(name)
    except Exception:
        df = None
    if df is None or df.empty:
        try:
            df = cload(name, "5m")
        except Exception:
            return None
    if df is None or df.empty:
        return None
    d = df.resample("1D").agg({"close": "last"}).dropna()
    return d["close"] if len(d) > 400 else None


def sharpe(r, periods):
    r = pd.Series(r).dropna()
    if len(r) < 60:
        return None
    v = r.std(ddof=1)
    return float(r.mean() / v * np.sqrt(periods)) if v > 0 else None


def dd(r):
    eq = (1 + pd.Series(r).dropna()).cumprod()
    return float(((eq.cummax() - eq) / eq.cummax()).max() * 100)


def signal(px, lb, long_only=True):
    """Long when the trailing return is positive. Shifted so the decision uses
    only information available before the return it earns."""
    s = (px.pct_change(lb) > 0).astype(float)
    if not long_only:
        s = s * 2 - 1
    return s.shift(1)


def run_market(px, lb, cost_bps, periods, long_only=True):
    ret = px.pct_change()
    sig = signal(px, lb, long_only)
    turn = sig.diff().abs().fillna(0)
    r = (sig * ret - turn * cost_bps / 10_000).dropna()
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost-bps", type=float, default=5.0)
    ap.add_argument("--long-only", action="store_true", default=True)
    a = ap.parse_args()

    print("=" * 86)
    print("  TREND FOLLOWING, ACROSS EVERY MARKET WE HOLD")
    print("=" * 86)

    series = {}
    for m in MARKETS:
        px = load_daily(m)
        if px is None:
            print(f"  {m:<8} no usable daily series")
            continue
        series[m] = px
        print(f"  {m:<8} {len(px):>5} days   {px.index[0]:%Y-%m-%d} to "
              f"{px.index[-1]:%Y-%m-%d}")
    if len(series) < 3:
        print("\n  not enough markets to test a basket")
        return

    # ---- per market, every lookback, against its own benchmark ------------
    print("\n" + "-" * 86)
    print("  EXCESS SHARPE OVER BUY AND HOLD, BY LOOKBACK")
    print("  Positive means the trend filter beat simply holding the thing.\n")
    hdr = "  " + f"{'market':<9}" + "".join(f"{lb:>9}d" for lb in LOOKBACKS) + f"{'hold':>10}"
    print(hdr)
    per_market = {}
    for m, px in series.items():
        periods = 365 if m == "btc" else 252
        bench = sharpe(px.pct_change(), periods)
        if bench is None:
            continue
        row, best = [], (None, -9e9)
        for lb in LOOKBACKS:
            r = run_market(px, lb, a.cost_bps, periods, a.long_only)
            s = sharpe(r, periods)
            row.append(s - bench if s is not None else None)
            if s is not None and s - bench > best[1]:
                best = (lb, s - bench)
        per_market[m] = (row, bench, best)
        cells = "".join(f"{v:>+10.2f}" if v is not None else f"{'-':>10}"
                        for v in row)
        print(f"  {m:<9}{cells}{bench:>+10.2f}")

    # ---- the basket, which is the real claim -------------------------------
    print("\n" + "-" * 86)
    print("  THE BASKET")
    print("  Equal weight across every market, rebalanced daily. This is the")
    print("  actual claim: uncorrelated trends add up to something smoother")
    print("  than any single one of them.\n")

    for lb in LOOKBACKS:
        cols = {}
        for m, px in series.items():
            r = run_market(px, lb, a.cost_bps, 252, a.long_only)
            cols[m] = r
        basket = pd.DataFrame(cols).dropna(how="all")
        if basket.empty or len(basket) < 200:
            continue
        port = basket.mean(axis=1, skipna=True).dropna()

        # the benchmark basket: holding all of them, equally weighted
        hold_cols = {m: px.pct_change() for m, px in series.items()}
        hold = pd.DataFrame(hold_cols).reindex(port.index).mean(axis=1, skipna=True)

        sp, sh = sharpe(port, 252), sharpe(hold, 252)
        if sp is None or sh is None:
            continue
        print(f"    {lb:>3}-day   trend Sharpe {sp:>+5.2f}   hold Sharpe {sh:>+5.2f}"
              f"   excess {sp - sh:>+5.2f}   trend DD {dd(port):>5.1f}%   "
              f"hold DD {dd(hold):>5.1f}%")

    # ---- held out ----------------------------------------------------------
    print("\n" + "-" * 86)
    print("  HELD OUT")
    print("  Lookback chosen on the first 60% of the basket, applied once to")
    print("  the last 40%.\n")

    all_idx = sorted(set().union(*[set(px.index) for px in series.values()]))
    cut_date = all_idx[int(len(all_idx) * 0.6)]
    print(f"    split at {cut_date:%Y-%m-%d}\n")

    def basket_for(lb, lo=None, hi=None):
        cols = {}
        for m, px in series.items():
            p = px
            if lo is not None:
                p = p[p.index >= lo]
            if hi is not None:
                p = p[p.index < hi]
            if len(p) < lb + 60:
                continue
            cols[m] = run_market(p, lb, a.cost_bps, 252, a.long_only)
        if not cols:
            return None, None
        b = pd.DataFrame(cols)
        port = b.mean(axis=1, skipna=True).dropna()
        hold_cols = {}
        for m, px in series.items():
            p = px
            if lo is not None:
                p = p[p.index >= lo]
            if hi is not None:
                p = p[p.index < hi]
            hold_cols[m] = p.pct_change()
        hold = pd.DataFrame(hold_cols).reindex(port.index).mean(axis=1, skipna=True)
        return port, hold

    best_lb, best_ex = None, -9e9
    for lb in LOOKBACKS:
        port, hold = basket_for(lb, hi=cut_date)
        if port is None:
            continue
        sp, sh = sharpe(port, 252), sharpe(hold, 252)
        if sp is None or sh is None:
            continue
        print(f"    {lb:>3}-day  first 60%   excess {sp - sh:>+5.2f}")
        if sp - sh > best_ex:
            best_lb, best_ex = lb, sp - sh

    if best_lb:
        port, hold = basket_for(best_lb, lo=cut_date)
        if port is not None:
            sp, sh = sharpe(port, 252), sharpe(hold, 252)
            print(f"\n    chosen: {best_lb}-day, excess {best_ex:+.2f} in training")
            if sp is not None and sh is not None:
                print(f"    HELD OUT   trend Sharpe {sp:+.2f}   hold Sharpe "
                      f"{sh:+.2f}   excess {sp - sh:+.2f}")
                print(f"               trend drawdown {dd(port):.1f}%   "
                      f"hold drawdown {dd(hold):.1f}%")
                print()
                if sp - sh > 0.15:
                    print("    It held. That is the first thing in this project to")
                    print("    beat its own benchmark on data it was not chosen on.")
                elif sp - sh > 0:
                    print("    Marginally positive out of sample. Better than")
                    print("    everything before it, not yet worth funding.")
                else:
                    print("    It did not hold. The in-sample result was the")
                    print("    lookback being chosen to suit the past.")

    print("\n" + "=" * 86)
    print("  Note on what this is NOT: a long-only trend filter cannot beat a")
    print("  rising market on return. Its claim is a smoother path to a similar")
    print("  place, which is why drawdown matters as much as Sharpe here.")
    print("=" * 86)


if __name__ == "__main__":
    main()
