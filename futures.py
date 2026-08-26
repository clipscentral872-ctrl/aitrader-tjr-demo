"""The system pointed at NQ and ES futures, which is what the method is for.

TJR trades Nasdaq and S&P futures. Everything in this project has been measured
on something else, and the three things were quietly conflated under the word
"Nasdaq":

    NSXUSD    the Nasdaq CASH INDEX. A number, not a tradeable instrument.
              Every promising one-minute figure sits on this.
    QQQ       an ETF. Trades 6.5 hours, costs a slice of notional, cannot
              touch London or the overnight sessions.
    NQ=F      the actual CME contract. 23 hours, fixed cost per contract.
              We hold ten weeks of it, which is not enough to test on.

They are not interchangeable. The cash index has no basis and no roll; the ETF
closes when most of the method's sessions are open; and the cost models differ
by a factor of eight. Each of those differences lands directly on the sweeps
this strategy trades.

WHAT THIS MODULE DOES

Routes every market to the right contract specification and cost model, and
makes the proxy relationship explicit rather than implied. A result on the
proxy is labelled as such, and the ten weeks of real contract data are the
reference it gets checked against.

CONTRACT SPECS, from the CME

    NQ    E-mini Nasdaq 100      0.25 tick    $5.00/tick    $20 a point
    MNQ   Micro Nasdaq 100       0.25 tick    $0.50/tick    $2 a point
    ES    E-mini S&P 500         0.25 tick    $12.50/tick   $50 a point
    MES   Micro S&P 500          0.25 tick    $1.25/tick    $5 a point

The micros are what a $50,000 account trades. One MNQ contract risks about $46
on a typical stop, so an account can size to the risk instead of being forced
into a position it cannot carry. One NQ contract on the same stop risks $460,
which on $50,000 is nearly 1% in a single contract with no ability to scale.

COSTS

Per contract, never per notional. Commission is roughly $1.50 round turn on the
E-mini and $1.00 on the micro, plus about a tick of slippage. On a typical stop
that is 0.026R against an ETF's 0.200R, and getting this wrong in either
direction has already cost this project once.
"""
import os
import numpy as np
import pandas as pd

from backtest.engine import Costs

ROOT = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(ROOT, "data", "store")

# ---------------------------------------------------------------------------
# contract specifications
# ---------------------------------------------------------------------------
CONTRACTS = {
    "NQ":  dict(name="E-mini Nasdaq 100",  tick=0.25, tick_value=5.00,
                commission_rt=1.50, per_point=20.0),
    "MNQ": dict(name="Micro Nasdaq 100",   tick=0.25, tick_value=0.50,
                commission_rt=1.00, per_point=2.0),
    "ES":  dict(name="E-mini S&P 500",     tick=0.25, tick_value=12.50,
                commission_rt=1.50, per_point=50.0),
    "MES": dict(name="Micro S&P 500",      tick=0.25, tick_value=1.25,
                commission_rt=1.00, per_point=5.0),
}


def costs_for(contract, slip_ticks=1.0):
    """Per-contract costs. Never a percentage of notional for futures."""
    c = CONTRACTS[contract]
    return Costs(per_contract=True, commission_rt=c["commission_rt"],
                 slip_ticks=slip_ticks, tick_size=c["tick"],
                 tick_value=c["tick_value"])


def cost_in_r(contract, entry, stop, slip_ticks=1.0):
    return costs_for(contract, slip_ticks).cost_in_r(entry, stop)


# ---------------------------------------------------------------------------
# data sources, and how far each can be trusted
# ---------------------------------------------------------------------------
SOURCES = {
    "nq": {
        "contract": "MNQ",
        "real": ("nq_5m.parquet", "CME via Yahoo, the actual contract"),
        "proxy": ("nasdaq_duka_5m.parquet", "Dukascopy index CFD"),
        "index": ("nsxusd_1m.parquet", "HistData cash index, 1-minute"),
    },
    "es": {
        "contract": "MES",
        "real": ("es_5m.parquet", "CME via Yahoo, the actual contract"),
        "proxy": ("sp500_duka_5m.parquet", "Dukascopy index CFD"),
        "index": (None, None),
    },
}


def load(market, prefer="proxy"):
    """Return (frame, label, is_real_contract).

    `prefer` picks the source; "real" gives the actual contract where we have
    it, which is only ten weeks and is the reference rather than the sample.
    """
    src = SOURCES.get(market)
    if src is None:
        return None, "unknown market", False
    order = ([src["real"], src["proxy"], src["index"]] if prefer == "real"
             else [src["proxy"], src["index"], src["real"]])
    for fname, label in order:
        if not fname:
            continue
        p = os.path.join(STORE, fname)
        if os.path.exists(p):
            df = pd.read_parquet(p)
            if df is None or df.empty:
                continue
            if df.index.tz is None:
                df.index = df.index.tz_localize("UTC")
            is_real = label and "CME" in label
            return df, label, bool(is_real)
    return None, "no data stored", False


def size_for(contract, account, risk_pct, stop_points):
    """How many contracts, from the stop distance. Risk first, size last."""
    c = CONTRACTS[contract]
    per_ct = stop_points * c["per_point"]
    if per_ct <= 0:
        return 0, 0.0
    n = int((account * risk_pct / 100) // per_ct)
    return n, n * per_ct


def report():
    print("=" * 78)
    print("  FUTURES CONFIGURATION")
    print("=" * 78)
    print(f"\n  {'contract':<6} {'name':<22} {'per point':>10} {'cost/R at a 0.08% stop':>24}")
    for k, c in CONTRACTS.items():
        px = 29_000.0
        cr = cost_in_r(k, px, px * 0.9992)
        print(f"  {k:<6} {c['name']:<22} ${c['per_point']:>9,.0f} {cr:>23.3f}R")

    print(f"\n  {'market':<6} {'source in use':<38} {'bars':>9} {'span':>22}")
    for m in SOURCES:
        df, label, real = load(m)
        if df is None:
            print(f"  {m:<6} {label:<38} {'-':>9}")
            continue
        tag = "REAL CONTRACT" if real else "proxy"
        print(f"  {m:<6} {label:<38} {len(df):>9,} "
              f"{df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}")
        print(f"  {'':<6} {'':<38} {tag}")

    print(f"\n  SIZING, $50,000 account, 1% risk, 40-point stop")
    for k in ("MNQ", "NQ", "MES", "ES"):
        n, risked = size_for(k, 50_000, 1.0, 40)
        note = "" if n else "   <- cannot size to the risk"
        print(f"    {k:<5} {n:>3} contract(s), ${risked:>7,.0f} risked{note}")
    print("\n" + "=" * 78)


if __name__ == "__main__":
    report()
