"""Start the S&P download the moment the Nasdaq one finishes.

Running two Dukascopy jobs at once starved both earlier today: one took the
whole connection and the other returned zero bytes for an hour. Dukascopy also
returns EMPTY rather than an error when throttled, so a starved download looks
like a completed one with missing hours.

So these run in sequence, not in parallel, and the handover happens without
waiting for someone to notice.

    python data/queue_sp500.py
"""
import os, subprocess, sys, time
import functools
print = functools.partial(print, flush=True)
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from data.dukascopy_pull import STORE

NASDAQ = os.path.join(STORE, "nasdaq_duka_5m.parquet")
SP500 = os.path.join(STORE, "sp500_duka_5m.parquet")
MIN_BARS = 100_000
POLL = 240


def nasdaq_done():
    if not os.path.exists(NASDAQ):
        return False, "not written yet"
    try:
        a = os.path.getsize(NASDAQ)
        time.sleep(6)
        if os.path.getsize(NASDAQ) != a:
            return False, "still being written"
        df = pd.read_parquet(NASDAQ)
    except Exception as e:
        return False, f"unreadable: {type(e).__name__}"
    if len(df) < MIN_BARS:
        return False, f"{len(df):,} bars so far"
    return True, f"{len(df):,} bars, {df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}"


def main():
    print("waiting for the Nasdaq download to finish before starting the S&P")
    waited = 0
    while True:
        ok, why = nasdaq_done()
        if ok:
            print(f"\nNasdaq complete: {why}\n")
            break
        if waited % 1200 == 0:
            print(f"  [{waited//60:>3} min] {why}")
        time.sleep(POLL)
        waited += POLL
        if waited > 10 * 3600:
            print("\ngiving up waiting; start the S&P by hand")
            return

    if os.path.exists(SP500):
        df = pd.read_parquet(SP500)
        if len(df) >= MIN_BARS:
            print(f"S&P already stored: {len(df):,} bars")
            return

    print("=" * 66)
    print("  DOWNLOADING S&P 500 INDEX, the ES futures proxy")
    print("=" * 66)
    code = (
        "import sys; sys.path.insert(0, r'%s')\n"
        "import pandas as pd, os\n"
        "from data.dukascopy_pull import pull, STORE\n"
        "frames = []\n"
        "for y in (2023, 2024, 2025):\n"
        "    b = pull('USA500IDXUSD', f'{y}-01-01', f'{y+1}-01-01', '5min', workers=16)\n"
        "    if b is not None and len(b):\n"
        "        print(f'{y}: {len(b):,} bars', flush=True)\n"
        "        frames.append(b)\n"
        "if frames:\n"
        "    m = pd.concat(frames).sort_index()\n"
        "    m = m[~m.index.duplicated(keep='first')]\n"
        "    m.to_parquet(os.path.join(STORE, 'sp500_duka_5m.parquet'))\n"
        "    print('stored', len(m), 'bars', m.index[0], '->', m.index[-1], flush=True)\n"
    ) % ROOT
    r = subprocess.run([sys.executable, "-c", code], cwd=ROOT,
                       capture_output=True, text=True)
    print(r.stdout or "")
    if r.stderr:
        print("stderr:", r.stderr[:500])

    try:
        import notify
        if os.path.exists(SP500):
            df = pd.read_parquet(SP500)
            notify.send(f"S&P 500 data downloaded: {len(df):,} bars, "
                        f"{df.index[0]:%Y-%m-%d} to {df.index[-1]:%Y-%m-%d}. "
                        f"Both index proxies are now in place.")
    except Exception:
        pass


if __name__ == "__main__":
    main()
