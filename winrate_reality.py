"""Win rate, and why raising it is the easiest useless thing in trading.

Chris asked whether the win rate can be got up. It can, trivially, and that is
the problem. Win rate is not a measure of skill, it is a dial you set when you
choose where the target goes.

Move the target closer and the win rate rises. Move it further and it falls.
The breakeven win rate for a given reward-to-risk is fixed by arithmetic:

    breakeven = 1 / (1 + reward-to-risk)

    target 0.5R  ->  needs 67% to break even
    target 1.0R  ->  needs 50%
    target 3.0R  ->  needs 25%
    target 5.0R  ->  needs 17%

So a 70% win rate at 0.5R and a 30% win rate at 3R are the same trader. Chasing
the first number while ignoring the second is how people run losing accounts for
years while telling themselves they win most of the time.

This demonstrates it on the project's own data rather than asserting it, and
then shows what does move the number that matters.

    python winrate_reality.py --market eurusd
"""
import argparse, dataclasses, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run
from evaluate import get_data
from tjr_study import SESSIONS


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="eurusd")
    ap.add_argument("--session", default="engine default (09:30-12:30 NY)")
    a = ap.parse_args()

    df, costs, ms, _ = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return
    filt = SESSIONS.get(a.session)

    print("=" * 82)
    print(f"  WIN RATE IS A DIAL, NOT A SCORE   {a.market.upper()}")
    print("=" * 82)
    print("\n  Identical setups throughout. The ONLY thing changing is where")
    print("  the target sits. Watch the win rate move and the expectancy not.\n")
    print(f"  {'target':>8} {'trades':>7} {'win %':>8} {'breakeven':>11} "
           f"{'margin':>8} {'expectancy':>12} {'total R':>9}")

    rows = []
    for rr in (0.5, 1.0, 1.5, 2.0, 3.0, 5.0, 8.0):
        cfg = Config(min_stop_pct=ms, max_stop_pct=1.5,
                     min_rr=min(rr, 1.0), max_rr=rr,
                     htf_bias=True, require_real_draw=True,
                     require_premium=True)
        s = find_setups(df, cfg, session_filter=filt)
        if not s:
            continue
        tr, _ = bt_run(df, s, costs)
        if len(tr) < 40:
            continue
        r = np.array([t.r for t in tr])
        win = float((r > 0).mean() * 100)
        be = 100.0 / (1.0 + rr)
        rows.append((rr, len(r), win, be, float(r.mean()), float(r.sum())))
        print(f"  {rr:>7.1f}R {len(r):>7} {win:>7.1f}% {be:>10.1f}% "
              f"{win - be:>+7.1f}% {r.mean():>+11.3f}R {r.sum():>+8.1f}")

    if len(rows) > 2:
        wins = np.array([x[2] for x in rows])
        exps = np.array([x[4] for x in rows])
        c = float(np.corrcoef(wins, exps)[0, 1])
        print(f"\n  Correlation between win rate and expectancy: {c:+.2f}")
        if c < 0.3:
            print("  Effectively unrelated. The win rate moved across a "
                  f"{wins.max() - wins.min():.0f} point")
            print("  range while expectancy stayed inside a "
                  f"{(exps.max() - exps.min()):.3f}R band.")

    # ---- what actually moves expectancy -----------------------------------
    print("\n" + "-" * 82)
    print("  WHAT DOES MOVE EXPECTANCY")
    print("  Each of these was measured earlier in the project. Only two of")
    print("  them are worth anything, and neither is a win rate.\n")

    items = [
        ("Cutting trading costs", "+0.39R", "on Bitcoin, where fees exceeded the risk"),
        ("Realistic fill assumptions", "-0.06R", "the cost of being honest, not a gain"),
        ("Higher timeframe agreement", "+0.18R", "replicated on two markets"),
        ("Complex pullback required", "+0.11R", "replicated on two markets"),
        ("Volatility-targeted sizing", "+0.00R", "raises capacity, costs expectancy"),
        ("Raising the win rate", "0.00R", "arithmetic, not an improvement"),
        ("More confluence combinations", "0.00R", "335 tested, none survived"),
    ]
    for name, val, note in items:
        print(f"    {name:<30} {val:>7}   {note}")

    print("\n" + "=" * 82)
    print("  The only honest routes to profit are a real edge, or lower costs.")
    print("  This project found no edge and one large cost bug. That is the")
    print("  whole ledger.")
    print("=" * 82)


if __name__ == "__main__":
    main()
