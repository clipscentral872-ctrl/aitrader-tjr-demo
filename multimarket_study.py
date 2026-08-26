"""Does trading many markets at once close the income gap?

The income equation has four terms and only one has headroom left:

    income = account  x  risk%  x  expectancy  x  trades per year

Expectancy tops out near +0.15R, measured across five markets and eleven years.
Risk percent is capped near 0.9% by the losing streak and the drawdown limit.
The account is what it is. Trade count is the only term that can multiply, and
it multiplies with every market added.

There is a second effect that compounds it and is the reason this is worth
doing rather than just running one market bigger. Uncorrelated markets rarely
lose on the same day, so a portfolio's worst losing streak is shorter than any
single market's. A shorter streak raises the risk that survives the drawdown
limit. So trade count and risk capacity push the same way here, which is the
only place in this project where two levers have not cancelled.

The claim is testable and the failure mode is known. The trend-following basket
looked good until one market was removed and the result inverted. So the same
leave-one-out check runs here, and results are split train and test as usual.

    python multimarket_study.py
"""
import argparse, glob, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run, Costs
from backtest import bootstrap
from backtest.guard import assess, Ledger
from evaluate import get_data, ETF, FX
from tjr_study import SESSIONS

STORE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "store")
LIMIT = 10.0


def available():
    """Every 5-minute series we hold, with the right cost model attached."""
    out = {}
    for path in sorted(glob.glob(os.path.join(STORE, "*_5m.parquet"))):
        name = os.path.basename(path).replace("_5m.parquet", "")
        try:
            df = pd.read_parquet(path)
        except Exception:
            continue
        if df is None or len(df) < 20000:
            continue
        if df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        costs = ETF if name not in ("btcusd",) else Costs(
            maker_pct=0.0, taker_pct=0.04, slip_pct=0.02)
        out[name] = (df, costs, 0.05 if name != "btcusd" else 0.80)
    # EURUSD lives elsewhere and is the market the result was found on
    try:
        df, c, ms, _ = get_data("eurusd")
        if df is not None and not df.empty:
            out["eurusd"] = (df, c, ms)
    except Exception:
        pass
    return out


def trades_for(df, costs, ms, filt, lo=None, hi=None):
    seg = df
    if lo is not None:
        seg = seg[seg.index >= lo]
    if hi is not None:
        seg = seg[seg.index < hi]
    if len(seg) < 5000:
        return None
    cfg = Config(min_stop_pct=ms, max_stop_pct=max(1.5, ms * 4),
                 min_rr=0.4, max_rr=0.5, htf_bias=True,
                 require_real_draw=True, require_premium=True)
    s = find_setups(seg, cfg, session_filter=filt)
    if not s:
        return None
    tr, _ = bt_run(seg, s, costs)
    if len(tr) < 30:
        return None
    return pd.DataFrame({"t": [x.entry_time for x in tr],
                         "r": [x.r for x in tr]}).set_index("t").sort_index()


def portfolio(per_market, drop=None):
    """All markets' trades on one timeline, in the order they happened.

    Interleaving by time is the point: the losing streak that decides risk
    capacity is a property of the COMBINED sequence, not of any one market.
    """
    frames = [v for k, v in per_market.items() if k != drop and v is not None]
    if len(frames) < 2:
        return None
    return pd.concat(frames).sort_index()


def worst_streak(r):
    st = worst = 0
    for x in r:
        st = st + 1 if x <= 0 else 0
        worst = max(worst, st)
    return worst


