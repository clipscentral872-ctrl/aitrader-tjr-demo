"""Can we cut the drawdown without giving up the return?

Three overlays, tested against the identical trade sequence so the only thing
changing is the money management:

  1. MONTHLY STOP      down X% in a month, stop until the next one
  2. MARKET SPLIT      a separate risk budget per market rather than one pot
  3. RISK SCALING      cut risk after consecutive losses, restore after wins

None of these touch the entry logic. They are all about how losses are allowed
to compound, because that is where drawdown actually comes from.

A warning that applies to every number below: these thresholds are being chosen
by looking at the same data they are measured on. Treat the RANKING as more
trustworthy than the exact figures.
"""
import sys, os
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.histdata_import import load
from data.fetch import resample
from engine.strategy import find_setups, Config
from backtest.engine import run, Costs

FX = Costs(maker_pct=0.0, taker_pct=0.0008, slip_pct=0.0008)
IDX = Costs(maker_pct=0.0, taker_pct=0.002, slip_pct=0.003)
NY = lambda ts: 13 * 60 + 30 <= (ts.hour * 60 + ts.minute) < 16 * 60 + 30
TUNED = dict(max_stop_pct=0.6, min_rr=1.0, htf_bias=False,
             require_real_draw=False, require_premium=True)
MARKETS = (("eurusd", FX, 0.05), ("nsxusd", IDX, 0.08))


def trades():
    """Time-ordered trade list across both markets."""
    rows = []
    for pair, costs, ms in MARKETS:
        d5 = resample(load(pair), "5min")
        s = find_setups(d5, Config(**{**TUNED, "min_stop_pct": ms}), session_filter=NY)
        t, _ = run(d5, s, costs)
        for x in t:
            rows.append({"time": x.exit_time, "market": pair, "r": x.r})
    return pd.DataFrame(rows).sort_values("time").reset_index(drop=True)


def curve(df, risk=0.01, monthly_stop=None, scale_after=None, scale_to=0.5,
          per_market=False):
    """Walk the trades and return (final_equity, max_drawdown, months_stopped)."""
    eq, peak, mdd = 1.0, 1.0, 0.0
    month_start_eq = 1.0
    cur_month = None
    stopped = set()
    losses = 0
    # a separate notional budget per market, so one market's bad run does not
    # size down the other's trades
    budgets = {m: 1.0 for m, _, _ in MARKETS}   # each starts at par

    for _, t in df.iterrows():
        mk = (t["time"].year, t["time"].month)
        if mk != cur_month:
            cur_month, month_start_eq = mk, eq

        if monthly_stop is not None:
            if mk in stopped:
                continue
            if (eq - month_start_eq) / month_start_eq <= -monthly_stop:
                stopped.add(mk)
                continue

        r_use = risk
        if scale_after is not None and losses >= scale_after:
            r_use = risk * scale_to

        if per_market:
            # each market compounds its OWN half of the account, so a bad run
            # in one does not shrink the position size of the other
            b = budgets[t["market"]]
            budgets[t["market"]] = b * (1 + r_use * t["r"])
            eq = sum(budgets.values()) / len(budgets)
        else:
            eq *= (1 + r_use * t["r"])

        losses = losses + 1 if t["r"] <= 0 else 0
        peak = max(peak, eq)
        mdd = max(mdd, (peak - eq) / peak)
    return eq, mdd, len(stopped)


def report(df):
    yrs = (df["time"].iloc[-1] - df["time"].iloc[0]).days / 365
    print(f"{len(df)} trades over {yrs:.1f} years\n")

    # how correlated are the two markets? diversification only helps if not
    m = df.copy()
    m["ym"] = m["time"].dt.to_period("M")
    piv = m.pivot_table(index="ym", columns="market", values="r", aggfunc="sum").fillna(0)
    if piv.shape[1] == 2:
        c = piv.corr().iloc[0, 1]
        print(f"monthly return correlation between the two markets: {c:+.2f}")
        print("  (near zero means splitting risk between them genuinely helps)\n")

    def line(name, eq, mdd, stopped=None):
        cagr = (eq ** (1 / yrs) - 1) * 100
        note = f"  ({stopped} months stopped)" if stopped else ""
        flag = "  <- under 10%" if mdd < 0.10 else ""
        print(f"  {name:<34} CAGR {cagr:>+6.1f}%   maxDD {mdd*100:>5.1f}%{flag}{note}")

    print("BASELINE")
    for risk in (0.005, 0.01):
        eq, mdd, _ = curve(df, risk=risk)
        line(f"plain, {risk*100:.2f}% risk", eq, mdd)

    print("\n1. MONTHLY STOP  (1% risk per trade)")
    for ms in (0.03, 0.04, 0.05, 0.06):
        eq, mdd, st = curve(df, risk=0.01, monthly_stop=ms)
        line(f"stop the month at -{ms*100:.0f}%", eq, mdd, st)

    print("\n2. MARKET SPLIT  (separate budget per market)")
    for risk in (0.01, 0.015, 0.02):
        eq, mdd, _ = curve(df, risk=risk, per_market=True)
        line(f"split, {risk*100:.1f}% risk each", eq, mdd)

    print("\n3. RISK SCALING  (cut risk after N straight losses)")
    for n in (2, 3, 4):
        for to in (0.5, 0.25):
            eq, mdd, _ = curve(df, risk=0.01, scale_after=n, scale_to=to)
            line(f"after {n} losses -> {to*100:.0f}% size", eq, mdd)

    print("\nCOMBINED  (all three together)")
    for risk, ms, n in ((0.01, 0.04, 3), (0.0075, 0.04, 3), (0.005, 0.03, 2)):
        eq, mdd, st = curve(df, risk=risk, monthly_stop=ms, scale_after=n,
                            scale_to=0.5, per_market=True)
        line(f"{risk*100:.2f}% + stop -{ms*100:.0f}% + scale@{n}", eq, mdd, st)


if __name__ == "__main__":
    report(trades())
