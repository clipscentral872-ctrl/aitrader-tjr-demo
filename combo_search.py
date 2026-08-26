"""Search every combination of course confluences, honestly.

Chris asked for every combination tried so the highest-probability trades come
out. That is the right question and it is also the most dangerous search in
this project, so the method matters more than the result.

Eight named confluences give 256 subsets. Three course filters that can be on
or off give another eight. Two thousand combinations in total. Across two
thousand tries, pure noise will hand you something that looks superb. The
Nasdaq artefact cleared thirteen checks; it would sail through this.

So the search is run the only way that survives its own size:

  SPLIT      the first 60% of history is the only data the search may see
  SEARCH     every combination, ranked on that 60%, and nothing else
  ONE SHOT   the single best combination is applied to the held-out 40% once
  CONFIRM    and then to a completely different market it was never near

A combination has to survive all four to be called anything. If the winner
falls apart on the held-out portion, that is the answer: the search found the
shape of the past, not the shape of the market.

Efficiency note: the tag requirements are applied to an already-computed trade
list rather than re-running the backtest, so all 256 subsets of a given filter
configuration cost one backtest between them.

    python combo_search.py --market qqq --confirm eurusd
"""
import argparse, dataclasses, itertools, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config
from backtest.engine import run as bt_run
from backtest.guard import expected_best_by_luck, Ledger, assess
from backtest import bootstrap
from evaluate import get_data
from live import ny_window

TAGS = ["pool3+", "htf_trend", "complex_pullback", "full_efficiency",
        "engulf", "follow_through", "real_gap", "deep_pd"]

FILTER_SETS = [
    {"htf_bias": h, "require_real_draw": d, "require_premium": p}
    for h in (True, False) for d in (True, False) for p in (True, False)
]


def describe(fs, req):
    on = [k.replace("require_", "").replace("htf_bias", "htf")
          for k, v in fs.items() if v]
    bits = ("filters: " + "+".join(on)) if on else "filters: none"
    return f"{bits} | needs: " + ("+".join(req) if req else "nothing")


def trades_for(df, base, fs, costs, session):
    cfg = dataclasses.replace(base, **fs)
    setups = find_setups(df, cfg, session_filter=session)
    if not setups:
        return [], []
    tr, _ = bt_run(df, setups, costs)
    # pair each trade with the tags of the setup that produced it
    tags = [set((s.tags or "").split("|")) - {""} for s in setups]
    return tr, tags[:len(tr)] if len(tags) >= len(tr) else tags


