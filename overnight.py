"""Everything that should happen overnight, in one sequential run.

Written as a single script on purpose. The background jobs used during a
working session die when that session ends, so anything that must survive the
night has to be a scheduled task running one process. This is that process.

Order matters and the steps are sequential rather than parallel: running two
Dukascopy downloads at once starved both earlier today, and a throttled request
returns EMPTY rather than failing, so a starved job looks like a finished one
with missing hours.

  1. Nasdaq 2025      the year lost when a download was killed mid-write
  2. S&P 500 2023-25  the ES futures proxy, never started
  3. verify           coverage checked before anything is trusted
  4. report           Telegram summary at the end

Each year is written as soon as it completes, so an interruption keeps what it
gathered. That is what saved 2023 and 2024 when the earlier run was killed:
the final assembly never happened but the per-year caches survived.
"""
import os, sys, time
import functools
print = functools.partial(print, flush=True)
import datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from data.dukascopy_pull import pull, STORE

JOBS = [
    ("nasdaq", "USATECHIDXUSD", "nasdaq_duka_5m.parquet", [2025]),
    ("sp500",  "USA500IDXUSD",  "sp500_duka_5m.parquet",  [2023, 2024, 2025]),
]


def coverage(df, years):
    """Fraction of expected weekday bars present. A throttled pull returns
    nothing rather than erroring, so a holed series must be caught here."""
    if df is None or df.empty:
        return 0.0
    days = sum(1 for y in years
               for i in range(365)
               if (dt.date(y, 1, 1) + dt.timedelta(days=i)).year == y
               and (dt.date(y, 1, 1) + dt.timedelta(days=i)).weekday() < 5)
    expected = days * 24 * 12
    return len(df) / expected if expected else 0.0


def run_job(label, symbol, outfile, years):
    path = os.path.join(STORE, outfile)
    existing = pd.read_parquet(path) if os.path.exists(path) else None
    have = set(existing.index.year) if existing is not None else set()
    todo = [y for y in years if y not in have]
    if not todo:
        print(f"{label}: already has {sorted(have)}, nothing to do")
        return existing

    frames = [existing] if existing is not None else []
    for y in todo:
        print(f"\n{label} {y} ...")
        t0 = time.time()
        try:
            b = pull(symbol, f"{y}-01-01", f"{y+1}-01-01", "5min", workers=16)
        except Exception as e:
            print(f"  failed: {type(e).__name__}: {str(e)[:80]}")
            continue
        if b is None or b.empty:
            print("  returned nothing")
            continue
        cov = coverage(b, [y])
        mins = (time.time() - t0) / 60
        print(f"  {len(b):,} bars, coverage {cov*100:.0f}%, {mins:.0f} min")
        if cov < 0.60:
            print("  REJECTED: too many missing hours, likely throttled")
            continue
        frames.append(b)
        # write after EVERY year, so a kill keeps what was gathered
        m = pd.concat(frames).sort_index()
        m = m[~m.index.duplicated(keep="first")]
        m.to_parquet(path)
        print(f"  stored, {len(m):,} bars total")
    return pd.read_parquet(path) if os.path.exists(path) else None


def main():
    print("=" * 70)
    print(f"  OVERNIGHT RUN  started {dt.datetime.now():%Y-%m-%d %H:%M}")
    print("=" * 70)
    results = {}
    for label, symbol, outfile, years in JOBS:
        try:
            df = run_job(label, symbol, outfile, years)
            results[label] = df
        except Exception as e:
            print(f"{label}: {type(e).__name__}: {str(e)[:100]}")

    print("\n" + "=" * 70)
    print("  FINAL STATE")
    lines = []
    for label, _, outfile, _ in JOBS:
        p = os.path.join(STORE, outfile)
        if os.path.exists(p):
            d = pd.read_parquet(p)
            msg = (f"{label}: {len(d):,} bars, "
                   f"{d.index[0]:%Y-%m-%d} to {d.index[-1]:%Y-%m-%d}")
        else:
            msg = f"{label}: nothing stored"
        print("  " + msg)
        lines.append(msg)

    try:
        import notify
        notify.send("Overnight data run finished.\n" + "\n".join(lines))
    except Exception:
        pass
    print("=" * 70)


if __name__ == "__main__":
    main()
