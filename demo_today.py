"""Paper-trade TJR's method live, on a demo account, in real time.

WHAT THIS IS HONEST ABOUT
-------------------------
The free CME feed runs about ten minutes behind. Fills come from the bar that
actually printed, so recorded PRICES are real; what is not real is the timing.
This demo can prove the logic, the levels and the sessions are right. It cannot
prove the trade was executable at that moment. Do not read it as latency proof.

Nor is it going to settle the edge. His 09:45-10:30 window yields on the order
of one setup a month, so a hundred trades is years away, not months. What a
short live run DOES catch, and catches quickly, is plumbing: a stale feed, a
session boundary off by an hour, a setup the system sees that a human would
not, a fill at a price that never traded.

THE RULES, AS HE STATES THEM
----------------------------
  * scan from 09:45 ET, because that is when he starts hunting confirmation
  * every step must be present before entry: require_confirm stays on, so the
    one-minute has to actually turn, not merely touch the zone
  * confirmation on the five-minute, entry on the one-minute
  * one position across NQ and ES, which correlate at +0.954

    python demo_today.py                # runs until the window closes
    python demo_today.py --minutes 30
"""
import argparse, functools, sys
print = functools.partial(print, flush=True)
import datetime as dt
import pandas as pd

from live import Runner
from paper.broker import PaperBroker
from engine.multiframe import find_setups_mtf
from data.fetch import yahoo, resample
from tjr_exact import window

# Sessions, New York time. His own 09:45-10:30 window is kept for reference but
# it is not measurable: 34 and 29 trades across the two halves, with opposite
# signs. london_ny agrees across halves on 853 and 568 trades, which is why it
# is the default.
WINDOWS = {
    "tjr":       window(9, 45, 10, 30),
    "ny_open":   window(9, 30, 11, 30),
    "ny_full":   window(9, 30, 16, 0),
    "london_ny": window(3, 0, 16, 0),
}
SCAN_NAME = "london_ny"
SCAN = WINDOWS[SCAN_NAME]
FRESH_LIMIT_MIN = 20                  # the free feed lags ~10; 20 is the cliff


