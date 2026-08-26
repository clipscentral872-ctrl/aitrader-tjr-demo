"""Test the TJR concepts the engine was not using.

Two of them, both taken straight from his transcript.

1. SMT DIVERGENCE. The one confluence that brings information from outside the
   chart being traded. Every other confluence is another view of the same bars,
   which is why stacking them added so little. This compares QQQ against SPY,
   his Nasdaq versus S&P 500, and only counts when it lands on a sweep.

2. HIS SESSION TIMES. In his words, New York time:

       "1800 to 3 is Asia session. 3 to 8:30 London session.
        8:30 back to 1800 is New York session"

   The engine has only ever traded 09:30 to 12:30 New York. TJR's New York
   session opens at 08:30, an hour earlier, and he talks about London
   forty-six times across the course. Those windows have never been tested.

    python tjr_study.py
"""
import argparse, dataclasses, os, sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from engine import smt
from backtest.engine import run as bt_run
from backtest.guard import assess, Ledger, expected_best_by_luck
from evaluate import get_data
from live import ny_window

NY = "America/New_York"


def window(lo_h, lo_m, hi_h, hi_m):
    """A session filter in New York time, which is how TJR states everything."""
    def f(ts):
        if ts.tzinfo is None:
            ts = ts.tz_localize("UTC")
        t = ts.tz_convert(NY)
        mins = t.hour * 60 + t.minute
        lo, hi = lo_h * 60 + lo_m, hi_h * 60 + hi_m
        return lo <= mins < hi if lo < hi else (mins >= lo or mins < hi)
    return f


SESSIONS = {
    "engine default (09:30-12:30 NY)": ny_window,
    "TJR New York (08:30-18:00)":      window(8, 30, 18, 0),
    "TJR NY open only (08:30-11:30)":  window(8, 30, 11, 30),
    "TJR London (03:00-08:30)":        window(3, 0, 8, 30),
    "TJR Asia (18:00-03:00)":          window(18, 0, 3, 0),
    "London + New York":               lambda ts: (window(3, 0, 18, 0)(ts)),
}


def score(r, led, market, label):
    if len(r) < 25:
        return f"{len(r):>5} trades   too few to read"
    a = np.array(r)
    v = assess(list(a), dataset=market, label=label, ledger=led)
    tag = "clears the bar" if v.is_edge else "inside its own noise"
    return (f"{len(a):>5} trades  {a.mean():>+8.3f}R  "
            f"win {(a > 0).mean()*100:>4.1f}%   {tag}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="qqq")
    ap.add_argument("--partner", default="spy")
    ap.add_argument("--reset-ledger", action="store_true")
    a = ap.parse_args()

    led = Ledger()
    if a.reset_ledger:
        led.reset()

    df, costs, ms, _ = get_data(a.market)
    base = Config(min_stop_pct=ms, max_stop_pct=1.5, min_rr=1.0, max_rr=1.5,
                  htf_bias=True, require_real_draw=True, require_premium=True)

    print("=" * 74)
    print(f"  TJR CONCEPTS THE ENGINE WAS NOT USING   {a.market.upper()}")
    print("=" * 74)

    # ---- 1. sessions -------------------------------------------------------
    print("\n1. HIS SESSION WINDOWS")
    print("   The engine has only ever traded one three-hour slice of his day.\n")
    print(f"   {'session':<34} result")
    best_sess, best_mean = None, -9e9
    for name, filt in SESSIONS.items():
        s = find_setups(df, base, session_filter=filt)
        if not s:
            print(f"   {name:<34} no setups")
            continue
        tr, _ = bt_run(df, s, costs)
        r = [t.r for t in tr]
        print(f"   {name:<34} {score(r, led, a.market, name)}")
        if len(r) >= 25 and np.mean(r) > best_mean:
            best_sess, best_mean = (name, filt), float(np.mean(r))

    # ---- 2. SMT ------------------------------------------------------------
    print("\n2. SMT DIVERGENCE  (%s against %s)" % (a.market.upper(), a.partner.upper()))
    df2, _, _, _ = get_data(a.partner)
    if df2 is None or df2.empty:
        print("   no partner data, cannot test this")
        return

    A, B = smt.align(df, df2)
    print(f"   aligned on {len(A):,} shared bars "
          f"({A.index[0]:%Y-%m-%d} to {A.index[-1]:%Y-%m-%d})")
    divs = smt.detect(A, B, a.market.upper(), a.partner.upper())
    smt.summarise(divs, len(A))

    # setups on the aligned frame so bar indices line up with the divergences
    sess_name, sess_filt = best_sess if best_sess else ("engine default", ny_window)
    print(f"\n   using the best session above: {sess_name}\n")
    setups = find_setups(A, base, session_filter=sess_filt)
    if not setups:
        print("   no setups on the aligned frame")
        return
    tr, _ = bt_run(A, setups, costs)

    with_smt, without = [], []
    for t, s in zip(tr, setups):
        d = smt.agrees(divs, s.bar, s.side)
        (with_smt if d else without).append(t.r)

    print(f"   {'':<26} {'trades':>7} {'mean R':>9} {'win %':>7}")
    for label, rs in (("SMT agrees", with_smt), ("no SMT", without),
                      ("everything", [t.r for t in tr])):
        if not rs:
            continue
        arr = np.array(rs)
        print(f"   {label:<26} {len(arr):>7} {arr.mean():>+9.3f} "
              f"{(arr > 0).mean()*100:>7.1f}")

    if len(with_smt) >= 25 and len(without) >= 25:
        gap = float(np.mean(with_smt)) - float(np.mean(without))
        led.record(a.market, "smt divergence")
        print(f"\n   SMT is worth {gap:+.3f}R per trade here.")
        v = assess(with_smt, dataset=a.market, label="smt filtered", ledger=led)
        print(f"   {v.headline}")
        print(f"     {v.detail}")
    else:
        print("\n   Not enough on one side to compare.")

    k = led.count(a.market)
    print("\n" + "=" * 74)
    print(f"  {k} hypotheses tested on {a.market} so far. Anything found here")
    print("  still has to repeat on a market it was not found on.")
    print("=" * 74)


if __name__ == "__main__":
    main()
