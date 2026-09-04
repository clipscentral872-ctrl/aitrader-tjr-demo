"""Rebuild every page the app serves, in the order they depend on each other."""
import functools
import os
import subprocess
import sys

print = functools.partial(print, flush=True)
ROOT = os.path.dirname(os.path.abspath(__file__))

STEPS = [
    # First, because the one-minute window is only about a week wide: every day
    # this does not run is a day of one-minute history lost for good.
    ("topping up market data", "collect_bars.py"),
    ("reading your exports", "tradejournal.py"),
    ("packing replay bars", "build_replay_data.py"),
    ("building the diary", "journal_render.py"),
    ("building the replay", "replay_page.py"),
    ("building the demo tab", "demo_page.py"),
]

for label, script in STEPS:
    print(f"\n--- {label} ---")
    r = subprocess.run([sys.executable, os.path.join(ROOT, script)], cwd=ROOT)
    if r.returncode:
        print(f"\n  {script} failed. Stopping here.")
        sys.exit(1)

print("\n  All three tabs are built. Start it with:  python app.py")
