"""What risk per trade does to the outcome, which is a different question.

Worth being clear about why this study is safe when so much else has not been.

Searching for a better strategy means testing many hypotheses, and every extra
one raises the bar a result must clear. That is why 335 combinations produced
nothing: the search itself manufactures winners.

Risk sizing is not that. It does not change expectancy at all. A strategy worth
+0.14R per trade is worth +0.14R whether you risk 0.1% or 5%. What risk changes
is the SHAPE of the outcome: how wide the range gets, how deep the drawdowns
go, and how likely you are to be wiped out before the edge shows up.

So there is a definite answer here, not a search. The uncomfortable part is
that the answer depends on an edge existing, and none has been established.
Sizing up a negative expectancy does not produce income faster. It produces
losses faster, which this makes visible rather than hiding.

    python risk_study.py --market eurusd
"""
import argparse, dataclasses, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run
from backtest import bootstrap
from evaluate import get_data
from tjr_study import SESSIONS

# What a prop firm actually enforces. These are the constraints that decide
# whether an account survives, and they bite long before the edge matters.
PROP_DAILY_LOSS = 5.0
PROP_TOTAL_LOSS = 10.0


def ruin_odds(r, risk_pct, limit_pct, runs=4000, block=5, seed=0):
    """Chance of hitting a drawdown limit at some point, not just ending below."""
    a = np.asarray(r, float)
    n = len(a)
    if n < 20:
        return None
    rng = np.random.default_rng(seed)
    hits = 0
    for _ in range(runs):
        nb = int(np.ceil(n / block))
        starts = rng.integers(0, max(1, n - block), nb)
        path = np.concatenate([a[s:s + block] for s in starts])[:n]
        eq = np.cumprod(1 + (risk_pct / 100) * path)
        peak = np.maximum.accumulate(eq)
        if ((peak - eq) / peak).max() * 100 >= limit_pct:
            hits += 1
    return hits / runs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="eurusd")
    ap.add_argument("--session", default="engine default (09:30-12:30 NY)")
    ap.add_argument("--min-stop", type=float, default=None)
    a = ap.parse_args()

    df, costs, ms, _ = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return
    ms = a.min_stop if a.min_stop is not None else ms
    filt = SESSIONS.get(a.session)

    cfg = Config(min_stop_pct=ms, max_stop_pct=max(1.5, ms * 4),
                 min_rr=3.0, max_rr=5.0, htf_bias=True,
                 require_real_draw=True, require_premium=True)
    setups = find_setups(df, cfg, session_filter=filt)
    trades, _ = bt_run(df, setups, costs)
    r = [t.r for t in trades]
    if len(r) < 30:
        print(f"only {len(r)} trades, not enough to say anything about risk")
        return

    arr = np.array(r)
    exp = float(arr.mean())
    print("=" * 74)
    print(f"  RISK STUDY  {a.market.upper()}   {len(arr)} trades   "
          f"expectancy {exp:+.3f}R   win {(arr > 0).mean()*100:.1f}%")
    print("=" * 74)

    if exp <= 0:
        print("\n  Expectancy is negative. Everything below shows how much FASTER")
        print("  the account dies as risk rises. There is no risk setting that")
        print("  turns a losing strategy into income.\n")
    else:
        print(f"\n  Expectancy is positive but has NOT cleared evaluate.py.")
        print("  Treat the returns below as what it would look like IF the edge")
        print("  is real, and the drawdowns as what happens whether it is or not.\n")

    print(f"  {'risk':>6} {'median return':>15} {'5th pct':>10} {'median DD':>11} "
          f"{'95th DD':>9} {'up?':>7}")
    for risk in (0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0):
        res = bootstrap.run(r, risk_pct=risk, runs=3000, block=5)
        if not res:
            continue
        print(f"  {risk:>5.2f}% {res.median_return:>+14.1f}% "
              f"{res.p05_return:>+9.1f}% {res.median_dd:>10.1f}% "
              f"{res.p95_dd:>8.1f}% {res.prob_profit*100:>6.1f}%")

    # ---- the constraint that actually decides it -------------------------
    print("\n  AGAINST A PROP FIRM'S RULES")
    print(f"  A {PROP_TOTAL_LOSS:.0f}% total drawdown ends the account. That is the")
    print("  number that matters, not the return.\n")
    print(f"  {'risk':>6} {'chance of blowing the account':>32}")
    safe = None
    for risk in (0.1, 0.25, 0.5, 1.0, 2.0, 3.0, 5.0):
        p = ruin_odds(r, risk, PROP_TOTAL_LOSS)
        if p is None:
            continue
        flag = ""
        if p <= 0.05 and safe is None:
            safe = risk
        if p > 0.5:
            flag = "   more likely than not"
        print(f"  {risk:>5.2f}% {p*100:>30.1f}%{flag}")

    best = bootstrap.risk_for_drawdown(r, PROP_TOTAL_LOSS)
    print(f"\n  Largest risk keeping 95% of paths inside {PROP_TOTAL_LOSS:.0f}%: {best}%")

    # ---- what that means in money ----------------------------------------
    print("\n  WHAT THAT IS WORTH IN MONEY")
    n_year = len(arr) / max((df.index[-1] - df.index[0]).days / 365.25, 0.5)
    print(f"    trades per year at this frequency: {n_year:.0f}")
    for acct in (25_000, 50_000, 100_000):
        per_year = acct * (best / 100) * exp * n_year
        print(f"    ${acct:>7,} account at {best}% risk: "
              f"${per_year:>10,.0f} a year, if the edge is real")

    print("\n" + "=" * 74)
    print("  Raising risk raises the return and the drawdown together, in a")
    print("  fixed ratio. It cannot improve the odds. The only thing that")
    print("  improves the odds is a strategy that clears evaluate.py.")
    print("=" * 74)


if __name__ == "__main__":
    main()
