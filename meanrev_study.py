"""Mean reversion, tested properly this time.

It was tested before and lost, consistently, at -0.13 to -0.30R. That result
had a structural flaw worth naming: the setup builder demanded a reward of at
least 1R, and mean reversion targets the mean, which is usually CLOSER than one
risk unit away. So most genuine setups were rejected and only the unnatural
ones survived to be measured. The old number describes a strategy nobody would
run.

Mean reversion's real shape is the opposite of the ICT model: a high win rate
with small winners. A 65% win rate at 0.5:1 is a genuine edge. Judging it by
the same 1:3 standard is judging a bus by its top speed.

Three other things have changed since that test:
  * costs are now charged correctly per asset class
  * fills are pessimistic (must trade through, stops gap)
  * there is far more data, including 7.6 years of BTC

There is also a real reason to look here. The ICT model is a continuation bet,
and on BTC it loses with high confidence: n=3,979, 95% range -0.550 to -0.355R,
entirely below zero. When a directional bet loses that reliably, the opposite
behaviour is worth measuring rather than assuming.

Method is the same discipline as everywhere else: search parameters on the
first 60% of history, then apply the single best to the untouched 40%, then to
a market it never saw.

    python meanrev_study.py --market btc --confirm eurusd
"""
import argparse, itertools, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.alt_strategies import mean_reversion, vwap_reversion, _mk
from engine import alt_strategies as ALT
from backtest.engine import run as bt_run
from backtest.guard import assess, Ledger, expected_best_by_luck
from backtest import bootstrap
from data.fetch import resample
from evaluate import get_data

# The parameter surface. Kept deliberately small: every extra combination
# raises the bar the winner has to clear.
LOOKBACKS = [20, 50, 100]
ZS = [1.5, 2.0, 2.5, 3.0]
TFS = ["5min", "15min", "30min", "1h"]


def build(df, lookback, z, min_rr, max_rr, min_stop):
    """Mean reversion setups with a reward floor that suits the strategy."""
    real_mk = ALT._mk

    def patched(bar, side, entry, stop, target, name, **kw):
        return real_mk(bar, side, entry, stop, target, name,
                       min_rr=min_rr, max_rr=max_rr, min_stop_pct=min_stop,
                       max_stop_pct=max(4.0, min_stop * 30))
    ALT._mk = patched
    try:
        return mean_reversion(df, lookback=lookback, z=z)
    finally:
        ALT._mk = real_mk


