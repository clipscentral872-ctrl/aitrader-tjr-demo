"""Wait for the second Nasdaq source, then run the check that decides it.

The Nasdaq result is the strongest unconfirmed thing in the project: +0.190R
over 427 trades with six of six walk-forward folds positive. It has cleared
every check except the one that matters most here, because this is the exact
market where a second-source comparison was read backwards once already.

Rather than poll by hand, this waits for the download to finish and then runs
the evaluation. It also refuses to run on a partial file, which matters: a
half-downloaded series looks like a complete one to pandas, and comparing a
full feed against an accidental subset is how you manufacture a disagreement.

    python await_nasdaq_check.py
"""
import os, subprocess, sys, time
import functools
print = functools.partial(print, flush=True)
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
TARGET = os.path.join(ROOT, "data", "store", "nasdaq_duka_5m.parquet")
MIN_BARS = 100_000          # roughly a year of 24-hour five-minute bars
POLL = 180


def ready():
    """Complete enough to compare, and not still being written."""
    if not os.path.exists(TARGET):
        return False, "not downloaded yet"
    try:
        size_a = os.path.getsize(TARGET)
        time.sleep(5)
        if os.path.getsize(TARGET) != size_a:
            return False, "still being written"
        df = pd.read_parquet(TARGET)
    except Exception as e:
        return False, f"unreadable: {type(e).__name__}"
    if len(df) < MIN_BARS:
        return False, f"only {len(df):,} bars, want {MIN_BARS:,}"
    span = (df.index[-1] - df.index[0]).days
    if span < 300:
        return False, f"only {span} days of span"
    return True, (f"{len(df):,} bars, {df.index[0]:%Y-%m-%d} to "
                  f"{df.index[-1]:%Y-%m-%d}")


def main():
    print("waiting for the second Nasdaq source ...")
    waited = 0
    while True:
        ok, why = ready()
        if ok:
            print(f"\nsecond source ready: {why}\n")
            break
        if waited % 900 == 0:
            print(f"  [{waited//60:>3} min] {why}")
        time.sleep(POLL)
        waited += POLL
        if waited > 14 * 3600:
            print("\ngave up after fourteen hours; the download is not finishing")
            return

    print("=" * 68)
    print("  RUNNING THE CHECK THAT DECIDES THE NASDAQ RESULT")
    print("=" * 68)
    r = subprocess.run(
        [sys.executable, os.path.join(ROOT, "evaluate.py"),
         "--market", "nsxusd", "--compare", "nasduka", "--reset-ledger"],
        capture_output=True, text=True, cwd=ROOT)
    out = r.stdout or ""
    print(out)
    if r.stderr:
        print("stderr:", r.stderr[:600])

    path = os.path.join(ROOT, "results", "nasdaq_verdict.txt")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    open(path, "w", encoding="utf-8").write(out)
    print(f"saved to {path}")

    try:
        import notify
        tail = [l for l in out.splitlines() if "PASS" in l or "FAIL" in l
                or "NOT AN EDGE" in l or "All checks passed" in l]
        if tail:
            notify.send("Nasdaq second-source check finished:\n" + "\n".join(tail))
    except Exception:
        pass


if __name__ == "__main__":
    main()
