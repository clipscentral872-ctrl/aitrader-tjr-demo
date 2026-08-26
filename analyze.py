"""The two questions that decide whether this system is worth building.

  1. Does stacking confluences actually raise the odds, as both courses claim?
  2. Does whatever we find survive on data the tuning never saw?

Question 2 is the one that matters. Anything that only works on the tuning slice
is noise wearing a nice hat.
"""
import sys, os, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.fetch import binance, resample
from engine.strategy import find_setups, Config
from backtest.engine import run, stats, Costs

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS, exist_ok=True)


def trades_with_confluence(df, cfg, costs=None):
    """Run the strategy and pair every filled trade with its setup."""
    setups = find_setups(df, cfg)
    if not setups:
        return [], [], 0
    trades, unfilled = run(df, setups, costs or Costs())
    by_bar = {s.bar: s for s in setups}
    bars = sorted(by_bar)
    rows = []
    for t in trades:
        # the setup that produced this fill is the last one at or before it
        j = np.searchsorted(bars, t.entry_bar, side="right") - 1
        s = by_bar[bars[j]] if j >= 0 else None
        rows.append((s.confluences if s else 0, s.tags if s else "", t.r))
    return trades, rows, unfilled


def confluence_table(rows, label=""):
    if not rows:
        print("  no trades"); return
    print(f"\n  {label}")
    print(f"  {'conf':>5} {'n':>6} {'win%':>7} {'expR':>9}")
    for cf in range(0, 9):
        rs = [r for c, _, r in rows if c == cf]
        if len(rs) < 8:
            continue
        a = np.array(rs)
        print(f"  {cf:>5} {len(a):>6} {100*(a>0).mean():>6.1f}% {a.mean():>+9.3f}")
    print(f"  {'-'*30}")
    for thr in range(0, 7):
        rs = [r for c, _, r in rows if c >= thr]
        if len(rs) < 20:
            continue
        a = np.array(rs)
        print(f"  >= {thr}: {len(a):>5} trades   win {100*(a>0).mean():>5.1f}%   exp {a.mean():+.3f}R")


def tag_value(rows):
    """Which individual confluence actually carries weight?"""
    tags = sorted({t for _, tg, _ in rows for t in tg.split("|") if t})
    print(f"\n  {'tag':<20} {'with':>18} {'without':>18}")
    for tg in tags:
        w = np.array([r for _, t, r in rows if tg in t.split("|")])
        o = np.array([r for _, t, r in rows if tg not in t.split("|")])
        if len(w) < 10 or len(o) < 10:
            continue
        print(f"  {tg:<20} {len(w):>5} @ {w.mean():>+7.3f}R "
              f"{len(o):>5} @ {o.mean():>+7.3f}R   edge {w.mean()-o.mean():>+.3f}")


def main():
    tf = sys.argv[1] if len(sys.argv) > 1 else "5min"
    start = sys.argv[2] if len(sys.argv) > 2 else "2022-01-01"
    print(f"loading BTCUSDT from {start} ...", flush=True)
    raw = binance("BTCUSDT", "1m", start, quiet=True)
    df = resample(raw, tf) if tf != "1min" else raw
    print(f"  {len(df):,} {tf} bars  {df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}\n", flush=True)

    cut = int(len(df) * 0.6)
    train, test = df.iloc[:cut], df.iloc[cut:]
    print(f"  TRAIN {train.index[0]:%Y-%m-%d} -> {train.index[-1]:%Y-%m-%d}")
    print(f"  TEST  {test.index[0]:%Y-%m-%d} -> {test.index[-1]:%Y-%m-%d}", flush=True)

    cfg = Config()
    print("\nscanning TRAIN ...", flush=True)
    _, rtr, u1 = trades_with_confluence(train, cfg)
    confluence_table(rtr, "TRAIN - does confluence stacking help?")
    tag_value(rtr)

    print("\nscanning TEST ...", flush=True)
    _, rte, u2 = trades_with_confluence(test, cfg)
    confluence_table(rte, "TEST - the only result that counts")

    # pick the threshold on TRAIN only, then score TEST once
    best_thr, best_exp = None, -9
    for thr in range(0, 7):
        rs = [r for c, _, r in rtr if c >= thr]
        if len(rs) < 40:
            continue
        e = float(np.mean(rs))
        if e > best_exp:
            best_thr, best_exp = thr, e
    print("\n" + "=" * 60)
    if best_thr is None:
        print("  not enough train trades to choose a threshold")
        return
    te = [r for c, _, r in rte if c >= best_thr]
    print(f"  threshold chosen on TRAIN: confluences >= {best_thr}  ({best_exp:+.3f}R)")
    if len(te) < 20:
        print(f"  TEST had only {len(te)} trades at that threshold - inconclusive")
        return
    a = np.array(te)
    print(f"  applied to TEST:  {len(a)} trades   win {100*(a>0).mean():.1f}%   exp {a.mean():+.3f}R")
    print("=" * 60)
    if a.mean() > 0.05:
        print("  Survives out of sample. Worth taking to paper trading.")
    elif a.mean() > -0.05:
        print("  Break-even out of sample. No edge after costs.")
    else:
        print("  Fails out of sample. The train result was noise.")

    json.dump({"threshold": best_thr, "train_exp": best_exp,
               "test_trades": len(a), "test_exp": float(a.mean()),
               "test_win": float((a > 0).mean())},
              open(os.path.join(RESULTS, f"confluence_{tf}.json"), "w"), indent=2)


if __name__ == "__main__":
    main()
