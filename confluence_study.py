"""Does stacking the course confluences actually improve the odds?

This is the question Chris asked, and it deserves a real answer rather than a
plausible one. The strategy already SCORES eight named confluences on every
setup. Until now it never REQUIRED any of them: `min_confluences` was 0, so a
setup with one confluence was traded exactly like a setup with six.

Two things are tested here.

1. THE STACK. If the course reasoning is right, expectancy should climb as the
   requirement rises, and it should climb smoothly. A single lucky bucket at
   four confluences with nothing either side of it is noise. A monotonic trend
   across the whole range is a finding.

2. THE FILTERS THAT WERE SWITCHED OFF. config/tuned.json disabled higher
   timeframe bias and the draw-on-liquidity requirement. Both are course
   non-negotiables. They were switched off because they hurt performance on
   NSXUSD, which we now know was a manufactured feed. Settings tuned against
   bad data have no claim on us, so they get re-tested on real data.

Everything here is charged to the hypothesis ledger. Testing thirty
combinations and reporting the best one without paying for the search is the
mistake this whole system exists to prevent.

    python confluence_study.py --market qqq
    python confluence_study.py --market eurusd --reset-ledger
"""
import argparse, dataclasses, os, sys
from collections import Counter
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run
from backtest.guard import assess, Ledger, expected_best_by_luck
from evaluate import get_data
from live import ny_window

# every confluence the strategy names, in the language of the courses
TAGS = ["pool3+", "htf_trend", "complex_pullback", "full_efficiency",
        "engulf", "follow_through", "real_gap", "deep_pd"]

MEANING = {
    "pool3+":           "liquidity pool touched 3+ times (a stronger build-up)",
    "htf_trend":        "higher timeframe agrees with the direction",
    "complex_pullback": "the internal retrace was a proper complex pullback",
    "full_efficiency":  "the pullback reached 95%+ back into the zone",
    "engulf":           "the entry candle engulfed the one before it",
    "follow_through":   "the candle closed near its extreme, not into the wick",
    "real_gap":         "the fair value gap is a meaningful size, not a hair",
    "deep_pd":          "deep in premium (for shorts) or discount (for longs)",
}


