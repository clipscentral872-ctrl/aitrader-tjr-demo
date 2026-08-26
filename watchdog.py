"""Watch the running jobs for the kind of failure that looks like success.

Two things stalled silently today and neither showed up in a log:

  * Dukascopy throttled a download and returned EMPTY rather than an error, so
    a starved job looked like a finished one with missing hours.
  * The live runner polled a data helper that caches for an hour, so it read
    the same chart sixty times and idled through most of a session. Its log
    said exactly what it had said when everything was fine.

The common shape is that the process is alive and the output is unchanged, and
"unchanged" reads as "quietly waiting" when it actually means "stopped". So
this checks PROGRESS rather than liveness: is the number moving.

    python watchdog.py            one pass
    python watchdog.py --watch    keep checking, alert on change
"""
import argparse, os, sqlite3, sys, time
import functools
print = functools.partial(print, flush=True)
import datetime as dt

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
STORE = os.path.join(ROOT, "data", "store")

# how long a thing may go without progressing before it counts as stalled
LIMITS = {
    "live session": 12 * 60,        # a 5-minute feed should tick well inside this
    "nasdaq download": 30 * 60,
    "sp500 download": 30 * 60,
}


def _age(path):
    if not os.path.exists(path):
        return None
    return time.time() - os.path.getmtime(path)


def live_session():
    """Is the trading loop still recording equity."""
    from paper.journal import DB
    try:
        db = sqlite3.connect(DB)
        row = db.execute("SELECT ts FROM equity ORDER BY ts DESC LIMIT 1").fetchone()
        db.close()
    except Exception as e:
        return "live session", None, f"journal unreadable: {type(e).__name__}"
    if not row:
        return "live session", None, "no equity rows at all"
    last = dt.datetime.fromisoformat(row[0])
    if last.tzinfo is None:
        last = last.replace(tzinfo=dt.timezone.utc)
    age = (dt.datetime.now(dt.timezone.utc) - last).total_seconds()
    return "live session", age, f"last equity snapshot {age/60:.0f} min ago"


def download(name, filename, logfile=None):
    """Is it progressing?

    Checking only for the finished parquet was wrong: Dukascopy writes it at
    the END of a year, so a download three hours into its work reported "not
    started". The progress signal during a run is the log the job streams to,
    so that is checked first and the finished file second.
    """
    if logfile and os.path.exists(logfile):
        a = _age(logfile)
        done = os.path.exists(os.path.join(STORE, filename))
        if not done:
            tail = ""
            try:
                lines = [x for x in open(logfile, encoding="utf-8",
                                         errors="ignore").read().splitlines() if x.strip()]
                tail = lines[-1].strip()[:46] if lines else ""
            except Exception:
                pass
            return name, a, f"running, log {a/60:.0f} min ago: {tail}"
    p = os.path.join(STORE, filename)
    if os.path.exists(p):
        age = _age(p)
        return name, age, f"COMPLETE, written {age/60:.0f} min ago"
    return name, None, "not started"


def check(quiet=False):
    scratch = os.environ.get("AITRADER_SCRATCH", "")
    sp = os.environ.get("AITRADER_SCRATCH") or ""
    rows = [
        live_session(),
        download("nasdaq download", "nasdaq_duka_5m.parquet",
                 os.path.join(sp, "nas_duka.txt") if sp else None),
        download("sp500 download", "sp500_duka_5m.parquet",
                 os.path.join(ROOT, "results", "sp500_queue.log")),
    ]
    problems = []
    if not quiet:
        print(f"  {'job':<20} {'state':<44}")
    for name, age, note in rows:
        limit = LIMITS.get(name)
        bad = age is not None and limit and age > limit
        tag = "STALLED" if bad else ("ok" if age is not None else "-")
        if not quiet:
            print(f"  {name:<20} [{tag:<7}] {note}")
        if bad:
            problems.append(f"{name}: {note}")
    return problems


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--watch", action="store_true")
    ap.add_argument("--every", type=int, default=600)
    a = ap.parse_args()

    if not a.watch:
        print(f"WATCHDOG  {dt.datetime.now():%H:%M}")
        p = check()
        print()
        print("  all progressing" if not p else "  NEEDS ATTENTION: " + "; ".join(p))
        return

    print(f"watching every {a.every//60} minutes; alerting only on a change")
    last_state = None
    while True:
        problems = check(quiet=True)
        state = tuple(problems)
        if state != last_state:
            stamp = dt.datetime.now().strftime("%H:%M")
            if problems:
                msg = "AITrader watchdog: " + "; ".join(problems)
                print(f"[{stamp}] {msg}")
                try:
                    import notify
                    notify.send(msg, urgent=True)
                except Exception:
                    pass
            else:
                print(f"[{stamp}] everything progressing again")
            last_state = state
        time.sleep(a.every)


if __name__ == "__main__":
    main()
