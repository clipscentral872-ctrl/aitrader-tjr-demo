"""Efficiency of the pullback, and internal versus external structure.

Both courses spend real time on these and the engine implements both, but
neither has ever been varied. They sit at defaults nobody chose deliberately:

    min_efficiency = 0.80      the pullback must retrace 80% into the zone
    swing_left/right = 2       internal structure
    ext_left/right = 6         external structure

There is a specific reason to suspect the efficiency setting is doing nothing.
The scored tag `full_efficiency`, which fires at 0.95 or better, appears on
99.5% of EURUSD setups and 99.6% of QQQ setups. If nearly every setup already
retraces 95% or more, then a filter demanding 80% is not filtering. It is
decoration, and it may be excluding the very setups worth taking.

Internal versus external structure is the other half. External structure is the
impulse leg; internal structure is what happens inside the pullback. The widths
that separate them decide what counts as an impulse at all, and 2 against 6 is
an arbitrary ratio.

Unlike the confluence combinations, these are structural parameters that shape
which setups exist, not another way of slicing the same setups. That makes this
a different question rather than a further search over the same ground, though
it is still a search and is charged as one.

    python structure_study.py --market eurusd --confirm qqq
"""
import argparse, dataclasses, itertools, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run
from backtest.guard import assess, Ledger, expected_best_by_luck
from evaluate import get_data
from tjr_study import SESSIONS

EFF = [0.0, 0.50, 0.62, 0.705, 0.80, 0.90]     # 0 means the filter is off
INTERNAL = [1, 2, 3]
EXTERNAL = [4, 6, 9, 12]


def run_one(df, costs, base, session, **over):
    cfg = dataclasses.replace(base, **over)
    s = find_setups(df, cfg, session_filter=session)
    if not s:
        return None, [], 0
    tr, _ = bt_run(df, s, costs)
    return ([t.r for t in tr] or None), s, len(tr)


def line(label, r, width=34):
    if not r or len(r) < 30:
        print(f"    {label:<{width}} {len(r) if r else 0:>6}   too few to read")
        return None
    a = np.array(r)
    print(f"    {label:<{width}} {len(a):>6} {a.mean():>+9.3f}R "
          f"win {(a > 0).mean()*100:>5.1f}%")
    return float(a.mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="eurusd")
    ap.add_argument("--confirm", default="qqq")
    ap.add_argument("--session", default="engine default (09:30-12:30 NY)")
    ap.add_argument("--min-trades", type=int, default=60)
    a = ap.parse_args()

    df, costs, ms, _ = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return
    filt = SESSIONS.get(a.session)
    base = Config(min_stop_pct=ms, max_stop_pct=1.5, min_rr=3.0, max_rr=5.0,
                  htf_bias=True, require_real_draw=True, require_premium=True)

    led = Ledger()
    led.reset()
    cut = int(len(df) * 0.6)
    train, test = df.iloc[:cut], df.iloc[cut:]

    print("=" * 78)
    print(f"  STRUCTURE STUDY  {a.market.upper()}")
    print(f"  search {train.index[0]:%Y-%m-%d} to {train.index[-1]:%Y-%m-%d}, "
          f"held back {test.index[0]:%Y-%m-%d} to {test.index[-1]:%Y-%m-%d}")
    print("=" * 78)

    # ---- 1. how much does efficiency actually bind? -----------------------
    print("\n1. EFFICIENCY OF THE PULLBACK")
    print("   Does demanding a deeper retrace help, or just remove trades?\n")
    print(f"    {'requirement':<34} {'trades':>6}")
    for e in EFF:
        over = ({"require_efficiency": False} if e == 0
                else {"require_efficiency": True, "min_efficiency": e})
        r, s, n = run_one(train, costs, base, filt, **over)
        lbl = "no requirement" if e == 0 else f"pullback reaches {e:.0%}"
        line(lbl, r)
        led.record(a.market, f"efficiency {e}")

    # ---- 2. internal vs external widths -----------------------------------
    print("\n2. INTERNAL AGAINST EXTERNAL STRUCTURE")
    print("   External is the impulse leg, internal is the move inside the")
    print("   pullback. The ratio between them decides what counts as an")
    print("   impulse at all.\n")
    print(f"    {'internal / external':<34} {'trades':>6}")
    grid = []
    for i, e in itertools.product(INTERNAL, EXTERNAL):
        if e <= i * 1.5:
            continue
        r, s, n = run_one(train, costs, base, filt,
                          swing_left=i, swing_right=i, ext_left=e, ext_right=e)
        m = line(f"internal {i}, external {e}", r)
        led.record(a.market, f"structure {i}/{e}")
        if m is not None and len(r) >= a.min_trades:
            grid.append((m, len(r), i, e, r))

    if not grid:
        print("\n  nothing produced enough trades to judge")
        return

    # ---- 3. the best, tested where it was not found -----------------------
    grid.sort(key=lambda x: -x[0])
    k = led.count(a.market)
    sd = float(np.std(grid[0][4], ddof=1))
    luck = expected_best_by_luck(k, sd, a.min_trades)
    bm, bn, bi, be, _ = grid[0]

    print("\n" + "-" * 78)
    print(f"  {k} settings tested. Luck alone across that many produces "
          f"about {luck:+.3f}R.")
    print(f"\n  best on the search data: internal {bi}, external {be}  "
          f"{bm:+.3f}R over {bn} trades")
    if bm < luck:
        print("  That is already under the luck line, so the held-out test is")
        print("  a formality rather than a hope.")

    print("\n  THE HELD-OUT TEST")
    r_test, _, _ = run_one(test, costs, base, filt,
                           swing_left=bi, swing_right=bi,
                           ext_left=be, ext_right=be)
    holds = False
    if not r_test or len(r_test) < 30:
        print(f"    {len(r_test) if r_test else 0} trades, too few to judge")
    else:
        arr = np.array(r_test)
        v = assess(list(arr), dataset=f"{a.market}_holdout",
                   label=f"structure {bi}/{be}", ledger=Ledger())
        print(f"    {arr.mean():+.3f}R over {len(arr)} trades, "
              f"win {(arr > 0).mean()*100:.0f}%")
        print(f"    {v.headline}")
        print(f"    decay from search to held out: {bm - float(arr.mean()):+.3f}R")
        holds = v.is_edge and float(arr.mean()) > 0

    if a.confirm:
        print(f"\n  CONFIRMATION ON {a.confirm.upper()}")
        df2, c2, ms2, _ = get_data(a.confirm)
        if df2 is not None and not df2.empty:
            b2 = dataclasses.replace(base, min_stop_pct=ms2)
            r2, _, _ = run_one(df2, c2, b2,
                               SESSIONS.get("TJR NY open only (08:30-11:30)"),
                               swing_left=bi, swing_right=bi,
                               ext_left=be, ext_right=be)
            if not r2 or len(r2) < 30:
                print(f"    {len(r2) if r2 else 0} trades, too few")
                holds = False
            else:
                a2 = np.array(r2)
                print(f"    {a2.mean():+.3f}R over {len(a2)} trades")
                if a2.mean() <= 0:
                    print("    Negative on a market it was not fitted to.")
                    holds = False

    print("\n" + "=" * 78)
    print("  Structure settings survived." if holds else
          "  Nothing survived. These were never tuned, so it was worth asking,")
    print("=" * 78 if holds else
          "  but the answer is the same as everywhere else.\n" + "=" * 78)


if __name__ == "__main__":
    main()
