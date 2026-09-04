"""Render the whole For Learning library from whatever the journal holds.

Cuts produced
-------------
Daily       every trading day, three ways: all, losers only, winners only,
            named by weekday so Monday's session is never confused with Friday's
By Weekday  all your Mondays together, all your Tuesdays, and so on, split into
            losers and winners. A weekday you consistently lose on is a real
            pattern and it is invisible in a day-by-day list
Weekly      each week, losers only and winners only
Overall     every loser you have ever taken, and every winner

The point of the split is that reviewing losers back to back shows you the same
mistake repeating, which is invisible when wins are mixed in between.

Two things keep this from taking all afternoon. The project is bundled once and
every render reuses it, rather than rebuilding seven times. And cuts that
contain exactly the same trades are rendered once and copied, which matters
early on when a single day is also the whole week and the whole history.
"""
import datetime as dt
import functools
import io
import json
import os
import shutil
import subprocess
import sys

print = functools.partial(print, flush=True)

HERE = os.path.dirname(os.path.abspath(__file__))
STORE = os.path.join(HERE, "..", "journal_data", "trades.json")
LIB = os.path.join(HERE, "..", "For Learning")
BUNDLE = os.path.join(HERE, "bundle")
NPX = "npx.cmd" if os.name == "nt" else "npx"


def run(args, **kw):
    return subprocess.run(args, cwd=HERE, shell=(os.name == "nt"), **kw)


DAYS = {1: "Monday", 2: "Tuesday", 3: "Wednesday", 4: "Thursday", 5: "Friday",
        6: "Saturday", 7: "Sunday"}


def monday(d):
    x = dt.date.fromisoformat(d)
    return (x - dt.timedelta(days=x.weekday())).isoformat()


def dayname(d):
    return DAYS[dt.date.fromisoformat(d).isoweekday()]


def cuts(trades):
    """Every video worth making, given the trades on record."""
    days = sorted({t["open_t"][:10] for t in trades})
    weeks = sorted({monday(d) for d in days})
    out = []

    for d in days:
        who = dayname(d)
        out.append(("Daily", f"{who} {d} - All Trades", {
            "mode": "all", "from": d, "to": d,
            "title": "Traders Diary", "subtitle": who}))
        out.append(("Daily", f"{who} {d} - Losers", {
            "mode": "losers", "from": d, "to": d,
            "title": "Losing Trades", "subtitle": who}))
        out.append(("Daily", f"{who} {d} - Winners", {
            "mode": "winners", "from": d, "to": d,
            "title": "Winning Trades", "subtitle": who}))

    # every Monday together, every Tuesday together, and so on
    for wd in sorted({dt.date.fromisoformat(d).isoweekday() for d in days}):
        who = DAYS[wd]
        out.append(("By Weekday", f"{who}s - Losers", {
            "mode": "losers", "weekday": wd % 7,
            "title": "Losing Trades", "subtitle": "Every " + who}))
        out.append(("By Weekday", f"{who}s - Winners", {
            "mode": "winners", "weekday": wd % 7,
            "title": "Winning Trades", "subtitle": "Every " + who}))

    for w in weeks:
        end = (dt.date.fromisoformat(w) + dt.timedelta(days=6)).isoformat()
        out.append(("Weekly", f"Week of {w} - Losers", {
            "mode": "losers", "from": w, "to": end,
            "title": "Losing Trades", "subtitle": "Week in review"}))
        out.append(("Weekly", f"Week of {w} - Winners", {
            "mode": "winners", "from": w, "to": end,
            "title": "Winning Trades", "subtitle": "Week in review"}))

    out.append(("Overall", "All Losers", {
        "mode": "losers", "title": "Losing Trades", "subtitle": "Everything so far"}))
    out.append(("Overall", "All Winners", {
        "mode": "winners", "title": "Winning Trades", "subtitle": "Everything so far"}))
    return out


def matching(trades, p):
    keys = []
    for t in trades:
        d = t["open_t"][:10]
        if p.get("from") and d < p["from"]:
            continue
        if p.get("to") and d > p["to"]:
            continue
        wd = p.get("weekday")
        if wd is not None and dt.date.fromisoformat(d).isoweekday() % 7 != wd:
            continue
        if p["mode"] == "losers" and not t["pnl"] < 0:
            continue
        if p["mode"] == "winners" and not t["pnl"] > 0:
            continue
        keys.append(t["symbol"] + t["open_t"])
    return keys


def main():
    force = "--force" in sys.argv
    if not os.path.exists(STORE):
        print("No trades stored yet. Run tradejournal.py first.")
        return

    print("refreshing the trade data")
    if run([sys.executable, "build_data.py"]).returncode:
        print("could not rebuild src/trades.ts")
        return
    # Only your own trades. The store also holds the automated system's, your
    # hand-placed paper trades and replay practice, and blending them produced
    # cuts for days you never traded.
    trades = [t for t in json.load(io.open(STORE, encoding="utf-8"))
              if t.get("source", "live") == "live"]
    if not trades:
        print("No live trades on record yet, so there is nothing to film.")
        return

    plan = [(folder, name, props) for folder, name, props in cuts(trades)
            if matching(trades, props)]
    if not plan:
        print("nothing to render")
        return
    print(f"{len(plan)} cut(s) to make")

    print("bundling the project once")
    if run([NPX, "remotion", "bundle", "--out-dir", BUNDLE, "--log=error"]).returncode:
        print("bundle failed")
        return

    made = {}          # signature -> the file already rendered for it
    props_file = os.path.join(HERE, ".props.json")
    for folder, name, props in plan:
        dest_dir = os.path.join(LIB, folder)
        os.makedirs(dest_dir, exist_ok=True)
        dest = os.path.join(dest_dir, name + ".mp4")
        sig = tuple(matching(trades, props)) + (props["title"],)

        if os.path.exists(dest) and not force and \
                os.path.getmtime(dest) > os.path.getmtime(STORE):
            print(f"  up to date   {folder}/{name}")
            made.setdefault(sig, dest)
            continue

        if sig in made:
            shutil.copyfile(made[sig], dest)
            print(f"  same trades  {folder}/{name}  (copied)")
            continue

        n = len(matching(trades, props))
        print(f"  rendering    {folder}/{name}  ({n} trade{'s' if n != 1 else ''})")
        json.dump(props, io.open(props_file, "w", encoding="utf-8"))
        r = run([NPX, "remotion", "render", BUNDLE, "Diary", dest,
                 "--props", props_file, "--log=error"])
        if r.returncode:
            print(f"  FAILED       {folder}/{name}")
            continue
        made[sig] = dest

    if os.path.exists(props_file):
        os.remove(props_file)

    # A cut that was renamed leaves its old file behind, which then sits in the
    # library looking current. Anything the plan no longer produces goes.
    wanted = {os.path.join(LIB, f, n + ".mp4") for f, n, _ in plan}
    for folder in os.listdir(LIB) if os.path.isdir(LIB) else []:
        d = os.path.join(LIB, folder)
        if not os.path.isdir(d):
            continue
        for f in os.listdir(d):
            full = os.path.join(d, f)
            if f.lower().endswith(".mp4") and full not in wanted:
                os.remove(full)
                print(f"  removed old  {folder}/{f[:-4]}")
        if not os.listdir(d):
            os.rmdir(d)
    print(f"\nlibrary is at {os.path.abspath(LIB)}")


if __name__ == "__main__":
    main()
