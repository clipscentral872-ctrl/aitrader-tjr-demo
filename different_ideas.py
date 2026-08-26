"""Genuinely different ideas, chosen for having a mechanism rather than a shape.

Everything tested so far was one idea wearing different clothes: a liquidity
sweep predicts reversal. Measured directly that is true 51% of the time, which
is why no arrangement of it worked.

These are different in kind. Each one is a documented effect with a proposed
cause, not a pattern found by looking at charts. That matters because a pattern
with no mechanism has nothing to explain why it should persist, and this project
has already demonstrated what happens when you search for patterns.

  1. OVERNIGHT DRIFT      Equity index returns accrue overwhelmingly between
                          the close and the next open, not during the session.
                          Proposed cause: compensation for holding risk while
                          markets are shut and positions cannot be adjusted.

  2. TIME-SERIES MOMENTUM Assets that have risen over the past N days continue
                          to. The most replicated anomaly in the literature.
                          Proposed cause: under-reaction and slow diffusion of
                          information.

  3. VOLATILITY SCALING   Not a strategy but a sizing rule: hold less when
                          realised volatility is high. Volatility clusters and
                          is far more forecastable than direction.

  4. TURN OF MONTH        Returns concentrate around the month boundary.
                          Proposed cause: pension and payroll flows on a
                          calendar schedule.

  5. DAY OF WEEK          The oldest calendar anomaly, and mostly gone. Included
                          precisely because it is expected to fail, which keeps
                          the test honest about what a null result looks like.

Crucially all of these are LOW FREQUENCY. The cost burden that destroyed the
Bitcoin results was 1.2R per trade at five-minute stops. Holding overnight or
for weeks makes trading costs a rounding error, which removes the structural
problem rather than tuning around it.

Metric is annualised return and Sharpe rather than R, because these are
positions held over time, not trades with a stop and a target.

    python different_ideas.py --market spy
"""
import argparse, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from evaluate import get_data

TRADING_DAYS = 252


def daily_bars(df, crypto=False):
    """Collapse to daily open/close, plus the overnight and intraday split."""
    d = df.resample("1D").agg({"open": "first", "high": "max", "low": "min",
                               "close": "last", "volume": "sum"}).dropna()
    d["intraday"] = d["close"] / d["open"] - 1
    d["overnight"] = d["open"] / d["close"].shift(1) - 1
    d["total"] = d["close"] / d["close"].shift(1) - 1
    return d.dropna()


def stats(r, periods=TRADING_DAYS, cost_bps=0.0, turnover=None):
    """Annualised return, volatility, Sharpe and drawdown for a return series."""
    r = pd.Series(r).dropna()
    if len(r) < 30:
        return None
    if cost_bps and turnover is not None:
        r = r - (pd.Series(turnover).reindex(r.index).fillna(0).abs()
                 * cost_bps / 10_000)
    ann = float(r.mean() * periods)
    vol = float(r.std(ddof=1) * np.sqrt(periods))
    eq = (1 + r).cumprod()
    dd = float(((eq.cummax() - eq) / eq.cummax()).max() * 100)
    return {"n": len(r), "ann": ann * 100, "vol": vol * 100,
            "sharpe": ann / vol if vol > 0 else 0.0, "maxdd": dd,
            "hit": float((r > 0).mean() * 100)}


BENCH = {"sharpe": None}


def show(label, s, width=30):
    if s is None:
        print(f"    {label:<{width}} too few periods")
        return
    # A long-only strategy in a rising market beats zero without being worth
    # anything. The benchmark is buy and hold, not cash. This column is the
    # only one that answers "was the work worth doing".
    b = BENCH.get("sharpe")
    excess = "" if b is None else f" {s['sharpe'] - b:>+8.2f}"
    print(f"    {label:<{width}} {s['n']:>6} {s['ann']:>+9.2f}% "
          f"{s['vol']:>8.2f}% {s['sharpe']:>+8.2f} {s['maxdd']:>8.1f}% "
          f"{s['hit']:>7.1f}%{excess}")


