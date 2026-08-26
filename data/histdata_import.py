"""Import HistData.com forex files into the local store.

Why forex, and why this source:

  * The phase course is TAUGHT on EURUSD and GBPUSD. The 3-10 pip stop, the Asia
    range, the London and New York windows - all of it is forex-native. Testing
    the method here tests it on its home ground.
  * Forex has REAL SESSIONS. That is the thing crypto lacked, and it is half the
    claimed edge.
  * Spreads are tiny relative to a 10 pip stop, so cost drag stops being fatal.
    Crypto fees ate 0.4R per trade; this is the fix.
  * HistData gives 1-minute bars back to 2000, free, no account, NO CARD.

Their download button is JavaScript-gated, so the files are fetched by hand once
and dropped in a folder. That is a few clicks for years of data, and it is the
honest way to use a site that offers the files freely but not scriptably.

    1. put the downloaded .zip files in  data/histdata/
    2. python data/histdata_import.py

Format inside each zip: DAT_ASCII_<PAIR>_M1_<YYYYMM>.csv, rows of
    YYYYMMDD HHMMSS;open;high;low;close;volume
timestamped in US Eastern WITHOUT daylight saving, which this converts to UTC.
"""
import os, re, sys, zipfile
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DROP = os.path.join(HERE, "histdata")
STORE = os.path.join(ROOT, "data", "store")
os.makedirs(DROP, exist_ok=True)
os.makedirs(STORE, exist_ok=True)

COLS = ["open", "high", "low", "close", "volume"]


def read_csv_bytes(raw, name=""):
    df = pd.read_csv(
        raw, sep=";", header=None,
        names=["ts", "open", "high", "low", "close", "volume"],
        dtype={"ts": str})
    # HistData stamps everything US Eastern with NO daylight saving, i.e. a
    # fixed UTC-5. Treating it as US/Eastern would shift half the year by an
    # hour and quietly corrupt every session test we then run.
    t = pd.to_datetime(df["ts"], format="%Y%m%d %H%M%S", errors="coerce")
    df = df.loc[t.notna()].copy()
    t = t[t.notna()]
    df.index = (t.dt.tz_localize("Etc/GMT+5").dt.tz_convert("UTC"))
    df.index.name = "time"
    out = df[COLS].astype(float)
    return out[~out.index.duplicated(keep="first")].sort_index()


def import_all(quiet=False):
    zips = [f for f in os.listdir(DROP) if f.lower().endswith(".zip")]
    csvs = [f for f in os.listdir(DROP) if f.lower().endswith(".csv")]
    if not zips and not csvs:
        print(f"Nothing to import. Put HistData .zip files in:\n  {DROP}\n")
        instructions()
        return

    frames = {}
    for z in sorted(zips):
        try:
            with zipfile.ZipFile(os.path.join(DROP, z)) as zf:
                for member in zf.namelist():
                    if not member.lower().endswith(".csv"):
                        continue
                    m = re.search(r"DAT_ASCII_([A-Z]{6})_M1", member, re.I)
                    pair = (m.group(1) if m else "UNKNOWN").lower()
                    with zf.open(member) as fh:
                        d = read_csv_bytes(fh, member)
                    frames.setdefault(pair, []).append(d)
                    if not quiet:
                        print(f"  {z} -> {pair} {len(d):,} bars "
                              f"{d.index[0]:%Y-%m-%d} to {d.index[-1]:%Y-%m-%d}")
        except Exception as e:
            print(f"  {z}: FAILED {type(e).__name__}: {str(e)[:70]}")

    for c in sorted(csvs):
        m = re.search(r"DAT_ASCII_([A-Z]{6})_M1", c, re.I)
        pair = (m.group(1) if m else "unknown").lower()
        with open(os.path.join(DROP, c), "rb") as fh:
            d = read_csv_bytes(fh, c)
        frames.setdefault(pair, []).append(d)
        if not quiet:
            print(f"  {c} -> {pair} {len(d):,} bars")

    if not frames:
        print("  no usable CSVs found inside those files")
        return

    print()
    for pair, parts in frames.items():
        new = pd.concat(parts)
        path = os.path.join(STORE, f"{pair}_1m.parquet")
        if os.path.exists(path):
            new = pd.concat([pd.read_parquet(path), new])
        new = new[~new.index.duplicated(keep="last")].sort_index()
        new.to_parquet(path)
        yrs = (new.index[-1] - new.index[0]).days / 365
        print(f"  {pair}: {len(new):,} bars  {new.index[0]:%Y-%m-%d} -> "
              f"{new.index[-1]:%Y-%m-%d}  ({yrs:.1f} years)  -> {pair}_1m.parquet")


def load(pair="eurusd"):
    p = os.path.join(STORE, f"{pair}_1m.parquet")
    return pd.read_parquet(p) if os.path.exists(p) else pd.DataFrame()


def instructions():
    print("How to get the files (free, no account, no card):")
    print()
    print("  1. Open:")
    print("     https://www.histdata.com/download-free-forex-data/"
          "?/ascii/1-minute-bar-quotes/eurusd")
    print("  2. Click a YEAR link (each year is one zip, about 3-4 MB)")
    print("  3. Click the DOWNLOAD button on the page that opens")
    print(f"  4. Save the .zip into:  {DROP}")
    print("  5. Repeat for the years you want, then run this script again")
    print()
    print("  Ten years of EURUSD is ten clicks and about 40 MB.")
    print("  Do GBPUSD too if you want a second pair to cross-check.")


if __name__ == "__main__":
    print("importing HistData files ...\n")
    import_all()