def run_cfg(df, costs, base, ledger, market, label, **over):
    cfg = dataclasses.replace(base, **over)
    setups = find_setups(df, cfg, session_filter=ny_window)
    if not setups:
        return None, [], []
    trades, _ = bt_run(df, setups, costs)
    r = [t.r for t in trades]
    if not r:
        return None, setups, []
    v = assess(r, dataset=market, label=label, ledger=ledger)
    return v, setups, r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="qqq")
    ap.add_argument("--reset-ledger", action="store_true")
    a = ap.parse_args()

    df, costs, ms, hours = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return

    led = Ledger()
    if a.reset_ledger:
        led.reset()

    # Start from the COURSE settings, not the ones tuned against the artefact.
    base = Config(min_stop_pct=ms, max_stop_pct=1.5, min_rr=1.0, max_rr=1.5,
                  htf_bias=True, require_real_draw=True, require_premium=True,
                  min_confluences=0)

    print("=" * 72)
    print(f"  CONFLUENCE STUDY  {a.market.upper()}   {len(df):,} bars")
    print("=" * 72)

    # ---- how often does each confluence actually appear? ------------------
    setups = find_setups(df, base, session_filter=ny_window)
    print(f"\n{len(setups)} setups with every course filter ON\n")
    if not setups:
        print("  Nothing passes the full course rules on this market. That is")
        print("  itself the answer: the rules as written are too strict here.")
        return

    counts = Counter()
    for s in setups:
        for t in (s.tags or "").split("|"):
            if t:
                counts[t] += 1
    print("  how often each confluence shows up")
    for t in TAGS:
        pct = counts[t] / len(setups) * 100
        print(f"    {t:<18} {counts[t]:>5}  {pct:>5.1f}%   {MEANING[t]}")

    # ---- does requiring more of them help? --------------------------------
    print("\n" + "-" * 72)
    print("  REQUIRING A STACK")
    print(f"    {'need':>5} {'setups':>7} {'trades':>7} {'mean R':>9} {'win %':>7}   verdict")
    stack = []
    for k in range(0, 7):
        v, ss, r = run_cfg(df, costs, base, led, a.market,
                           f"min_confluences={k}", min_confluences=k)
        if v is None:
            print(f"    {k:>5} {len(ss):>7} {0:>7}   no trades")
            continue
        arr = np.array(r)
        tag = "clears the bar" if v.is_edge else "inside its own noise"
        print(f"    {k:>5} {len(ss):>7} {len(r):>7} {arr.mean():>+9.3f} "
              f"{(arr > 0).mean()*100:>7.1f}   {tag}")
        stack.append((k, float(arr.mean()), len(r)))

    # ---- each confluence on its own ---------------------------------------
    print("\n" + "-" * 72)
    print("  EACH CONFLUENCE ALONE (setups carrying it, versus setups without)")
    print(f"    {'confluence':<18} {'with':>13} {'without':>13}   {'difference':>11}")
    singles = []
    all_tr, _ = bt_run(df, setups, costs)
    for t in TAGS:
        with_r = [x.r for x, s in zip(all_tr, setups) if t in (s.tags or "")]
        wo_r = [x.r for x, s in zip(all_tr, setups) if t not in (s.tags or "")]
        if len(with_r) < 30 or len(wo_r) < 30:
            print(f"    {t:<18} too few either side to compare")
            continue
        mw, mo = float(np.mean(with_r)), float(np.mean(wo_r))
        led.record(a.market, f"tag {t}")
        print(f"    {t:<18} {mw:>+8.3f}R {len(with_r):>4} {mo:>+8.3f}R {len(wo_r):>4}"
              f"   {mw - mo:>+10.3f}R")
        singles.append((t, mw - mo, len(with_r)))

    # ---- the filters that had been switched off ---------------------------
    print("\n" + "-" * 72)
    print("  THE FILTERS TUNED OFF AGAINST THE ARTEFACT DATA")
    print(f"    {'setting':<34} {'trades':>7} {'mean R':>9}")
    for name, over in (
            ("course defaults (both ON)", {}),
            ("higher timeframe bias OFF", {"htf_bias": False}),
            ("draw on liquidity OFF", {"require_real_draw": False}),
            ("both OFF (what tuned.json ships)", {"htf_bias": False,
                                                  "require_real_draw": False}),
            ("premium/discount OFF too", {"htf_bias": False,
                                          "require_real_draw": False,
                                          "require_premium": False})):
        v, ss, r = run_cfg(df, costs, base, led, a.market, name, **over)
        if v is None:
            print(f"    {name:<34} {0:>7}   no trades")
            continue
        print(f"    {name:<34} {len(r):>7} {np.mean(r):>+9.3f}")

    # ---- the honest reckoning ---------------------------------------------
    print("\n" + "=" * 72)
    k = led.count(a.market)
    sd = float(np.std([t.r for t in all_tr], ddof=1)) if len(all_tr) > 2 else 1.0
    luck = expected_best_by_luck(k, sd, max(len(all_tr) // 4, 25))
    print(f"  {k} hypotheses tested on {a.market}. Across that many tries, the")
    print(f"  best result you would expect from luck alone is {luck:+.3f}R.")
    print()
    if stack:
        ms_ = [m for _, m, _ in stack]
        rising = all(ms_[i] <= ms_[i + 1] + 0.02 for i in range(len(ms_) - 1))
        best_k, best_m, best_n = max(stack, key=lambda x: x[1])
        if rising and best_m > luck:
            print("  Expectancy rises with the stack AND the best clears the luck")
            print("  bar. That is the shape a real effect makes. Re-test it on a")
            print("  market it was not found on before believing it.")
        elif best_m > luck:
            print(f"  The best bucket ({best_k} confluences, {best_m:+.3f}R on "
                  f"{best_n} trades) clears")
            print("  the luck bar, but the trend is not monotonic. One good bucket")
            print("  with worse ones either side is what cherry-picking looks like.")
        else:
            print("  No level of confluence stacking clears the luck bar. The")
            print("  confluences describe the setup well. They do not predict it.")
    print("=" * 72)


if __name__ == "__main__":
    main()