def summarise(label, seq, years, account, show=True):
    if seq is None or len(seq) < 60:
        if show:
            print(f"  {label:<28} too few trades")
        return None
    r = seq["r"].to_numpy(float)
    safe = bootstrap.risk_for_drawdown(list(r), LIMIT)
    per_yr = len(r) / years
    money = account * (safe / 100) * float(r.mean()) * per_yr
    if show:
        print(f"  {label:<28} {len(r):>6} {per_yr:>8.0f} {r.mean():>+8.3f} "
              f"{(r > 0).mean()*100:>6.1f}% {worst_streak(r):>7} "
              f"{safe:>8.3f}% ${money/12:>9,.0f}")
    return {"n": len(r), "per_yr": per_yr, "mean": float(r.mean()),
            "safe": safe, "month": money / 12, "streak": worst_streak(r)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--account", type=float, default=50_000)
    ap.add_argument("--session", default="London + New York")
    a = ap.parse_args()

    mkts = available()
    if len(mkts) < 3:
        print(f"only {len(mkts)} markets available; the downloads may still be running")
        return
    filt = SESSIONS.get(a.session)

    print("=" * 92)
    print(f"  MULTI-MARKET   {len(mkts)} markets   window: {a.session}")
    print(f"  account ${a.account:,.0f}, {LIMIT:.0f}% drawdown limit")
    print("=" * 92)

    # Split on a shared DATE, but do not truncate every market to the
    # intersection. Taking max(starts) meant one short series (Bitcoin, which
    # only had 2024 onward) cut eleven years of EURUSD down to twenty months
    # and destroyed the sample. Each market now contributes whatever history it
    # has; only the train/test boundary is shared.
    starts = [v[0].index[0] for v in mkts.values()]
    ends = [v[0].index[-1] for v in mkts.values()]
    lo, hi = min(starts), max(ends)
    cut = lo + (hi - lo) * 0.6
    span = {n: (v[0].index[0], v[0].index[-1]) for n, v in mkts.items()}
    short = [n for n, (s0, s1) in span.items() if (s1 - s0).days < 500]
    if short:
        print(f"\n  note: {', '.join(short)} have under 18 months of history")
    print(f"\n  common window {lo:%Y-%m-%d} to {hi:%Y-%m-%d}, split {cut:%Y-%m-%d}")

    yrs_tr = (cut - lo).days / 365.25
    yrs_te = (hi - cut).days / 365.25

    print(f"\n  {'market':<28} {'trades':>6} {'per yr':>8} {'exp R':>8} "
          f"{'win %':>7} {'streak':>7} {'safe':>9} {'$/month':>10}")
    print("  --- each market alone, HELD OUT ---")
    per_test, per_train = {}, {}
    for name, (df, costs, ms) in sorted(mkts.items()):
        per_train[name] = trades_for(df, costs, ms, filt, lo=lo, hi=cut)
        per_test[name] = trades_for(df, costs, ms, filt, lo=cut, hi=hi)
        summarise(name, per_test[name], yrs_te, a.account)

    print("\n  --- the portfolio ---")
    tr_all = portfolio(per_train)
    te_all = portfolio(per_test)
    s_tr = summarise("all markets, training", tr_all, yrs_tr, a.account)
    s_te = summarise("all markets, HELD OUT", te_all, yrs_te, a.account)

    if not s_te:
        print("\n  not enough combined trades to judge")
        return

    # ---- did diversification shorten the streak? --------------------------
    singles = [summarise(n, v, yrs_te, a.account, show=False)
               for n, v in per_test.items()]
    singles = [x for x in singles if x]
    if singles:
        # The worst streak in a series grows with its LENGTH, so comparing a
        # 500-trade portfolio against a 100-trade market is rigged: the longer
        # series has a longer streak by construction, whatever its structure.
        # Per hundred trades makes the comparison mean something.
        avg_streak = np.mean([x["streak"] / max(x["n"], 1) * 100 for x in singles])
        avg_safe = np.mean([x["safe"] for x in singles])
        port_streak = s_te["streak"] / max(s_te["n"], 1) * 100
        print(f"\n  average single market: {avg_streak:.2f} streak per 100 trades, "
              f"safe risk {avg_safe:.3f}%")
        print(f"  the portfolio:         {port_streak:.2f} per 100 trades, "
              f"safe risk {s_te['safe']:.3f}%")
        if s_te["safe"] > avg_safe * 1.1:
            print("  Diversification raised the risk capacity, which is the")
            print("  effect this test exists to find.")
        else:
            print("  Risk capacity did NOT improve. The markets are losing")
            print("  together, so combining them adds trades but not safety.")

    # ---- leave one out ----------------------------------------------------
    print("\n  --- leave one out, HELD OUT ---")
    rows = []
    for name in sorted(per_test):
        p = portfolio(per_test, drop=name)
        s = summarise(f"without {name}", p, yrs_te, a.account, show=False)
        if s:
            rows.append((name, s["month"]))
    rows.sort(key=lambda x: x[1])
    for name, m in rows[:3]:
        print(f"    without {name:<12} ${m:>9,.0f} a month")
    if rows:
        print(f"    ... best case:  without {rows[-1][0]:<12} ${rows[-1][1]:>9,.0f}")
        if rows[0][1] > s_te["month"] * 0.6:
            print("    No single market is carrying the result.")
        else:
            print("    One market dominates. This is not really a portfolio.")

    # ---- is the combined result significant? ------------------------------
    print("\n" + "-" * 92)
    led = Ledger()
    v = assess(list(te_all["r"].to_numpy(float)), dataset="multimarket",
               label="portfolio", ledger=led)
    print(f"  {v.headline}")
    print(f"    {v.detail}")

    print("\n" + "=" * 92)
    print(f"  ${a.account:,.0f} account, held-out estimate: "
          f"${s_te['month']:,.0f} a month")
    for target, name in ((3000, "$3,000 a month"), (13000, "$3,000 every 5 days")):
        need = a.account * target / s_te["month"] if s_te["month"] > 0 else 0
        print(f"    {name:<22} would need ${need:>12,.0f}")
    print("=" * 92)


if __name__ == "__main__":
    main()
