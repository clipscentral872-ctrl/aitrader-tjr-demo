"""Run the course strategy over historical data and report honestly.

Usage:
    python run_backtest.py                 # BTC 5m, the default proving ground
    python run_backtest.py --tf 15m
    python run_backtest.py --symbol ETHUSDT --tf 5m
"""
import argparse, json, os, sys
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.fetch import binance, resample                 # noqa: E402
from engine.strategy import find_setups, Config          # noqa: E402
from backtest.engine import run, stats, to_frame, Costs  # noqa: E402

RESULTS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results")
os.makedirs(RESULTS, exist_ok=True)

TF = {"1m": None, "5m": "5min", "15m": "15min", "1h": "1h"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default="BTCUSDT")
    ap.add_argument("--tf", default="5m", choices=list(TF))
    ap.add_argument("--start", default="2021-01-01")
    ap.add_argument("--max-rr", type=float, default=3.0)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()

    print(f"loading {a.symbol} 1m from {a.start} ...", flush=True)
    df = binance(a.symbol, "1m", a.start, quiet=True)
    if TF[a.tf]:
        df = resample(df, TF[a.tf])
    print(f"  {len(df):,} bars on {a.tf}   "
          f"{df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}", flush=True)

    cfg = Config(max_rr=a.max_rr)
    print("scanning for setups ...", flush=True)
    setups = find_setups(df, cfg)
    print(f"  {len(setups):,} setups found", flush=True)
    if not setups:
        print("no setups - the rules never triggered on this data")
        return

    print("simulating ...", flush=True)
    trades, unfilled = run(df, setups, Costs())
    s = stats(trades, unfilled)

    name = a.tag or f"{a.symbol}_{a.tf}"
    print()
    print("=" * 62)
    print(f"  {name}   {a.start} -> now")
    print("=" * 62)
    for k, v in s.items():
        print(f"  {k:<24} {v}")
    print("=" * 62)

    verdict(s)

    if trades:
        to_frame(trades).to_csv(os.path.join(RESULTS, f"trades_{name}.csv"), index=False)
    json.dump(s, open(os.path.join(RESULTS, f"stats_{name}.json"), "w"), indent=2)
    print(f"\nsaved to results/  (trades_{name}.csv, stats_{name}.json)")


def verdict(s):
    """Say plainly what the numbers mean, including when they mean 'no edge'."""
    print()
    if s.get("trades", 0) < 30:
        print("  VERDICT: too few trades to conclude anything. Widen the data or loosen the rules.")
        return
    e = s.get("expectancy_R", 0)
    if e > 0.3:
        print(f"  VERDICT: strongly positive ({e}R per trade).")
        print("           Treat this with SUSPICION first - check for lookahead before believing it.")
    elif e > 0.05:
        print(f"  VERDICT: positive ({e}R per trade). Worth forward testing on paper.")
    elif e > -0.05:
        print(f"  VERDICT: break-even ({e}R per trade). No edge after costs.")
    else:
        print(f"  VERDICT: negative ({e}R per trade). The rules as written lose money here.")
    print(f"           Worst losing streak was {s.get('worst_losing_streak')} trades "
          f"and max drawdown {s.get('max_drawdown_R')}R.")


if __name__ == "__main__":
    main()
