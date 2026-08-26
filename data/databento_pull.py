"""Pull years of CME futures history from Databento into the local store.

Run `--cost` FIRST. It asks Databento what a download would charge and prints it
against the $125 signup credit, so nothing is spent blind. Only then run the
actual pull.

    python data/databento_pull.py --cost                 # price it, spend nothing
    python data/databento_pull.py --cost --start 2010-01-01
    python data/databento_pull.py --pull                 # download and store

Needs an API key at config/databento.key (or the DATABENTO_API_KEY env var).
Chris creates the account and the key; this script only reads it.
"""
import argparse, os, sys
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
STORE = os.path.join(ROOT, "data", "store")
KEYFILE = os.path.join(ROOT, "config", "databento.key")
os.makedirs(STORE, exist_ok=True)

DATASET = "GLBX.MDP3"          # CME Globex, covers NQ/ES/GC
SCHEMA = "ohlcv-1m"            # minute bars: the cheapest schema by far
CREDIT = 125.0                 # the signup credit, for context in the output

# Databento continuous-contract notation: front month, volume-rolled.
SYMBOLS = {"NQ.v.0": "nq", "ES.v.0": "es", "GC.v.0": "gc"}


def api_key():
    k = os.environ.get("DATABENTO_API_KEY")
    if k:
        return k.strip()
    if os.path.exists(KEYFILE):
        k = open(KEYFILE, encoding="utf-8").read().strip()
        if k:
            return k
    return None


def client():
    key = api_key()
    if not key:
        print("No API key found.")
        print(f"  Put it in {KEYFILE}")
        print("  or set DATABENTO_API_KEY")
        return None
    try:
        import databento as db
    except ImportError:
        print("The databento client is not installed. Run:")
        print("    python -m pip install databento")
        return None
    return db.Historical(key)


def cost(start, end, symbols=None):
    c = client()
    if c is None:
        return
    syms = list(symbols or SYMBOLS)
    print(f"pricing {SCHEMA} from {DATASET}")
    print(f"  symbols: {', '.join(syms)}")
    print(f"  range:   {start} -> {end}\n")

    total = 0.0
    for s in syms:
        try:
            size = c.metadata.get_billable_size(
                dataset=DATASET, symbols=[s], schema=SCHEMA,
                start=start, end=end, stype_in="continuous")
            price = c.metadata.get_cost(
                dataset=DATASET, symbols=[s], schema=SCHEMA,
                start=start, end=end, stype_in="continuous")
            total += float(price)
            print(f"  {s:<10} {size/1e6:>9.1f} MB   ${float(price):>8.2f}")
        except Exception as e:
            print(f"  {s:<10} could not price: {type(e).__name__}: {str(e)[:70]}")

    print(f"\n  TOTAL ${total:.2f}   against ${CREDIT:.2f} of free credit")
    if total <= CREDIT:
        print(f"  Fits inside the credit with ${CREDIT - total:.2f} to spare.")
        print("  Run with --pull to download.")
    else:
        print(f"  Over the credit by ${total - CREDIT:.2f}.")
        print("  Shorten the range with --start and price it again.")


def pull(start, end, symbols=None):
    c = client()
    if c is None:
        return
    for sym, tag in (symbols or SYMBOLS).items():
        print(f"downloading {sym} ...", flush=True)
        try:
            data = c.timeseries.get_range(
                dataset=DATASET, symbols=[sym], schema=SCHEMA,
                start=start, end=end, stype_in="continuous")
            df = data.to_df()
        except Exception as e:
            print(f"  failed: {type(e).__name__}: {str(e)[:90]}")
            continue
        if df.empty:
            print("  empty response")
            continue

        # normalise to the same shape the rest of the project expects
        df = df.rename(columns=str.lower)
        keep = [c_ for c_ in ("open", "high", "low", "close", "volume") if c_ in df.columns]
        out = df[keep].copy()
        out.index = pd.to_datetime(df.index, utc=True)
        out.index.name = "time"
        out = out[~out.index.duplicated(keep="first")].sort_index()

        path = os.path.join(STORE, f"{tag}_1m_databento.parquet")
        if os.path.exists(path):
            old = pd.read_parquet(path)
            out = pd.concat([old, out])
            out = out[~out.index.duplicated(keep="last")].sort_index()
        out.to_parquet(path)
        yrs = (out.index[-1] - out.index[0]).days / 365
        print(f"  {len(out):,} bars  {out.index[0]:%Y-%m-%d} -> {out.index[-1]:%Y-%m-%d}"
              f"  ({yrs:.1f} years)  ->  {os.path.basename(path)}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--cost", action="store_true", help="price it, spend nothing")
    ap.add_argument("--pull", action="store_true", help="download and store")
    ap.add_argument("--start", default="2015-01-01")
    ap.add_argument("--end", default=None)
    ap.add_argument("--symbol", default=None, help="just one, e.g. NQ.v.0")
    a = ap.parse_args()

    end = a.end or (pd.Timestamp.now('UTC') - pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    syms = {a.symbol: SYMBOLS.get(a.symbol, "x")} if a.symbol else None

    if a.pull:
        pull(a.start, end, syms)
    else:
        cost(a.start, end, syms)