def evaluate_subsets(tr, tags, min_trades):
    """Every subset of TAGS, scored against an already-computed trade list."""
    out = []
    r_all = np.array([t.r for t in tr])
    for size in range(0, 5):          # requiring more than four is over-narrow
        for req in itertools.combinations(TAGS, size):
            need = set(req)
            keep = [i for i, tg in enumerate(tags) if need <= tg]
            if len(keep) < min_trades:
                continue
            r = r_all[keep]
            out.append((req, float(r.mean()), len(r), float((r > 0).mean())))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="qqq")
    ap.add_argument("--confirm", default=None, help="a second, untouched market")
    ap.add_argument("--min-trades", type=int, default=60)
    ap.add_argument("--train-frac", type=float, default=0.6)
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()

    df, costs, ms, hours = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return

    base = Config(min_stop_pct=ms, max_stop_pct=1.5, min_rr=1.0, max_rr=1.5,
                  min_confluences=0)
    cut = int(len(df) * a.train_frac)
    train, test = df.iloc[:cut], df.iloc[cut:]

    print("=" * 74)
    print(f"  COMBINATION SEARCH  {a.market.upper()}")
    print(f"  search on   {train.index[0]:%Y-%m-%d} to {train.index[-1]:%Y-%m-%d}"
          f"   ({len(train):,} bars)")
    print(f"  held back   {test.index[0]:%Y-%m-%d} to {test.index[-1]:%Y-%m-%d}"
          f"   ({len(test):,} bars)")
    print("=" * 74)

    # ---- the search, on the training portion only -------------------------
    results = []
    for fs in FILTER_SETS:
        tr, tags = trades_for(train, base, fs, costs, ny_window)
        if not tr:
            continue
        for req, mean, n, wr in evaluate_subsets(tr, tags, a.min_trades):
            results.append((mean, n, wr, fs, req))

    if not results:
        print("\n  Nothing produced enough trades to score. The rules as written")
        print("  are too strict for this market.")
        return

    results.sort(key=lambda x: -x[0])
    tested = len(results)
    sd = float(np.std([t.r for t in trades_for(train, base, FILTER_SETS[0],
                                               costs, ny_window)[0]], ddof=1))
    luck = expected_best_by_luck(tested, sd, a.min_trades)

    print(f"\n  {tested:,} combinations scored on the training portion.")
    print(f"  Across that many tries, luck alone produces about {luck:+.3f}R.")
    print(f"  Anything below that line is not a finding, however good it looks.\n")

    print(f"  {'rank':>4} {'mean R':>9} {'trades':>7} {'win %':>7}   combination")
    for i, (mean, n, wr, fs, req) in enumerate(results[:a.top], 1):
        flag = "" if mean > luck else "   (under the luck line)"
        print(f"  {i:>4} {mean:>+9.3f} {n:>7} {wr*100:>7.1f}   "
              f"{describe(fs, req)}{flag}")

    # ---- one shot at the held-out data ------------------------------------
    best_mean, best_n, best_wr, best_fs, best_req = results[0]
    print("\n" + "-" * 74)
    print("  THE HELD-OUT TEST")
    print(f"  Taking the single best combination and applying it, once, to data")
    print(f"  the search never saw.\n")
    print(f"    {describe(best_fs, best_req)}")
    print(f"    on the training portion: {best_mean:+.3f}R over {best_n} trades")

    tr_t, tags_t = trades_for(test, base, best_fs, costs, ny_window)
    need = set(best_req)
    keep = [i for i, tg in enumerate(tags_t) if need <= tg]
    r_test = np.array([tr_t[i].r for i in keep]) if keep else np.array([])

    verdict_holds = False
    if len(r_test) < 20:
        print(f"    on the held-out portion: only {len(r_test)} trades, too few to judge")
    else:
        led = Ledger()
        v = assess(list(r_test), dataset=f"{a.market}_holdout",
                   label=describe(best_fs, best_req), ledger=led)
        print(f"    on the held-out portion: {r_test.mean():+.3f}R over "
              f"{len(r_test)} trades, win {(r_test > 0).mean()*100:.0f}%")
        print(f"    {v.headline}")
        decay = best_mean - float(r_test.mean())
        print(f"    decay from search to held-out: {decay:+.3f}R")
        verdict_holds = v.is_edge and float(r_test.mean()) > 0
        if decay > 0.15:
            print("    Most of the result did not survive being held out, which")
            print("    is what a search of this size produces from noise.")

    # ---- and a market it has never touched --------------------------------
    if a.confirm:
        print("\n" + "-" * 74)
        print(f"  CONFIRMATION ON {a.confirm.upper()}, which the search never saw")
        df2, c2, ms2, _ = get_data(a.confirm)
        if df2 is None or df2.empty:
            print(f"    no data for {a.confirm}")
        else:
            b2 = dataclasses.replace(base, min_stop_pct=ms2)
            tr2, tags2 = trades_for(df2, b2, best_fs, c2, ny_window)
            keep2 = [i for i, tg in enumerate(tags2) if need <= tg]
            r2 = np.array([tr2[i].r for i in keep2]) if keep2 else np.array([])
            if len(r2) < 20:
                print(f"    only {len(r2)} trades, too few to judge")
                verdict_holds = False
            else:
                print(f"    {r2.mean():+.3f}R over {len(r2)} trades, "
                      f"win {(r2 > 0).mean()*100:.0f}%")
                if r2.mean() <= 0:
                    print("    Negative on a market it was not fitted to.")
                    verdict_holds = False

    # ---- what it would mean in money --------------------------------------
    if verdict_holds and len(r_test) >= 20:
        print("\n" + "-" * 74)
        print("  IF IT IS REAL, WHAT COULD YOU RISK")
        safe = bootstrap.risk_for_drawdown(list(r_test), 10.0)
        print(f"    largest risk per trade keeping 95% of paths under a 10% "
              f"drawdown: {safe}%")

    print("\n" + "=" * 74)
    if verdict_holds:
        print("  A combination survived the search, the held-out data and a")
        print("  second market. That is rare and worth taking seriously.")
        print("  Next step is evaluate.py, not a funded account.")
    else:
        print("  Nothing survived. The best combination on the training data did")
        print("  not hold up where it counted.")
        print()
        print("  This is the expected outcome of searching two thousand ideas,")
        print("  and it is why the search is run this way. The alternative is a")
        print("  beautiful number from the top of that list and a funded account.")
    print("=" * 74)


if __name__ == "__main__":
    main()
