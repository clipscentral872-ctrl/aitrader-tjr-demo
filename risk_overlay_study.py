"""Does the overlay actually raise the risk this system can carry?

Reducing drawdown is only worth something if it converts into risk capacity.
The chain has to hold all the way:

    smaller drawdown  ->  larger risk survives the limit  ->  more income

If it stops at the first step, the overlay is a comfort blanket. Reducing
drawdown by trading smaller is trivially easy and completely pointless: halving
size halves the drawdown and halves the return, and the safe risk level moves
by exactly the amount needed to cancel it out.

So the measurement here is not drawdown. It is the largest risk that keeps 95%
of bootstrapped paths inside a 10% drawdown, and the money that risk produces.
That number is scale-invariant, which is what makes it honest.

    python risk_overlay_study.py --market eurusd
"""
import argparse, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run
from backtest import bootstrap
from paper.volsize import VolTarget, DrawdownThrottle, combined
from evaluate import get_data
from tjr_study import SESSIONS

LIMIT = 10.0


def scaled_returns(trades, closes, vt, th=None, start_equity=100_000.0,
                   risk_pct=1.0):
    """Per-trade R, multiplied by the sizing the overlay would have applied.

    The drawdown throttle has to be walked forward: its multiplier depends on
    the equity curve the previous trades produced, so it cannot be computed in
    one pass like the volatility scale.
    """
    out = []
    equity, peak = start_equity, start_equity
    for t in trades:
        i = t.entry_bar
        lo = max(0, i - 240)
        vs = vt.scale(closes[lo:i + 1])
        ds = th.scale(equity, peak) if th else 1.0
        sc = combined(vs, ds)
        out.append(t.r * sc)
        equity *= 1 + (risk_pct / 100) * t.r * sc
        peak = max(peak, equity)
    return np.array(out)


def assess(label, r, risk_pct_for_report=None):
    """Drawdown is the headline everywhere else. Here it is the safe risk."""
    if len(r) < 40:
        print(f"  {label:<26} too few trades")
        return None
    safe = bootstrap.risk_for_drawdown(list(r), LIMIT)
    res = bootstrap.run(list(r), risk_pct=safe, runs=3000, block=5)
    if res is None:
        return None
    mean_r = float(np.mean(r))
    print(f"  {label:<26} {len(r):>5} {mean_r:>+8.3f} {safe:>9.3f}% "
          f"{res.median_return:>+11.2f}% {res.median_dd:>9.1f}% "
          f"{res.prob_profit*100:>7.1f}%")
    return {"safe": safe, "median": res.median_return, "mean_r": mean_r}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="eurusd")
    ap.add_argument("--session", default="engine default (09:30-12:30 NY)")
    ap.add_argument("--equity", type=float, default=100_000.0)
    a = ap.parse_args()

    df, costs, ms, _ = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return
    filt = SESSIONS.get(a.session)
    cfg = Config(min_stop_pct=ms, max_stop_pct=1.5, min_rr=3.0, max_rr=5.0,
                 htf_bias=True, require_real_draw=True, require_premium=True)
    setups = find_setups(df, cfg, session_filter=filt)
    trades, _ = bt_run(df, setups, costs)
    if len(trades) < 60:
        print(f"only {len(trades)} trades, not enough to judge sizing")
        return

    closes = df["close"].to_numpy(float)
    base = np.array([t.r for t in trades])

    print("=" * 88)
    print(f"  RISK OVERLAY  {a.market.upper()}   {len(trades)} trades")
    print("=" * 88)
    print("\n  The number that matters is 'safe risk': the largest risk per")
    print("  trade keeping 95% of paths inside a 10% drawdown. Everything else")
    print("  can be faked by simply trading smaller.\n")
    print(f"  {'sizing':<26} {'n':>5} {'mean R':>8} {'safe risk':>10} "
          f"{'median ret':>12} {'median DD':>10} {'up?':>8}")

    results = {}
    results["fixed"] = assess("fixed fraction (now)", base)

    for st in (0.5, 1.0):
        vt = VolTarget(enabled=True, strength=st)
        r = scaled_returns(trades, closes, vt)
        results[f"vol{st}"] = assess(f"vol target, strength {st}", r)

    vt = VolTarget(enabled=True, strength=1.0)
    th = DrawdownThrottle(enabled=True)
    r = scaled_returns(trades, closes, vt, th)
    results["vol+throttle"] = assess("vol target + throttle", r)

    th_only = DrawdownThrottle(enabled=True)
    r = scaled_returns(trades, closes, VolTarget(enabled=False), th_only)
    results["throttle"] = assess("throttle only", r)

    # ---- did it convert into money? ---------------------------------------
    fixed = results.get("fixed")
    if not fixed:
        return
    print("\n" + "-" * 88)
    print("  WHAT IT IS WORTH")
    print(f"  A ${a.equity:,.0f} account, at each overlay's own safe risk.\n")
    print(f"  {'sizing':<26} {'safe risk':>10} {'return a year':>15} "
          f"{'against fixed':>15}")
    n_year = len(trades) / max((df.index[-1] - df.index[0]).days / 365.25, 0.5)
    base_money = None
    for k, label in (("fixed", "fixed fraction (now)"),
                     ("vol0.5", "vol target, half strength"),
                     ("vol1.0", "vol target, full strength"),
                     ("vol+throttle", "vol target + throttle"),
                     ("throttle", "throttle only")):
        v = results.get(k)
        if not v:
            continue
        money = a.equity * (v["safe"] / 100) * v["mean_r"] * n_year
        if base_money is None:
            base_money = money
        delta = "" if k == "fixed" else f"{money - base_money:>+14,.0f}"
        print(f"  {label:<26} {v['safe']:>9.3f}% ${money:>13,.0f} {delta:>15}")

    print("\n" + "=" * 88)
    best = max((v for v in results.values() if v),
               key=lambda x: x["safe"] * x["mean_r"], default=None)
    if best and fixed and best["safe"] * best["mean_r"] > fixed["safe"] * fixed["mean_r"] * 1.1:
        print("  The overlay converts into real capacity: the same signal")
        print("  carries more risk inside the same drawdown limit.")
    else:
        print("  The overlay did NOT convert into capacity. It smooths the")
        print("  curve and the safe risk barely moves, which means the")
        print("  drawdown reduction was bought by trading smaller.")
    print(f"\n  Note: {n_year:.0f} trades a year. Nothing here creates an edge,")
    print("  and this strategy has not cleared evaluate.py. These figures show")
    print("  what the sizing does, not that the underlying signal is real.")
    print("=" * 88)


if __name__ == "__main__":
    main()