class DemoRunner(Runner):
    """Runner with the entry timeframe moved down to one minute."""

    def feed(self):
        # ONE-MINUTE bars: the entry timeframe. The five-minute series used for
        # confirmation is resampled from these, so both charts come from one
        # request and cannot disagree with each other.
        df = yahoo(self.feed_sym, "1m", "5d", max_age=45)
        if df is None or df.empty:
            return pd.DataFrame()
        now = dt.datetime.now(dt.timezone.utc)
        self._lag_min = (now - df.index[-1].to_pydatetime()).total_seconds() / 60

        # HEARTBEAT. Yesterday this runner logged nothing between launch and
        # the end of the session, and a silent log looks identical whether the
        # process is polling quietly or died an hour ago. Zero trades from a
        # process that cannot be shown to have been alive proves nothing, so
        # every poll now leaves a mark. Inside the scan window it prints each
        # time; outside it, every tenth poll, to stay readable overnight.
        ny = now - dt.timedelta(hours=4)
        in_window = SCAN(df.index[-1])
        self._beats = getattr(self, "_beats", 0) + 1
        if in_window or self._beats % 10 == 1:
            self.log(f"  . {ny:%H:%M} NY  {self.inst_name}  "
                     f"{float(df['close'].iloc[-1]):,.2f}  "
                     f"lag {self._lag_min:.0f}m  "
                     f"{'SCANNING' if in_window else 'outside window'}")
        return df

    def find(self, df, session_filter=None):
        if len(df) < 120:
            return []
        m5 = resample(df, "5min")
        # The correlated index, for SMT divergence. He reads NQ against ES, so
        # without this his signature confluence cannot fire at all: it needs a
        # second instrument and there is none on a single chart.
        pair = None
        try:
            pair = yahoo("ES=F", "5m", "5d", max_age=45)
        except Exception:
            pair = None
        setups = find_setups_mtf(df, m5, self.cfg,
                                 session_filter=session_filter or SCAN,
                                 require_confirm=True,   # all steps, always
                                 smt_df=pair)
        if not setups:
            return []
        # A setup is stamped at its one-minute ENTRY bar, which may sit a few
        # bars behind the newest one. step() only inspects the latest bar, so
        # without this remap the runner would find setups and never act on a
        # single one. Anything older than two bars is dropped rather than
        # chased: the entry price has already been and gone.
        last = len(df) - 1
        fresh = [s for s in setups if s.bar >= last - 2]
        if not fresh:
            return []
        best = max(fresh, key=lambda s: (s.confluences, s.rr))
        from dataclasses import replace
        return [replace(best, bar=last)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--window", default="london_ny",
                    choices=sorted(WINDOWS), help="which session to scan")
    ap.add_argument("--symbols", default="mnq,mes",
                    help="comma separated; they share one correlation book")
    ap.add_argument("--equity", type=float, default=50_000.0)
    ap.add_argument("--risk", type=float, default=1.3)
    ap.add_argument("--minutes", type=int, default=None)
    ap.add_argument("--poll", type=int, default=60)
    a = ap.parse_args()
    global SCAN, SCAN_NAME
    SCAN_NAME = a.window
    SCAN = WINDOWS[SCAN_NAME]

    print("=" * 66)
    print("  TJR METHOD, LIVE PAPER DEMO")
    print("=" * 66)
    now_utc = dt.datetime.now(dt.timezone.utc)
    print(f"  started        {now_utc:%Y-%m-%d %H:%M} UTC "
          f"= {now_utc - dt.timedelta(hours=4):%H:%M} New York")
    print(f"  instruments    {a.symbols.upper()}  (paper, no money at risk)")
    print(f"  equity         ${a.equity:,.0f}   risking {a.risk}% a trade")
    print(f"  scanning       {SCAN_NAME} (New York time)")
    print( "  entry          1-minute, all confirmations required")
    print( "  feed           free CME, roughly 10 minutes behind")

    # Build the gate from the STRATEGY CONFIG, not from literals. The default
    # RiskRules demands min_rr 1.0 while this config caps reward at 0.5R, so the
    # gate would have refused every setup with "reward too small" and the run
    # would have looked like a quiet session instead of a broken one.
    from paper.risk import RiskRules
    from live import Runner as _R
    _t = _R._tuned()
    rules = RiskRules(risk_pct=a.risk,
                      min_rr=getattr(_t, "min_rr", 1.0),
                      max_rr=getattr(_t, "max_rr", 1.5),
                      max_total_drawdown_pct=10.0)
    print(f"  gate           risk {rules.risk_pct}% a trade, "
          f"reward {rules.min_rr}-{rules.max_rr}R, "
          f"max {rules.max_trades_per_day} trades a day")
    print("=" * 66)

    # NQ and ES correlate at +0.954, so they are one bet quoted two ways.
    # Each runner polls its own instrument but they share paper.correlation.BOOK,
    # which permits only ONE open position across the group. Whichever confirms
    # first takes it and the other is refused, with the reason recorded.
    import threading
    runners = []
    for sym in [x.strip() for x in a.symbols.split(",") if x.strip()]:
        r = DemoRunner(symbol=sym, equity=a.equity, rules=rules,
                       broker=PaperBroker(equity=a.equity), window=SCAN)
        r._lag_min = 0.0
        runners.append(r)
        print(f"  watching       {r.inst_name} via {r.feed_sym}")
    print("=" * 66)
    try:
        threads = [threading.Thread(
            target=r.live,
            kwargs=dict(poll_sec=a.poll, max_minutes=a.minutes),
            daemon=True) for r in runners]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    except KeyboardInterrupt:
        print("\n  stopped by hand")
    for r in runners:
        r.report()


if __name__ == "__main__":
    main()
