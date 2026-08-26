"""Run the remaining work in priority order, then leave a summary for morning.

Chris has a day job and will not be at the machine. So the overnight work is
ordered by what actually decides something, and the result is a single readable
summary rather than eight log files.

Priority, highest first:

  1. the 1-minute evaluation      decides whether the best candidate is real
  2. the data downloads           enable tomorrow, already running as a task
  3. the step 4 test              a refinement, useful but not decisive

The CPU-heavy jobs run SEQUENTIALLY. Two of them running at once halved each
other's speed earlier tonight, which is worse than either finishing first.

    python morning_report.py
"""
import os, subprocess, sys, time
import functools
print = functools.partial(print, flush=True)
import datetime as dt
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
SCRATCH = os.environ.get("AITRADER_SCRATCH", os.path.join(ROOT, "results"))
OUT = os.path.join(ROOT, "results", "morning.txt")


def wait_for(path, label, limit_min=90):
    """Wait for a job to write its output, without blocking forever."""
    print(f"waiting for {label} ...")
    waited = 0
    while waited < limit_min * 60:
        if os.path.exists(path) and os.path.getsize(path) > 400:
            txt = open(path, encoding="utf-8", errors="ignore").read()
            if "DONE" in txt:
                print(f"  {label} finished")
                return txt
        time.sleep(60)
        waited += 60
    print(f"  {label} did not finish inside {limit_min} min")
    return None


def run(script_args, label, outfile, limit_min=120):
    print(f"\nrunning {label} ...")
    t0 = time.time()
    with open(outfile, "w", encoding="utf-8") as fh:
        r = subprocess.run([sys.executable] + script_args, cwd=ROOT,
                           stdout=fh, stderr=subprocess.STDOUT,
                           timeout=limit_min * 60)
    print(f"  {label} done in {(time.time()-t0)/60:.0f} min")
    return open(outfile, encoding="utf-8", errors="ignore").read()


def section(title, body, keep=26):
    lines = [l for l in (body or "").splitlines() if l.strip()]
    return f"\n{'='*70}\n  {title}\n{'='*70}\n" + "\n".join(lines[-keep:])


def main():
    started = dt.datetime.now()
    parts = [f"AITRADER MORNING REPORT\n  assembled {started:%Y-%m-%d %H:%M}"]

    # 1. the evaluation that decides the candidate
    ev = wait_for(os.path.join(SCRATCH, "eval_1min.txt"),
                  "1-minute evaluation", limit_min=90)
    parts.append(section("1-MINUTE CONFIG: FULL EVALUATION",
                         ev or "did not finish overnight"))

    # 2. step 4, now that the CPU is free
    try:
        s4 = run(["-c", STEP4], "step 4 test",
                 os.path.join(SCRATCH, "step4.txt"), limit_min=100)
    except Exception as e:
        s4 = f"failed: {type(e).__name__}: {e}"
    parts.append(section("STEP 4: DOES THE 1-MINUTE CONFIRMATION HELP", s4))

    # 3. what data arrived
    rows = []
    for label, f in (("nasdaq", "nasdaq_duka_5m.parquet"),
                     ("sp500", "sp500_duka_5m.parquet"),
                     ("nsxusd 1m", "nsxusd_1m.parquet")):
        p = os.path.join(ROOT, "data", "store", f)
        if os.path.exists(p):
            d = pd.read_parquet(p)
            rows.append(f"  {label:<12} {len(d):>9,} bars  "
                        f"{d.index[0]:%Y-%m-%d} to {d.index[-1]:%Y-%m-%d}")
        else:
            rows.append(f"  {label:<12} missing")
    parts.append(section("DATA ON DISK", "\n".join(rows)))

    text = "\n".join(parts)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w", encoding="utf-8").write(text)
    print(f"\nwritten to {OUT}")

    try:
        import notify
        head = [l for l in text.splitlines()
                if "PASS" in l or "FAIL" in l or "EDGE" in l
                or "NOT AN EDGE" in l or "All checks" in l][:10]
        notify.send("Overnight work finished. Summary in results/morning.txt\n\n"
                    + "\n".join(head))
    except Exception:
        pass


STEP4 = r'''
import sys, functools
print = functools.partial(print, flush=True)
sys.path.insert(0, r"__ROOT__")
import numpy as np, pandas as pd
from engine.strategy import Config
from engine.multiframe import find_setups_mtf
from backtest.engine import run as bt_run, Costs
from backtest import bootstrap
from data.fetch import resample
from tjr_exact import TJR, window
m1 = pd.read_parquet("data/store/nsxusd_1m.parquet")
m5 = resample(m1, "5min")
c1 = int(len(m1)*0.6); c5 = int(len(m5)*0.6)
costs = Costs(maker_pct=0.0, taker_pct=0.002, slip_pct=0.003)
base = dict(TJR); base["min_stop_pct"] = 0.03
sess = (lambda t: window(3,0,8,30)(t) or window(9,30,16,0)(t))
print("STEP 4: does the 1-minute confirmation earn its place?")
print()
print(f"{'entry rule':<30} {'seg':>6} {'trades':>8} {'exp R':>9} {'win %':>7} {'$/mo 50k':>10}")
for label, conf in (("zone touched (old)", False), ("1m must break or invert", True)):
    for tag, lo, hi in (("train", m1.iloc[:c1], m5.iloc[:c5]),
                        ("TEST", m1.iloc[c1:], m5.iloc[c5:])):
        s = find_setups_mtf(lo, hi, Config(**base), session_filter=sess,
                            require_confirm=conf)
        if not s:
            print(f"{label:<30} {tag:>6}   no setups"); continue
        tr, _ = bt_run(lo, s, costs)
        if len(tr) < 40:
            print(f"{label:<30} {tag:>6} {len(tr):>8}   too few"); continue
        r = np.array([t.r for t in tr]); yrs = (lo.index[-1]-lo.index[0]).days/365.25
        safe = bootstrap.risk_for_drawdown(list(r), 10.0) if r.mean() > 0 else 0.0
        money = 50000*(safe/100)*r.mean()*(len(r)/yrs)/12
        print(f"{label:<30} {tag:>6} {len(r):>8} {r.mean():>+8.3f} "
              f"{(r>0).mean()*100:>6.1f}% ${money:>9,.0f}")
    print()
print("DONE")
'''.replace("__ROOT__", ROOT)


if __name__ == "__main__":
    main()
