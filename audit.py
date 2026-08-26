"""Hunt for the failures that look like success.

Every serious error in this project has been silent. Not one raised an
exception; each produced a plausible number that was wrong:

  * a data helper cached for an hour, so a live loop read the same chart sixty
    times and its log said what it says when everything is fine
  * a download printed DONE having written nothing, because a timeout killed it
    after the last progress line and the shell still ran the echo
  * throttled requests returned EMPTY rather than failing, so a starved job
    looked like a completed one with missing hours
  * contract specs were applied to a feed quoting the index divided by 100,
    which charged 5.35R of cost per trade and produced a 0% win rate
  * a walk-forward grid offered reward targets the config forbade, so every
    fold silently tested a different strategy and passed
  * a second-source check passed whenever a second source was SUPPLIED, never
    comparing them

So this checks the things that go wrong quietly, and it is written to be run
before trusting any result rather than after doubting one.

    python audit.py
"""
import glob, os, sys
import functools
print = functools.partial(print, flush=True)
import json
import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
STORE = os.path.join(ROOT, "data", "store")

# what each market should roughly quote at, so a rescaled feed is caught
EXPECTED_LEVEL = {
    "nsxusd": (8_000, 40_000, "Nasdaq index"),
    "nasdaq_duka": (8_000, 40_000, "Nasdaq index"),
    "sp500_duka": (2_000, 9_000, "S&P 500 index"),
    "eurusd": (0.8, 1.7, "EURUSD"),
    "qqq": (100, 900, "QQQ shares"),
    "spy": (200, 900, "SPY shares"),
    "nq": (8_000, 40_000, "NQ futures"),
    "es": (2_000, 9_000, "ES futures"),
    "btcusd": (5_000, 200_000, "Bitcoin"),
    "btcusdt": (5_000, 200_000, "Bitcoin"),
}

FAIL, WARN, OK = "FAIL", "warn", "ok  "
issues = []


def line(tag, what, detail=""):
    print(f"  [{tag}] {what}" + (f"   {detail}" if detail else ""))
    if tag == FAIL:
        issues.append(f"{what}: {detail}")


def check_scales():
    """A feed quoting the wrong scale is invisible until costs explode."""
    print("\n1. PRICE SCALE  (the bug that produced a 0% win rate)")
    for path in sorted(glob.glob(os.path.join(STORE, "*.parquet"))):
        name = os.path.basename(path).replace(".parquet", "")
        key = next((k for k in EXPECTED_LEVEL if name.startswith(k)), None)
        if key is None:
            continue
        lo, hi, label = EXPECTED_LEVEL[key]
        try:
            last = float(pd.read_parquet(path, columns=["close"])["close"].iloc[-1])
        except Exception as e:
            line(WARN, name, f"unreadable: {type(e).__name__}")
            continue
        if lo <= last <= hi:
            line(OK, f"{name:<24}", f"{last:,.2f}  ({label})")
        else:
            ratio = last / lo
            hint = ""
            for f in (0.01, 0.1, 10, 100, 1000):
                if lo <= last * f <= hi:
                    hint = f"  looks like the real value x{1/f:g}"
                    break
            line(FAIL, f"{name:<24}", f"{last:,.2f} outside {lo:,}-{hi:,} for {label}{hint}")


def check_costs():
    """Costs above ~0.25R per trade swamp the edge and are easy to miss."""
    print("\n2. COST BURDEN  (Bitcoin once paid 1.2R per trade)")
    from backtest.engine import Costs
    from futures import costs_for
    cases = [
        ("MNQ futures @25,000", costs_for("MNQ"), 25_000, 0.05),
        ("MES futures @6,400", costs_for("MES"), 6_400, 0.05),
        ("EURUSD @1.08", Costs(maker_pct=0, taker_pct=0.0008, slip_pct=0.0008), 1.08, 0.05),
        ("QQQ shares @600", Costs(maker_pct=0, taker_pct=0, slip_pct=0.01), 600, 0.05),
        ("index CFD @25,000", Costs(maker_pct=0, taker_pct=0.002, slip_pct=0.003), 25_000, 0.05),
    ]
    for label, c, px, stop_pct in cases:
        r = c.cost_in_r(px, px * (1 - stop_pct / 100))
        tag = OK if r < 0.15 else (WARN if r < 0.30 else FAIL)
        line(tag, f"{label:<24}", f"{r:.3f} R per trade at a {stop_pct}% stop")


