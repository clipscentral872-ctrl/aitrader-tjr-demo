"""Where the stop and the target go, using real highs and lows.

The first version of this file tested arbitrary placements: two times risk,
three times risk, an ATR multiple. Chris pointed out that this is not how
either course teaches it, and he is right. In ICT terms a stop and a target
are not distances, they are LOCATIONS. Specific highs and lows where orders
actually rest.

    stop     beyond the high or low that proves the idea wrong
    target   at the high or low where the opposing orders are sitting

So every option here is a real structural point taken from the chart, and the
arbitrary multiples are gone.

There is a specific reason to expect this to matter more than the confluence
questions. Stop distance is the denominator of every R in the system. It also
sets the cost burden, which is how the Bitcoin problem hid for so long. Moving
a stop changes every number; adding a filter only changes which rows survive.

And one placement comes straight from the video. TJR enters at the inverse fair
value gap rather than waiting for the break of structure:

    "This makes my stop loss literally two times the size and now makes me have
     a risk-to-reward that's not even 1:0.5 ... versus if I take this trade up
     here, if I'm risking $1,000, I'll be able to make $1,300."

    "I use this confluence almost every single day, almost more than break of
     structure, because more often than not it happens before break of
     structure."

That is not a filter, which is how it was tested earlier and why it looked
useless. It is an earlier entry that halves the risk on the same idea.

    python placement_study.py --market eurusd --confirm qqq
"""
import argparse, dataclasses, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from engine import structure as S
from backtest.engine import run as bt_run
from backtest.guard import assess, Ledger, expected_best_by_luck
from evaluate import get_data
from tjr_study import SESSIONS


def _context(df, cfg):
    """Swings and named levels, computed once and shared by every placement."""
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    int_sw = S.find_swings(h, l, cfg.swing_left, cfg.swing_right)
    ext_sw = S.find_swings(h, l, cfg.ext_left, cfg.ext_right)
    levels = S.session_levels(df.index, h, l)
    return h, l, c, int_sw, ext_sw, levels


def _swing_beyond(swings, bar, price, side, n=30):
    """The nearest confirmed swing sitting the wrong side of the trade,
    which is the point that would prove it wrong."""
    kind = "high" if side == "short" else "low"
    known = S.known_tail(swings, bar, n)
    cands = [x.price for x in known if x.kind == kind and
             (x.price > price if side == "short" else x.price < price)]
    if not cands:
        return None
    return min(cands) if side == "short" else max(cands)


def _level_target(levels, bar, price, side, min_dist_pct=0.05):
    """The nearest NAMED liquidity level ahead: previous day, session, week."""
    want = "low" if side == "short" else "high"
    pool = S.levels_at(levels, bar)
    cands = [p["price"] for p in pool if p["kind"] == want and
             (p["price"] < price if side == "short" else p["price"] > price)
             and abs(p["price"] - price) / price * 100 >= min_dist_pct]
    if not cands:
        return None
    return max(cands) if side == "short" else min(cands)


def reprice(setups, ctx, stop_mode, target_mode, rr_cap=6.0, min_rr=0.5):
    """Same entries, stops and targets moved to different real levels."""
    h, l, c, int_sw, ext_sw, levels = ctx
    out = []
    for s in setups:
        i, entry, side = s.bar, s.entry, s.side

        # ---- stop: a point that proves the idea wrong -------------------
        if stop_mode == "swept extreme":
            stop = s.stop                     # what the engine has always done
        elif stop_mode == "internal swing":
            stop = _swing_beyond(int_sw, i, entry, side)
        elif stop_mode == "external swing":
            stop = _swing_beyond(ext_sw, i, entry, side)
        elif stop_mode == "session level":
            k = "high" if side == "short" else "low"
            pool = S.levels_at(levels, i)
            cands = [p["price"] for p in pool if p["kind"] == k and
                     (p["price"] > entry if side == "short" else p["price"] < entry)]
            stop = (min(cands) if side == "short" else max(cands)) if cands else None
        else:
            stop = s.stop
        if stop is None:
            continue
        if side == "short" and stop <= entry:
            continue
        if side == "long" and stop >= entry:
            continue
        risk = abs(entry - stop)
        if risk <= 0:
            continue

        # ---- target: where the opposing orders rest ---------------------
        if target_mode == "draw on liquidity":
            target = s.target                 # the engine's own choice
        elif target_mode == "swept level":
            target = s.swept_price or None
        elif target_mode == "named level":
            target = _level_target(levels, i, entry, side)
        elif target_mode == "opposite swing":
            kind = "low" if side == "short" else "high"
            known = S.known_tail(ext_sw, i, 30)
            cands = [x.price for x in known if x.kind == kind and
                     (x.price < entry if side == "short" else x.price > entry)]
            target = (max(cands) if side == "short" else min(cands)) if cands else None
        elif target_mode == "stacked liquidity":
            target = S.stacked_target(int_sw, i, entry,
                                      "bear" if side == "short" else "bull")
        else:
            target = s.target
        if target is None:
            continue
        if side == "short" and target >= entry:
            continue
        if side == "long" and target <= entry:
            continue

        rr = abs(target - entry) / risk
        if rr > rr_cap:
            target = (entry - risk * rr_cap if side == "short"
                      else entry + risk * rr_cap)
            rr = rr_cap
        if rr < min_rr:
            continue
        out.append(dataclasses.replace(s, stop=float(stop),
                                       target=float(target), rr=float(rr)))
    return out