def header():
    b = "" if BENCH.get("sharpe") is None else f" {'vs hold':>8}"
    print(f"    {'':<30} {'periods':>6} {'annual':>9} {'vol':>9} "
          f"{'Sharpe':>8} {'max DD':>9} {'hit %':>8}{b}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="spy")
    ap.add_argument("--cost-bps", type=float, default=2.0,
                    help="round-trip cost in basis points of notional")
    a = ap.parse_args()

    df, _, _, _ = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return
    crypto = a.market in ("btc",)
    d = daily_bars(df, crypto)
    periods = 365 if crypto else TRADING_DAYS

    print("=" * 84)
    print(f"  DIFFERENT IDEAS  {a.market.upper()}   {len(d):,} days   "
          f"{d.index[0]:%Y-%m-%d} to {d.index[-1]:%Y-%m-%d}")
    print("=" * 84)

    cut = int(len(d) * 0.6)
    train, test = d.iloc[:cut], d.iloc[cut:]

    hold = stats(d["total"], periods)
    print("")
    print(f"  BENCHMARK  buy and hold: {hold['ann']:+.2f}% a year, "
          f"Sharpe {hold['sharpe']:+.2f}, max drawdown {hold['maxdd']:.1f}%")
    print("  Everything below is judged against that, not against zero.")
    BENCH["sharpe"] = hold["sharpe"]

    # ---- 1. overnight against intraday ------------------------------------
    print("\n1. OVERNIGHT AGAINST INTRADAY")
    print("   Buy at the close and sell at the next open, versus the reverse.")
    print("   If the split is real, one of these carries the whole return.\n")
    header()
    show("buy and hold", stats(d["total"], periods))
    show("overnight only", stats(d["overnight"], periods,
                                 a.cost_bps, np.ones(len(d))))
    show("intraday only", stats(d["intraday"], periods,
                                a.cost_bps, np.ones(len(d))))
    print()
    show("overnight, first 60%", stats(train["overnight"], periods,
                                       a.cost_bps, np.ones(len(train))))
    show("overnight, HELD OUT", stats(test["overnight"], periods,
                                      a.cost_bps, np.ones(len(test))))

    # ---- 2. time-series momentum ------------------------------------------
    print("\n2. TIME-SERIES MOMENTUM")
    print("   Hold long when the trailing return is positive, else flat.\n")
    header()
    best_lb, best_sh = None, -9e9
    for lb in (5, 10, 20, 60, 120):
        sig = (d["close"].pct_change(lb) > 0).shift(1).astype(float)
        r = sig * d["total"]
        turn = sig.diff().abs()
        s = stats(r, periods, a.cost_bps, turn)
        show(f"{lb}-day lookback", s)
        if s and s["sharpe"] > best_sh:
            best_lb, best_sh = lb, s["sharpe"]
    if best_lb:
        print()
        for nm, seg in (("first 60%", train), ("HELD OUT", test)):
            sig = (seg["close"].pct_change(best_lb) > 0).shift(1).astype(float)
            show(f"{best_lb}-day, {nm}",
                 stats(sig * seg["total"], periods, a.cost_bps,
                       sig.diff().abs()))

    # ---- 3. volatility scaling --------------------------------------------
    print("\n3. VOLATILITY SCALING")
    print("   Same exposure, sized inversely to trailing volatility.")
    print("   A sizing rule, not a signal: it should raise Sharpe, not return.\n")
    header()
    show("buy and hold", stats(d["total"], periods))
    for w in (20, 60):
        vol = d["total"].rolling(w).std()
        target = vol.median()
        size = (target / vol).clip(0, 2.0).shift(1)
        s = stats(size * d["total"], periods, a.cost_bps, size.diff().abs())
        show(f"scaled by {w}-day vol", s)

    # ---- 4. turn of month --------------------------------------------------
    print("\n4. TURN OF MONTH")
    print("   Hold only around the month boundary.\n")
    header()
    dom = d.index.day
    eom = d.index.to_series().groupby([d.index.year, d.index.month]).transform("max")
    is_turn = (dom <= 3) | (d.index.to_series() >= eom - pd.Timedelta(days=2))
    sig = pd.Series(is_turn.values.astype(float), index=d.index).shift(1)
    show("turn of month only", stats(sig * d["total"], periods,
                                     a.cost_bps, sig.diff().abs()))
    show("rest of the month", stats((1 - sig) * d["total"], periods,
                                    a.cost_bps, (1 - sig).diff().abs()))

    # ---- 5. day of week ----------------------------------------------------
    print("\n5. DAY OF WEEK")
    print("   Expected to fail. Included so a null result has a shape.\n")
    header()
    for i, nm in enumerate(["Monday", "Tuesday", "Wednesday", "Thursday", "Friday"]):
        sel = d["total"][d.index.dayofweek == i]
        show(nm, stats(sel, 52))

    print("\n" + "=" * 84)
    print("  Every number above is a hypothesis. Two things decide whether one")
    print("  is worth anything: it has to survive the HELD OUT rows, and it has")
    print("  to beat buy and hold. A long-only rule in a rising market clears")
    print("  zero without clearing either.")
    print("=" * 84)


if __name__ == "__main__":
    main()
