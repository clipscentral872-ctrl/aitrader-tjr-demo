"""Test the three things TJR actually uses when narrating a live trade.

Taken from him trading in front of a student, which is more honest evidence
than the teaching segments: it is what he reaches for under pressure.

His recap of the winning trade, verbatim:

    "came in with the bearish bias. It got invalidated once we swept the lows,
     put in that SMT. We inverse this five minute pretty strongly. Uh, got that
     pullback. And inside that pullback, we also got a one minute inversion."

And earlier, live:

    "ON THE HIGH TIME FRAMES. WE'RE BULLISH. Inverse this gap. NASDAQ took out
     London highs. We still have Asia session highs up here."

Three things in there the engine never had:

  1. INVERSE FAIR VALUE GAP. He mentions it twice in one recap. A gap price has
     closed through flips polarity and becomes resistance instead of support.
     An ordinary gap and an inverted gap point in OPPOSITE directions.

  2. LONDON LEVELS. He names London highs directly. The engine had Asia and
     previous day, but not London.

  3. 1:3 RISK TO REWARD. He says "1:3 risk-to-reward ratio" on the winning
     trade. config/tuned.json caps reward at 1.5 times risk, a number tuned
     against the artefact data.

    python tjr_live_study.py --market qqq
"""
import argparse, dataclasses, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from engine import structure as S
from backtest.engine import run as bt_run
from backtest.guard import assess, Ledger
from evaluate import get_data
from tjr_study import SESSIONS


def ifvg_agrees(h, l, c, setups, lookback=60):
    """For each setup, is there an inverted gap pointing the same way?"""
    out = []
    for s in setups:
        want = "bear" if s.side == "short" else "bull"
        inv = S.inverse_gaps(h, l, c, s.bar, lookback=lookback)
        hit = any(g["dir"] == want for g in inv)
        # and the stricter version: price is sitting IN one right now
        inside = S.in_inverse_gap(inv, s.entry, want) is not None
        out.append((hit, inside))
    return out


def show(label, rs, led, market):
    if len(rs) < 25:
        print(f"    {label:<30} {len(rs):>6} trades   too few to read")
        return None
    a = np.array(rs)
    v = assess(list(a), dataset=market, label=label, ledger=led)
    tag = "clears the bar" if v.is_edge else "inside its own noise"
    print(f"    {label:<30} {len(a):>6} {a.mean():>+9.3f}R "
          f"win {(a > 0).mean()*100:>4.1f}%   {tag}")
    return float(a.mean())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="qqq")
    ap.add_argument("--session", default="TJR NY open only (08:30-11:30)")
    ap.add_argument("--reset-ledger", action="store_true")
    a = ap.parse_args()

    led = Ledger()
    if a.reset_ledger:
        led.reset()

    df, costs, ms, _ = get_data(a.market)
    filt = SESSIONS.get(a.session)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)

    print("=" * 74)
    print(f"  WHAT TJR ACTUALLY USES LIVE   {a.market.upper()}")
    print(f"  session: {a.session}")
    print("=" * 74)

    base = Config(min_stop_pct=ms, max_stop_pct=1.5, min_rr=1.0, max_rr=1.5,
                  htf_bias=True, require_real_draw=True, require_premium=True,
                  use_session_levels=True)

    # ---- 1. reward to risk -------------------------------------------------
    print("\n1. HOW FAR HE TARGETS")
    print("   He says 1:3 on the winning trade. The engine caps at 1.5.\n")
    best_rr, best_m = 1.5, -9e9
    for rr in (1.5, 2.0, 2.5, 3.0):
        cfg = dataclasses.replace(base, max_rr=rr)
        s = find_setups(df, cfg, session_filter=filt)
        if not s:
            print(f"    max {rr}:1                       no setups")
            continue
        tr, _ = bt_run(df, s, costs)
        m = show(f"max reward {rr}:1", [t.r for t in tr], led, a.market)
        if m is not None and m > best_m:
            best_rr, best_m = rr, m

    # ---- 2. inverse fair value gaps ---------------------------------------
    print(f"\n2. INVERSE FAIR VALUE GAP   (using max {best_rr}:1 from above)")
    print("   A gap price closed through, now pointing the other way.\n")
    cfg = dataclasses.replace(base, max_rr=best_rr)
    setups = find_setups(df, cfg, session_filter=filt)
    tr, _ = bt_run(df, setups, costs)
    flags = ifvg_agrees(h, l, c, setups[:len(tr)])

    agree = [t.r for t, (hit, _) in zip(tr, flags) if hit]
    disagree = [t.r for t, (hit, _) in zip(tr, flags) if not hit]
    inside = [t.r for t, (_, ins) in zip(tr, flags) if ins]
    show("an inverted gap agrees", agree, led, a.market)
    show("none agrees", disagree, led, a.market)
    show("entry sits INSIDE one", inside, led, a.market)
    show("everything", [t.r for t in tr], led, a.market)
    if len(agree) >= 25 and len(disagree) >= 25:
        print(f"\n    inverted gap agreement is worth "
              f"{np.mean(agree) - np.mean(disagree):+.3f}R per trade")

    # ---- 3. session levels as pools ---------------------------------------
    print("\n3. SESSION LEVELS AS THE THING BEING SWEPT")
    print("   London and Asia highs and lows, which he names constantly.\n")
    for label, over in (("session levels ON", {"use_session_levels": True}),
                        ("session levels OFF", {"use_session_levels": False})):
        cfg2 = dataclasses.replace(base, max_rr=best_rr, **over)
        s2 = find_setups(df, cfg2, session_filter=filt)
        if not s2:
            print(f"    {label:<30}   no setups")
            continue
        tr2, _ = bt_run(df, s2, costs)
        show(label, [t.r for t in tr2], led, a.market)

    # ---- which pool actually pays -----------------------------------------
    print("\n   which kind of level, when swept, leads to the best trade")
    by_src = {}
    for t, s in zip(tr, setups):
        src = next((x for x in (s.tags or "").split("|") if "_" in x), "other")
        by_src.setdefault(src, []).append(t.r)
    for src, rs in sorted(by_src.items(), key=lambda kv: -len(kv[1]))[:8]:
        if len(rs) < 20:
            continue
        arr = np.array(rs)
        print(f"    {src:<30} {len(arr):>6} {arr.mean():>+9.3f}R")

    print("\n" + "=" * 74)
    print(f"  {led.count(a.market)} hypotheses tested on {a.market}. Anything")
    print("  promising here has to repeat on a market it was not found on.")
    print("=" * 74)


if __name__ == "__main__":
    main()
