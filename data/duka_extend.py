"""Extend the Dukascopy history backwards, one year at a time.

The second-source check is the one guardrail that cannot be worked around: it
is what caught the Nasdaq artefact, and it is the only check the tight-target
result has not cleared. It did not fail — the two vendors differ by 0.90
standard errors on 77 overlapping trades, which is too little data to confirm
or refute anything.

More overlap is the entire fix. Two extra years roughly triples the comparison
sample and turns an inconclusive check into an answer either way.

Chunked by year on purpose. Each year caches independently, so an interrupted
run resumes instead of starting over, and a year that fails does not cost the
years that succeeded.

    python data/duka_extend.py --from 2021 --to 2024
"""
import argparse, os, sys
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from data.dukascopy_pull import pull, STORE

OUT = os.path.join(STORE, "eurusd_5m_duka.parquet")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="y0", type=int, default=2021)
    ap.add_argument("--to", dest="y1", type=int, default=2024)
    ap.add_argument("--symbol", default="EURUSD")
    a = ap.parse_args()

    existing = pd.read_parquet(OUT) if os.path.exists(OUT) else pd.DataFrame()
    if not existing.empty:
        print(f"already have {len(existing):,} bars "
              f"{existing.index[0]:%Y-%m-%d} -> {existing.index[-1]:%Y-%m-%d}")

    frames = [existing] if not existing.empty else []
    for year in range(a.y0, a.y1):
        start, end = f"{year}-01-01", f"{year + 1}-01-01"
        print(f"\n{year} ...", flush=True)
        try:
            bars = pull(a.symbol, start, end, "5min", workers=32)
        except Exception as e:
            print(f"  {year} failed: {type(e).__name__}: {str(e)[:80]}")
            continue
        if bars is None or bars.empty:
            print(f"  {year} returned nothing")
            continue
        print(f"  {year}: {len(bars):,} bars", flush=True)
        frames.append(bars)

        # write after every year, so an interruption keeps what was gathered
        merged = pd.concat(frames).sort_index()
        merged = merged[~merged.index.duplicated(keep="first")]
        merged.to_parquet(OUT)
        print(f"  stored {len(merged):,} bars total", flush=True)

    if frames:
        merged = pd.concat(frames).sort_index()
        merged = merged[~merged.index.duplicated(keep="first")]
        merged.to_parquet(OUT)
        print(f"\nfinal: {len(merged):,} bars  "
              f"{merged.index[0]:%Y-%m-%d} -> {merged.index[-1]:%Y-%m-%d}")
        print(f"years: {sorted(set(merged.index.year))}")


if __name__ == "__main__":
    main()
