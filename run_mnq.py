"""Paper-trade MNQ micro futures on TJR's session windows.

Why this exists rather than another Alpaca symbol: Alpaca does not offer
futures, and QQQ cannot trade the windows that carry the result. The held-out
Nasdaq figures come from London and the New York open, and a US equity ETF is
shut for one of them entirely.

MNQ is the right vehicle for three reasons:

  SESSIONS   it trades nearly 23 hours, so London and the New York open are
             both available. QQQ offers neither pre-market nor London.
  COST       commission is a fixed dollar amount per contract rather than a
             slice of notional, which on a 0.05% stop is 0.026R against the
             ETF's 0.200R.
  SIZE       one micro contract is $2 a point, so a $50,000 account can size
             to the risk instead of being forced into a position it cannot
             afford. The full-size NQ at $20 a point cannot.

Signals come from Yahoo's NQ=F, which is the real exchange contract rather than
a CFD, updated live and covering 23 hours a day.

Execution is simulated locally by PaperBroker with real MNQ specs, because no
futures broker is connected yet. That is the honest state: the fills are
modelled, not real, and modelled fills are optimistic in ways only a live
account reveals.

    python run_mnq.py --window "NY open 09:30-16:00" --minutes 390
    python run_mnq.py --check
"""
import argparse, os, sys, time
import functools
print = functools.partial(print, flush=True)
import datetime as dt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups
from paper.risk import RiskGate, RiskRules, INSTRUMENTS
from paper.broker import PaperBroker
from paper.journal import Journal
from data.fetch import yahoo
from live import Runner
import notify

NY = "America/New_York"


def window(lo_h, lo_m, hi_h, hi_m):
    def f(ts):
        t = (ts.tz_localize("UTC") if ts.tzinfo is None else ts).tz_convert(NY)
        m = t.hour * 60 + t.minute
        lo, hi = lo_h * 60 + lo_m, hi_h * 60 + hi_m
        return lo <= m < hi if lo < hi else (m >= lo or m < hi)
    return f


# TJR's own definitions. Asia is present but excluded by default: it is the
# only window negative out of sample (-0.012R against +0.167R for the NY open),
# and he teaches it as a source of levels rather than an entry window.
WINDOWS = {
    "NY open 09:30-16:00":      (window(9, 30, 16, 0),  "+0.167R held out, best of the set"),
    "London 03:00-08:30":       (window(3, 0, 8, 30),   "+0.160R held out"),
    "London + NY 03:00-16:00":  (window(3, 0, 16, 0),   "+0.132R, more trades, lower risk capacity"),
    "NY grouped 08:30-16:00":   (window(8, 30, 16, 0),  "+0.134R, includes pre-market"),
    "Asia 18:00-03:00":         (window(18, 0, 3, 0),   "NEGATIVE out of sample, not recommended"),
}


class MNQRunner(Runner):
    """The same engine, pointed at real futures with micro contract specs."""

    def __init__(self, equity, rules, win, quiet=False):
        super().__init__("mnq", equity=equity, rules=rules, quiet=quiet)
        self.inst = INSTRUMENTS["MNQ"]
        self.inst_name = "MNQ"
        self.window = win
        self.source = "live-mnq-sim"
        self.alerts = True

    def feed(self):
        df = yahoo("NQ=F", "5m", "5d")
        if df is not None and not df.empty and df.index.tz is None:
            df.index = df.index.tz_localize("UTC")
        return df


def check():
    print("=" * 70)
    print("  MNQ READINESS")
    print("=" * 70)
    df = yahoo("NQ=F", "5m", "5d")
    if df is None or df.empty:
        print("  FAIL  no NQ=F data")
        return
    if df.index.tz is None:
        df.index = df.index.tz_localize("UTC")
    age = (pd.Timestamp.now(tz=df.index.tz) - df.index[-1]).total_seconds() / 60
    print(f"  feed        NQ=F, {len(df):,} bars, last bar {age:.0f} min old")

    i = INSTRUMENTS["MNQ"]
    px = float(df["close"].iloc[-1])
    print(f"  contract    MNQ, {i.tick_size} tick, ${i.tick_value}/tick "
          f"(${i.tick_value / i.tick_size:.0f} a point)")
    print(f"  NQ now      {px:,.2f}")
    for acct, risk in ((25_000, 1.0), (50_000, 1.0), (50_000, 1.9), (100_000, 1.0)):
        stop_pts = px * 0.0008
        per_ct = stop_pts / i.tick_size * i.tick_value
        n = int((acct * risk / 100) // per_ct)
        print(f"  ${acct:>7,} at {risk:.1f}%  ->  {n} contract(s) "
              f"(${per_ct:,.0f} risk each on a {stop_pts:.0f}-point stop)")
    print()
    print("  windows available:")
    for name, (_, note) in WINDOWS.items():
        print(f"    {name:<26} {note}")
    print()
    print("  Execution is SIMULATED. No futures broker is connected, so fills")
    print("  are modelled rather than real. Connecting one is the remaining step.")
    print("=" * 70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--window", default="NY open 09:30-16:00")
    ap.add_argument("--equity", type=float, default=50_000)
    ap.add_argument("--risk", type=float, default=1.0)
    ap.add_argument("--minutes", type=int, default=390)
    ap.add_argument("--max-dd", type=float, default=10.0)
    a = ap.parse_args()

    if a.check:
        check()
        return

    if a.window not in WINDOWS:
        print("unknown window. options:")
        for k, (_, note) in WINDOWS.items():
            print(f"  {k:<26} {note}")
        return
    win, note = WINDOWS[a.window]
    if "NEGATIVE" in note:
        print(f"refusing: {a.window} is {note}.")
        print("It is in the list to be measured, not to be traded.")
        return

    rules = RiskRules(risk_pct=a.risk, max_total_drawdown_pct=a.max_dd,
                      min_rr=0.4, max_rr=0.5, max_trades_per_day=5,
                      max_losses_per_day=3)
    r = MNQRunner(a.equity, rules, win)
    print(f"MNQ paper session   window: {a.window}   ({note})")
    print(f"  ${a.equity:,.0f} at {a.risk}% risk, {a.max_dd}% drawdown limit")
    print("  signals from real NQ futures; fills are SIMULATED, not a live broker")
    notify.send(f"MNQ paper session started: {a.window}, "
                f"${a.equity:,.0f} at {a.risk}% risk")
    r.live(max_minutes=a.minutes)
    r.report()


if __name__ == "__main__":
    main()
