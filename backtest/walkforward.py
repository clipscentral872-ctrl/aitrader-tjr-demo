"""Walk-forward validation: tune on a window, trade the window after it, repeat.

A single train/test split can be lucky. You pick one cut point, and if the
strategy happens to suit the second half you get a result that looks earned.

Walk-forward is stricter and closer to reality. Tune on months 1-12, trade month
13 with those settings. Slide forward. Tune on 2-13, trade 14. The out-of-sample
results are stitched together, and every one of them was produced by settings
chosen without seeing it.

If a strategy only works when you choose the split, this is where it stops
working.
"""
from dataclasses import dataclass
import itertools
import numpy as np
import pandas as pd


@dataclass
class Fold:
    n: int
    train_from: str
    train_to: str
    test_from: str
    test_to: str
    params: dict
    train_exp: float
    test_exp: float
    test_trades: int


def walk(df, make_setups, run_backtest, grid, folds=8, train_frac=0.7,
         min_trades=40, session_filter=None, quiet=False):
    """
    `make_setups(segment, params, session_filter)` -> list of setups
    `run_backtest(segment, setups)` -> list of per-trade R values
    `grid` is {param_name: [values]}
    """
    n = len(df)
    span = n // (folds + 1)
    if span < 500:
        print("  not enough data for this many folds")
        return [], []

    keys = list(grid)
    combos = list(itertools.product(*(grid[k] for k in keys)))
    results, all_r = [], []

    for f in range(folds):
        tr = df.iloc[f * span:(f + 1) * span]
        te = df.iloc[(f + 1) * span:(f + 2) * span]
        if len(te) < 200:
            break

        # ---- choose settings on the training window ONLY ----------------
        best, best_exp, best_params = None, -9e9, None
        for combo in combos:
            p = dict(zip(keys, combo))
            s = make_setups(tr, p, session_filter)
            if not s:
                continue
            r = run_backtest(tr, s)
            if len(r) < min_trades:
                continue
            e = float(np.mean(r))
            if e > best_exp:
                best_exp, best_params = e, p
        if best_params is None:
            if not quiet:
                print(f"    fold {f+1}: no usable settings on the training window")
            continue

        # ---- apply them to the window that follows ----------------------
        s = make_setups(te, best_params, session_filter)
        r = run_backtest(te, s) if s else []
        if len(r) == 0:
            if not quiet:
                print(f"    fold {f+1}: no trades out of sample")
            continue

        te_exp = float(np.mean(r))
        all_r.extend(r)
        results.append(Fold(
            n=f + 1,
            train_from=f"{tr.index[0]:%Y-%m}", train_to=f"{tr.index[-1]:%Y-%m}",
            test_from=f"{te.index[0]:%Y-%m}", test_to=f"{te.index[-1]:%Y-%m}",
            params=best_params, train_exp=round(best_exp, 3),
            test_exp=round(te_exp, 3), test_trades=len(r)))
        if not quiet:
            print(f"    fold {f+1}: train {best_exp:+.3f}R -> "
                  f"TEST {te_exp:+.3f}R on {len(r)} trades   {best_params}")

    return results, all_r


def summarise(folds, all_r):
    if not folds:
        print("  no folds completed")
        return
    te = np.array([f.test_exp for f in folds])
    tr = np.array([f.train_exp for f in folds])
    print()
    print(f"  {len(folds)} folds, {len(all_r)} out-of-sample trades")
    print(f"    train mean {tr.mean():+.3f}R   TEST mean {te.mean():+.3f}R")
    print(f"    folds positive out of sample: {(te > 0).sum()}/{len(te)}")
    print(f"    decay from train to test: {(tr.mean() - te.mean()):+.3f}R")
    if tr.mean() > 0 and te.mean() < 0:
        print("    Positive in training and negative out of it. That is the")
        print("    signature of fitting the settings to the past.")
    elif (te > 0).sum() < len(te) * 0.6:
        print("    Fewer than 60% of folds held up. Not reliable.")
    else:
        print("    Holds up across folds, which is a much harder test than one split.")
