"""TJR's method exactly as the guide states it, assembled and tested.

Not a variation on it. Every rule from Part 13 of the guide, applied together,
on the window he actually gives.

  1. POTENTIAL      price sweeps a marked level: session high or low, previous
                    day high or low, equal highs or lows, or a stack
  2. CONFIRMATION   a candle CLOSES beyond the recent swing point against the
                    sweep, or closes through a fair value gap
  3. CONTINUATION   price pulls back into a fair value gap OR into equilibrium
                    and respects it
  4. TARGET         a known liquidity pool, decided before entry

  "All four must be present. Three out of four is not a trade."

And the timing, which is the part the engine had wrong:

  09:30 - 09:50   watch only. He calls it the manipulation window and does
                  not trade it.
  from 09:50      look for the confirmation close on the five-minute
  by 10:30        "If nothing has set up by 10:30, close the platform for the
                  day."

That is a forty-minute entry window. Every previous test in this project used
six and a half hours and called it the New York open.

Three gaps between the guide and the engine, all fixed here:

  * the manipulation window was traded rather than watched
  * there was no 10:30 cutoff
  * step 3 accepted a fair value gap only, when the guide gives the gap OR
    equilibrium as alternatives

A fourth is tested rather than assumed: he reads structure on the FOUR-hour
chart, and the engine's higher-timeframe factor of 12 on five-minute bars is
one hour, not four.

    python tjr_exact.py
"""
import argparse, dataclasses, os, sys
import functools
print = functools.partial(print, flush=True)
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run, Costs
from backtest import bootstrap
from backtest.guard import assess, Ledger

NY = "America/New_York"


def window(lo_h, lo_m, hi_h, hi_m):
    def f(ts):
        t = (ts.tz_localize("UTC") if ts.tzinfo is None else ts).tz_convert(NY)
        m = t.hour * 60 + t.minute
        lo, hi = lo_h * 60 + lo_m, hi_h * 60 + hi_m
        return lo <= m < hi if lo < hi else (m >= lo or m < hi)
    return f


# His window, and the ones we had been using, for comparison
WINDOWS = {
    "TJR exact 09:50-10:30":      window(9, 50, 10, 30),
    "with manipulation 09:30-10:30": window(9, 30, 10, 30),
    "to 11:30":                   window(9, 50, 11, 30),
    "to 12:00":                   window(9, 50, 12, 0),
    "full NY 09:30-16:00":        window(9, 30, 16, 0),
}

# The guide's rules, as config. htf_factor 48 on five-minute bars is the
# FOUR-hour chart he reads structure on; 12 would be one hour.
TJR = dict(
    min_stop_pct=0.08, max_stop_pct=1.5,
    min_rr=0.4, max_rr=0.5,
    htf_bias=True, htf_factor=48,
    require_real_draw=True,          # step 4: a named pool or no trade
    require_premium=True,            # sells in premium, buys in discount
    use_session_levels=True,         # Asia, London, previous day
    use_equal_levels=True,           # equal highs and lows
    entry_mode="tjr",                # step 3: gap OR equilibrium
    require_valid_gap=True,          # a gap dies when a candle closes through
)


def score(seg, cfg, filt, costs, label, tag, led=None, market="nsxusd"):
    s = find_setups(seg, cfg, session_filter=filt)
    if not s:
        print(f"  {label:<34} {tag:>6}   no setups")
        return None
    tr, _ = bt_run(seg, s, costs)
    if len(tr) < 25:
        print(f"  {label:<34} {tag:>6} {len(tr):>7}   too few")
        return None
    r = np.array([t.r for t in tr])
    yrs = max((seg.index[-1] - seg.index[0]).days / 365.25, 0.5)
    safe = bootstrap.risk_for_drawdown(list(r), 10.0) if r.mean() > 0 else 0.0
    print(f"  {label:<34} {tag:>6} {len(r):>7} {len(r)/yrs:>5.0f} "
          f"{r.mean():>+8.3f} {(r > 0).mean()*100:>6.1f}% {safe:>7.3f}%")
    return {"r": r, "n": len(r), "per_yr": len(r) / yrs,
            "mean": float(r.mean()), "safe": safe}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="nsxusd")
    ap.add_argument("--account", type=float, default=50_000)
    a = ap.parse_args()

    from evaluate import get_data
    df, costs, ms, _ = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return
    cut = int(len(df) * 0.6)
    train, test = df.iloc[:cut], df.iloc[cut:]

    print("=" * 84)
    print(f"  TJR'S METHOD, WORD FOR WORD   {a.market.upper()}")
    print(f"  {len(df):,} bars   {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}")
    print("=" * 84)

    hdr = (f"  {'':<34} {'seg':>6} {'trades':>7} {'/yr':>5} {'exp R':>8} "
           f"{'win %':>7} {'safe':>8}")

    # ---- 1. his window against the ones we had been using -----------------
    print("\n1. THE ENTRY WINDOW")
    print("   His is forty minutes. Everything before this used six hours.\n")
    print(hdr)
    best = None
    for name, filt in WINDOWS.items():
        for tag, seg in (("train", train), ("TEST", test)):
            res = score(seg, Config(**TJR), filt, costs, name, tag)
            if tag == "TEST" and res and (best is None or res["mean"] > best[1]["mean"]):
                best = (name, res)
        print()

    # ---- 2. does step 3 as written matter? --------------------------------
    print("\n2. STEP 3 AS WRITTEN: GAP *OR* EQUILIBRIUM")
    print("   The engine accepted only the gap, so half his entries were")
    print("   invisible to it.\n")
    print(hdr)
    filt = WINDOWS["TJR exact 09:50-10:30"]
    for mode, label in (("bos_gap", "gap only (what we had)"),
                        ("tjr", "gap OR equilibrium (his rule)")):
        for tag, seg in (("train", train), ("TEST", test)):
            score(seg, dataclasses.replace(Config(**TJR), entry_mode=mode),
                  filt, costs, label, tag)
        print()

    # ---- 3. the four-hour chart -------------------------------------------
    print("\n3. WHICH HIGHER TIMEFRAME")
    print("   He reads structure on the 4-hour. The engine defaulted to 1-hour.\n")
    print(hdr)
    for factor, label in ((12, "1-hour bias (engine default)"),
                          (48, "4-hour bias (what he uses)"),
                          (288, "daily bias")):
        for tag, seg in (("train", train), ("TEST", test)):
            score(seg, dataclasses.replace(Config(**TJR), htf_factor=factor),
                  filt, costs, label, tag)
        print()

    # ---- what it is worth --------------------------------------------------
    if best:
        name, res = best
        print("\n" + "-" * 84)
        print(f"  BEST HELD-OUT WINDOW: {name}")
        led = Ledger()
        v = assess(list(res["r"]), dataset=a.market, label=name, ledger=led)
        print(f"    {v.headline}")
        print(f"    {v.detail}")
        money = a.account * (res["safe"] / 100) * res["mean"] * res["per_yr"] / 12
        print(f"\n    ${a.account:,.0f} at {res['safe']:.3f}% risk: "
              f"${money:,.0f} a month")
        print(f"    {res['per_yr']:.0f} trades a year, which is "
              f"{res['per_yr']/252:.2f} a day")
    print("\n" + "=" * 84)


if __name__ == "__main__":
    main()