def score(df, costs, lookback, z, min_rr, max_rr, min_stop):
    s = build(df, lookback, z, min_rr, max_rr, min_stop)
    if not s:
        return None, []
    tr, _ = bt_run(df, s, costs)
    r = [t.r for t in tr]
    return (float(np.mean(r)) if r else None), r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="btc")
    ap.add_argument("--confirm", default="eurusd")
    ap.add_argument("--min-trades", type=int, default=80)
    ap.add_argument("--min-stop", type=float, default=0.05)
    a = ap.parse_args()

    df, costs, ms, _ = get_data(a.market)
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return
    ms = max(a.min_stop, ms)

    led = Ledger()
    led.reset()

    print("=" * 78)
    print(f"  MEAN REVERSION  {a.market.upper()}   {len(df):,} five-minute bars")
    print("=" * 78)

    # ---- first: does the reward floor explain the old result? -------------
    print("\n  WHAT THE REWARD FLOOR WAS DOING")
    print("  The old test demanded 1R minimum. Mean reversion rarely offers it.\n")
    print(f"    {'min reward':>11} {'trades':>8} {'mean R':>9} {'win %':>7}")
    for mr in (0.3, 0.5, 0.8, 1.0):
        m, r = score(df, costs, 50, 2.0, mr, 3.0, ms)
        if m is None or len(r) < 30:
            print(f"    {mr:>11} {len(r) if r else 0:>8}   too few")
            continue
        arr = np.array(r)
        print(f"    {mr:>11} {len(arr):>8} {arr.mean():>+9.3f} "
              f"{(arr > 0).mean()*100:>7.1f}")

    # ---- the search, on the first 60% only --------------------------------
    cut = int(len(df) * 0.6)
    train, test = df.iloc[:cut], df.iloc[cut:]
    print(f"\n  searching {train.index[0]:%Y-%m-%d} to {train.index[-1]:%Y-%m-%d}")
    print(f"  held back {test.index[0]:%Y-%m-%d} to {test.index[-1]:%Y-%m-%d}\n")

    results = []
    for tf in TFS:
        d = train if tf == "5min" else resample(train, tf)
        if len(d) < 3000:
            continue
        for lb, z in itertools.product(LOOKBACKS, ZS):
            m, r = score(d, costs, lb, z, 0.4, 3.0, ms)
            if m is None or len(r) < a.min_trades:
                continue
            results.append((m, len(r), tf, lb, z, float((np.array(r) > 0).mean())))

    if not results:
        print("  nothing produced enough trades to score")
        return

    results.sort(key=lambda x: -x[0])
    sd = 1.0
    luck = expected_best_by_luck(len(results), sd, a.min_trades)
    print(f"  {len(results)} combinations scored. Luck alone across that many")
    print(f"  tries produces about {luck:+.3f}R.\n")
    print(f"  {'rank':>4} {'mean R':>9} {'trades':>7} {'win %':>7}  setting")
    for i, (m, n, tf, lb, z, wr) in enumerate(results[:10], 1):
        flag = "" if m > luck else "   (under the luck line)"
        print(f"  {i:>4} {m:>+9.3f} {n:>7} {wr*100:>7.1f}  "
              f"{tf}, lookback {lb}, z {z}{flag}")

    # ---- one shot at the held-out portion ---------------------------------
    bm, bn, btf, blb, bz, bwr = results[0]
    print("\n" + "-" * 78)
    print("  THE HELD-OUT TEST")
    print(f"    {btf}, lookback {blb}, z {bz}")
    print(f"    on the search data:  {bm:+.3f}R over {bn} trades")

    dt = test if btf == "5min" else resample(test, btf)
    mt, rt = score(dt, costs, blb, bz, 0.4, 3.0, ms)
    holds = False
    if mt is None or len(rt) < 30:
        print(f"    on the held-out data: {len(rt) if rt else 0} trades, too few")
    else:
        arr = np.array(rt)
        v = assess(list(arr), dataset=f"{a.market}_holdout",
                   label=f"meanrev {btf}", ledger=Ledger())
        print(f"    on the held-out data: {arr.mean():+.3f}R over {len(arr)} "
              f"trades, win {(arr > 0).mean()*100:.0f}%")
        print(f"    {v.headline}")
        print(f"      {v.detail}")
        print(f"    decay: {bm - float(arr.mean()):+.3f}R")
        holds = v.is_edge and float(arr.mean()) > 0

    # ---- and a market it never saw ----------------------------------------
    if a.confirm:
        print("\n" + "-" * 78)
        print(f"  CONFIRMATION ON {a.confirm.upper()}")
        df2, c2, ms2, _ = get_data(a.confirm)
        if df2 is None or df2.empty:
            print("    no data")
        else:
            d2 = df2 if btf == "5min" else resample(df2, btf)
            m2, r2 = score(d2, c2, blb, bz, 0.4, 3.0, max(a.min_stop, ms2))
            if m2 is None or len(r2) < 30:
                print(f"    {len(r2) if r2 else 0} trades, too few")
                holds = False
            else:
                arr2 = np.array(r2)
                print(f"    {arr2.mean():+.3f}R over {len(arr2)} trades, "
                      f"win {(arr2 > 0).mean()*100:.0f}%")
                if arr2.mean() <= 0:
                    print("    Negative on a market it was not fitted to.")
                    holds = False

    if holds and len(rt) >= 30:
        print("\n" + "-" * 78)
        print("  WHAT IT COULD CARRY")
        safe = bootstrap.risk_for_drawdown(list(rt), 10.0)
        print(f"    largest risk keeping 95% of paths under a 10% drawdown: {safe}%")
        res = bootstrap.run(list(rt), risk_pct=safe, runs=3000, block=5)
        if res:
            print(f"    median return at that risk: {res.median_return:+.1f}%")
            print(f"    chance of finishing up: {res.prob_profit*100:.1f}%")

    print("\n" + "=" * 78)
    if holds:
        print("  Mean reversion survived the search, the held-out data and a")
        print("  second market. Run evaluate.py on it before anything else.")
    else:
        print("  Mean reversion did not survive. Note this is now a FAIR test:")
        print("  the reward floor that crippled the previous one is gone.")
    print("=" * 78)


if __name__ == "__main__":
    main()
