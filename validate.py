"""Train/test validation, so tuning cannot quietly become curve fitting.

The rule this file enforces: any parameter chosen by looking at results must be
chosen on the TRAIN slice only. The TEST slice is scored once, at the end, and
whatever it says is the answer. If train looks good and test does not, the
strategy does not work - that is the whole point of holding data back.

Also runs a walk-forward pass, which is the harder and more honest test: tune on
a rolling window, trade the window immediately after it, repeat. That mimics
what actually happens when you deploy.
"""
import sys, os, itertools, json
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run, stats, Costs


def score(df, cfg, costs=None):
    s = find_setups(df, cfg)
    if not s:
        return None, 0
    t, u = run(df, s, costs or Costs())
    if not t:
        return None, u
    return stats(t, u), u


def grid_search(df, grid, min_trades=40, costs=None, quiet=False):
    """Try every combination on ONE slice. Returns results sorted by expectancy.

    `min_trades` matters more than it looks: a combination with 6 trades and a
    great number is noise, and without this floor the search will hand you noise
    every single time because noise has the widest tails.
    """
    keys = list(grid)
    rows = []
    for combo in itertools.product(*(grid[k] for k in keys)):
        params = dict(zip(keys, combo))
        st, _ = score(df, Config(**params), costs)
        if st is None or st["trades"] < min_trades:
            continue
        rows.append({**params, **{k: st[k] for k in
                    ("trades", "win_rate", "avg_win_R", "avg_loss_R",
                     "expectancy_R", "total_R", "profitable_days_pct",
                     "worst_losing_streak", "max_drawdown_R")}})
        if not quiet:
            print(f"    {params}  ->  {st['trades']} trades, "
                  f"{st['expectancy_R']:+.3f}R", flush=True)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("expectancy_R", ascending=False)


def train_test(df, grid, split=0.6, min_trades=40, costs=None):
    """Tune on the first `split` of the data, then score the rest once."""
    n = int(len(df) * split)
    train, test = df.iloc[:n], df.iloc[n:]
    print(f"  train {train.index[0]:%Y-%m-%d} -> {train.index[-1]:%Y-%m-%d}  ({len(train):,} bars)")
    print(f"  test  {test.index[0]:%Y-%m-%d} -> {test.index[-1]:%Y-%m-%d}  ({len(test):,} bars)")

    print("\n  searching on TRAIN only ...")
    res = grid_search(train, grid, min_trades, costs, quiet=True)
    if res.empty:
        print("  no combination produced enough trades on train")
        return None
    best = res.iloc[0]
    params = {k: best[k] for k in grid}
    # numpy scalars -> python
    params = {k: (float(v) if isinstance(v, (np.floating,)) else
                  int(v) if isinstance(v, (np.integer,)) else v)
              for k, v in params.items()}

    print(f"\n  best on train: {params}")
    print(f"    train: {int(best['trades'])} trades, {best['expectancy_R']:+.3f}R, "
          f"win {best['win_rate']}%")

    st, _ = score(test, Config(**params), costs)
    if st is None:
        print("    test: produced no trades")
        return None
    print(f"    TEST : {st['trades']} trades, {st['expectancy_R']:+.3f}R, "
          f"win {st['win_rate']}%, profitable days {st['profitable_days_pct']}%")

    print()
    drop = best["expectancy_R"] - st["expectancy_R"]
    if st["expectancy_R"] <= 0:
        print("  VERDICT: the tuned settings do NOT survive out of sample.")
        print("           Whatever looked good on train was noise.")
    elif drop > 0.25:
        print(f"  VERDICT: survives but degrades badly ({drop:+.2f}R drop). Treat with caution.")
    else:
        print("  VERDICT: holds up out of sample. This is the only result that counts.")
    return {"params": params, "train": {k: float(best[k]) for k in
            ("trades", "expectancy_R", "win_rate")}, "test": st}


def walk_forward(df, grid, folds=5, min_trades=25, costs=None):
    """Roll a train window forward, trading only the window after each one."""
    n = len(df)
    size = n // (folds + 1)
    allr = []
    print(f"\n  walk-forward, {folds} folds of ~{size:,} bars each")
    for f in range(folds):
        tr = df.iloc[f * size:(f + 1) * size]
        te = df.iloc[(f + 1) * size:(f + 2) * size]
        res = grid_search(tr, grid, min_trades, costs, quiet=True)
        if res.empty:
            print(f"    fold {f+1}: no usable settings on train")
            continue
        p = {k: res.iloc[0][k] for k in grid}
        p = {k: (float(v) if isinstance(v, np.floating) else
                 int(v) if isinstance(v, np.integer) else v) for k, v in p.items()}
        st, _ = score(te, Config(**p), costs)
        if st is None:
            print(f"    fold {f+1}: no trades out of sample")
            continue
        allr.append(st["expectancy_R"])
        print(f"    fold {f+1}: {te.index[0]:%Y-%m-%d} -> {te.index[-1]:%Y-%m-%d}  "
              f"{st['trades']:>4} trades  {st['expectancy_R']:+.3f}R")
    if allr:
        print(f"\n    mean out-of-sample expectancy: {np.mean(allr):+.3f}R "
              f"over {len(allr)} folds")
        print(f"    folds positive: {sum(1 for x in allr if x > 0)}/{len(allr)}")
    return allr