def check_config():
    """A config that contradicts itself produces zero setups and no error."""
    print("\n3. CONFIG CONSISTENCY")
    p = os.path.join(ROOT, "config", "tuned.json")
    d = json.load(open(p, encoding="utf-8"))
    mn, mx = d.get("min_rr", 0), d.get("max_rr", 0)
    if mn > mx:
        line(FAIL, "reward bounds", f"min_rr {mn} exceeds max_rr {mx}: nothing can pass")
    else:
        line(OK, "reward bounds", f"{mn} to {mx}")
    smn, smx = d.get("min_stop_pct", 0), d.get("max_stop_pct", 0)
    if smn >= smx:
        line(FAIL, "stop bounds", f"min {smn} >= max {smx}")
    else:
        line(OK, "stop bounds", f"{smn}% to {smx}%")
    line(OK if d.get("status") != "candidate_unvalidated" else WARN,
         "status", d.get("status", d.get("_comment", "")[:52]))

    # The risk gate rejects on reward BEFORE sizing. If its floor sits above
    # the strategy's ceiling, every setup is refused with "reward too small",
    # which reads like a quiet market rather than a misconfiguration. This
    # silently blocked the entire live path until 2026-08-25.
    from paper.risk import RiskRules
    g = RiskRules()
    if g.min_rr > mx:
        line(FAIL, "gate vs strategy",
             f"gate floor {g.min_rr}R exceeds strategy ceiling {mx}R: "
             f"EVERY setup refused as 'reward too small'")
    else:
        line(OK, "gate vs strategy", f"gate floor {g.min_rr}R <= ceiling {mx}R")

    lv = open(os.path.join(ROOT, "live.py"), encoding="utf-8").read()
    hard = "min_rr=1.0, max_rr=1.5" in lv
    line(FAIL if hard else OK, "gate bounds source",
         "hardcoded in live.py, will drift from the config" if hard
         else "derived from tuned.json")


def check_lookahead():
    """Swings must not be visible before the bars that confirm them."""
    print("\n4. NO-LOOKAHEAD")
    from engine import structure as S
    rng = np.random.default_rng(0)
    n = 3000
    c = 25000 + np.cumsum(rng.normal(0, 5, n))
    h = c + np.abs(rng.normal(0, 3, n)); l = c - np.abs(rng.normal(0, 3, n))
    sw = S.find_swings(h, l, 2, 2)
    bad = [x for x in sw if x.confirmed_at <= x.idx]
    line(FAIL if bad else OK, "swing confirmation",
         f"{len(bad)} swings visible at or before their own bar" if bad
         else f"{len(sw)} swings, all confirmed after the fact")
    mid = n // 2
    known = S.known_tail(sw, mid, 50)
    future = [x for x in known if x.confirmed_at > mid]
    line(FAIL if future else OK, "known_tail",
         f"{len(future)} future swings leaked" if future else "no future data leaked")


def check_evaluate():
    """The guardrails themselves have been wrong three times."""
    print("\n5. THE GUARDRAILS")
    src = open(os.path.join(ROOT, "evaluate.py"), encoding="utf-8").read()
    line(OK if 'cross["ok"]' in src else FAIL, "second source",
         "compares the sources" if 'cross["ok"]' in src
         else "passes merely because a source was supplied")
    line(OK if "cfg_rr" in src else FAIL, "walk-forward grid",
         "centred on the configured target" if "cfg_rr" in src
         else "fixed list, may test a different strategy")
    line(OK if "sigmas" in src else WARN, "underpowered vs disagree",
         "distinguishes them" if "sigmas" in src else "may conflate them")
    line(OK if 'cross = {"ok": False' in src else FAIL, "no-compare path",
         "initialised" if 'cross = {"ok": False' in src else "can crash")


def check_live():
    """The live path has to differ from research in specific ways."""
    print("\n6. LIVE PATH")
    src = open(os.path.join(ROOT, "live.py"), encoding="utf-8").read()
    line(OK if "max_age=45" in src else FAIL, "feed cache",
         "45s for live" if "max_age=45" in src else "may serve stale bars")
    line(OK if "BOOK.can_open" in src else WARN, "correlation rule",
         "one position per correlated group" if "BOOK.can_open" in src else "not wired")
    line(OK if "self.window" in src else WARN, "session window",
         "configurable" if "self.window" in src else "hardcoded")
    line(OK if "freshness" in src else WARN, "stale-feed gate",
         "refuses to trade on old data" if "freshness" in src else "missing")


def main():
    print("=" * 74)
    print("  SYSTEM AUDIT  -  looking for failures that look like success")
    print("=" * 74)
    for fn in (check_scales, check_costs, check_config,
               check_lookahead, check_evaluate, check_live):
        try:
            fn()
        except Exception as e:
            line(FAIL, fn.__name__, f"{type(e).__name__}: {str(e)[:70]}")
    print("\n" + "=" * 74)
    if issues:
        print(f"  {len(issues)} PROBLEM(S) FOUND")
        for i in issues:
            print(f"    - {i}")
    else:
        print("  Nothing failing. Warnings above are worth reading, not acting on.")
    print("=" * 74)


if __name__ == "__main__":
    main()