STOPS = ["swept extreme", "internal swing", "external swing", "session level"]
TARGETS = ["draw on liquidity", "swept level", "named level",
           "opposite swing", "stacked liquidity"]


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
    led = Ledger()
    led.reset()

    cut = int(len(df) * 0.6)
    train, test = df.iloc[:cut], df.iloc[cut:]

    # min_rr is low here on purpose: a nearer target must be allowed to be
    # measured rather than rejected before it is seen
    base = Config(min_stop_pct=ms, max_stop_pct=1.5, min_rr=0.5, max_rr=10.0,
                  htf_bias=True, require_real_draw=True, require_premium=True)
    setups = find_setups(train, base, session_filter=filt)

    print("=" * 78)
    print(f"  STOP AND TARGET PLACEMENT  {a.market.upper()}")
    print(f"  {len(setups)} entries, identical throughout. Only the levels change.")
    print(f"  search {train.index[0]:%Y-%m-%d} to {train.index[-1]:%Y-%m-%d}, "
          f"held back {test.index[0]:%Y-%m-%d} to {test.index[-1]:%Y-%m-%d}")
    print("=" * 78)
    if not setups:
        print("  no setups")
        return

    ctx = _context(train, base)
    print(f"\n  {'stop at':<17} {'target at':<20} {'trades':>7} {'mean R':>9} "
          f"{'win %':>7} {'avg R:R':>8}")
    rows = []
    for sm in STOPS:
        for tm in TARGETS:
            ss = reprice(setups, ctx, sm, tm)
            if not ss:
                continue
            tr, _ = bt_run(train, ss, costs)
            if len(tr) < a.min_trades:
                continue
            r = np.array([t.r for t in tr])
            rr = float(np.mean([x.rr for x in ss]))
            print(f"  {sm:<17} {tm:<20} {len(r):>7} {r.mean():>+9.3f} "
                  f"{(r > 0).mean()*100:>7.1f} {rr:>8.2f}")
            led.record(a.market, f"{sm}/{tm}")
            rows.append((float(r.mean()), len(r), sm, tm))

    if not rows:
        print("\n  nothing with enough trades")
        return

    rows.sort(key=lambda x: -x[0])
    k = led.count(a.market)
    luck = expected_best_by_luck(k, 1.0, a.min_trades)
    bm, bn, bsm, btm = rows[0]
    print(f"\n  {k} placements tested. Luck across that many produces "
          f"about {luck:+.3f}R.")

    print("\n" + "-" * 78)
    print("  THE HELD-OUT TEST")
    print(f"    best on search data: stop at {bsm}, target at {btm}")
    print(f"    {bm:+.3f}R over {bn} trades")

    s_test = find_setups(test, base, session_filter=filt)
    ctx_t = _context(test, base)
    ss = reprice(s_test, ctx_t, bsm, btm)
    holds = False
    if ss:
        tr, _ = bt_run(test, ss, costs)
        if len(tr) >= 30:
            arr = np.array([t.r for t in tr])
            v = assess(list(arr), dataset=f"{a.market}_holdout",
                       label=f"{bsm}/{btm}", ledger=Ledger())
            print(f"    on held-out data: {arr.mean():+.3f}R over {len(arr)} "
                  f"trades, win {(arr > 0).mean()*100:.0f}%")
            print(f"    {v.headline}")
            print(f"    decay: {bm - float(arr.mean()):+.3f}R")
            holds = v.is_edge and float(arr.mean()) > 0
        else:
            print(f"    {len(tr)} trades, too few")

    if a.confirm:
        print(f"\n  CONFIRMATION ON {a.confirm.upper()}")
        df2, c2, ms2, _ = get_data(a.confirm)
        if df2 is not None and not df2.empty:
            b2 = dataclasses.replace(base, min_stop_pct=ms2)
            s2 = find_setups(df2, b2, session_filter=SESSIONS.get(
                "TJR NY open only (08:30-11:30)"))
            ss2 = reprice(s2, _context(df2, b2), bsm, btm)
            if ss2:
                tr2, _ = bt_run(df2, ss2, c2)
                if len(tr2) >= 30:
                    a2 = np.array([t.r for t in tr2])
                    print(f"    {a2.mean():+.3f}R over {len(a2)} trades")
                    if a2.mean() <= 0:
                        print("    Negative on a market it was not fitted to.")
                        holds = False
                else:
                    print(f"    {len(tr2)} trades, too few")
                    holds = False

    print("\n" + "=" * 78)
    if holds:
        print("  A placement survived. Put it through evaluate.py next.")
    else:
        print("  No placement survived. Stop distance moves every number in the")
        print("  system, so this was the right place to look. The answer holds.")
    print("=" * 78)


if __name__ == "__main__":
    main()
