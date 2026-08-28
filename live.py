"""The trading loop: context -> setup -> risk gate -> paper trade -> journal.

Two modes, same code path, which is the point:

    --mode replay   walk stored history bar by bar, as if it were live
    --mode live     poll the feed and act on new bars as they close

Replay is how we build a track record quickly. Live is how we prove the plumbing
works against a real feed. Because both drive the identical engine, broker and
journal, a disagreement between them is a bug and not a discovery.

    python live.py --mode replay --symbol nq --days 60
    python live.py --mode live --symbol nq
"""
import argparse, os, sys, time
import datetime as dt
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from engine.strategy import find_setups, Config          # noqa: E402
from engine import news as newsmod                       # noqa: E402
from paper.risk import RiskGate, RiskRules, INSTRUMENTS  # noqa: E402
from paper.broker import PaperBroker                     # noqa: E402
from paper.live_broker import LiveBroker                  # noqa: E402
from paper.crypto_broker import CryptoBroker              # noqa: E402
from paper.journal import Journal                        # noqa: E402
from paper.correlation import BOOK, group_of              # noqa: E402
from collector import load as load_store                 # noqa: E402
from data.fetch import yahoo                             # noqa: E402
import notify                                            # noqa: E402

# key -> (instrument spec, yahoo feed symbol, collector store tag)
# The micros trade the same underlying as the full-size contract, so they share
# one stored data series and differ only in tick value.
SYM_MAP = {"nq":  ("NQ",  "NQ=F", "nq"),
           "mnq": ("MNQ", "NQ=F", "nq"),
           "es":  ("ES",  "ES=F", "es"),
           "mes": ("MES", "ES=F", "es"),
           "gc":  ("GC",  "GC=F", "gc"),
           # the validated market: Nasdaq index, traded with micro specs
           "nsx": ("NSXUSD", "NQ=F", "nsxusd")}


# The correlated instrument, for his index-alignment veto: he refuses a trade
# when NQ and ES disagree about direction. find_setups needs the OTHER index to
# check that, and live.py never supplied it, so the veto would raise here while
# working fine in poll_once and evaluate.
PAIR_FEED = {"NQ=F": "ES=F", "ES=F": "NQ=F", "QQQ": "SPY", "SPY": "QQQ"}


# --------------------------------------------------------------------------
# session windows  (TJR: the New York window)
# --------------------------------------------------------------------------
def ny_window(ts, start_h=13, start_m=30, hours=3):
    """True inside the New York session window, in UTC.

    NY opens 13:30 UTC in summer. TJR trades the open; the phase course skips
    the first hour and takes the second. `hours` covers both readings so the
    difference can be measured rather than argued about.
    """
    if ts.tzinfo is None:
        ts = ts.tz_localize("UTC")
    mins = ts.hour * 60 + ts.minute
    lo = start_h * 60 + start_m
    return lo <= mins < lo + hours * 60


class Runner:
    def __init__(self, symbol="nq", equity=100_000.0, cfg=None, rules=None,
                 use_news=True, session=True, quiet=False, broker=None,
                 window=None):
        self.key = symbol.lower()
        self.inst_name, self.feed_sym, self.store_tag = SYM_MAP.get(
            self.key, ("NQ", "NQ=F", "nq"))
        self.inst = INSTRUMENTS[self.inst_name]
        if isinstance(broker, CryptoBroker):
            self.inst_name = broker.symbol
            self.inst = INSTRUMENTS["BTCUSD"]
        elif isinstance(broker, LiveBroker):
            # Trading a share account. Sizing with futures tick values here
            # would be out by a factor of twenty and is worth guarding against.
            self.inst_name = broker.symbol
            self.inst = INSTRUMENTS["SHARES"]
        # defaults come from config/tuned.json so the paper system and the
        # backtest cannot silently drift apart
        self.cfg = cfg or self._tuned()
        self.broker = broker or PaperBroker(equity=equity)
        self.gate = RiskGate(rules or RiskRules(), start_equity=equity)
        self.journal = Journal()
        self.use_news = use_news
        self.session = session
        # Which hours to take new trades in. The engine default is a narrow
        # three-hour slice of the New York open; the backtests that produced
        # every result here used TJR's full session. Trading a different window
        # live from the one that was measured makes the measurement irrelevant.
        self.window = window or ny_window
        self.quiet = quiet
        self.blocked_cache = (None, False, None)
        # tag every trade with where it came from. Replay results and live
        # results must never be averaged together: the first is a test of the
        # idea, the second is a test of the plumbing.
        self.source = ("live-alpaca" if isinstance(self.broker, LiveBroker)
                       else "replay")
        # only a real run is worth a phone alert. Replaying four years of
        # history would send hundreds.
        self.alerts = isinstance(self.broker, LiveBroker)

    @staticmethod
    def _tuned():
        import json
        p = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                         "config", "tuned.json")
        d = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}
        # Accept ANY key Config actually defines. This used to be a hand-kept
        # whitelist of nine names, and every other key in tuned.json was
        # dropped without a word: htf_factor, min_confluences and the SMT
        # settings were all being written to the file, read back, and thrown
        # away, so the live system quietly ran different settings from the
        # backtest that justified it.
        import dataclasses
        valid = {f.name for f in dataclasses.fields(Config)}
        cfg_keys = {k: v for k, v in d.items() if k in valid}
        # anything left over is either a typo or a setting Config never had.
        # Say so rather than ignoring it, which is how this went unnoticed.
        ignored = [k for k in d
                   if k not in valid and not k.startswith(("_", "status", "validated"))]
        if ignored:
            print(f"  tuned.json: {len(ignored)} key(s) Config does not define, "
                  f"ignored: {', '.join(sorted(ignored)[:6])}", flush=True)
        return Config(**cfg_keys)

    # ---- helpers ---------------------------------------------------------
    def _risk_for(self, order, inst):
        dist = abs(order.limit - order.stop)
        return (inst.risk_per_contract(dist) * order.size if inst.is_futures
                else dist * order.size)

    def _news_blocked(self, when):
        if not self.use_news:
            return False, None
        key = when.replace(minute=(when.minute // 5) * 5, second=0, microsecond=0)
        if self.blocked_cache[0] == key:
            return self.blocked_cache[1], self.blocked_cache[2]
        try:
            b, e = newsmod.blocked(when.to_pydatetime() if hasattr(when, "to_pydatetime")
                                   else when, self.feed_sym.replace("=F", ""))
        except Exception:
            b, e = False, None
        self.blocked_cache = (key, b, e)
        return b, e

    def log(self, *a):
        if not self.quiet:
            print(*a, flush=True)

    # ---- the core step ---------------------------------------------------
    def step(self, df, i, setups_by_bar):
        """Process one bar: manage the book, then consider a new setup."""
        when = df.index[i]
        bar = df.iloc[i]

        events = self.broker.on_bar(bar, when, self.inst, self._risk_for)
        for kind, obj in events:
            if kind == "closed":
                BOOK.closed(self.inst_name)
                self.journal.record_trade(obj, session="NY" if self.session else "all",
                                          source=self.source)
                self.gate.record_result(obj.r_multiple, obj.pnl_cash)
                self.log(f"  {when:%m-%d %H:%M}  CLOSED {obj.side} {obj.outcome:<7} "
                         f"{obj.r_multiple:+.2f}R  ${obj.pnl_cash:+,.0f}  "
                         f"equity ${self.broker.cash:,.0f}")
                if self.alerts:
                    notify.send(
                        f"{obj.symbol} {obj.side} closed {obj.outcome} "
                        f"{obj.r_multiple:+.2f}R (${obj.pnl_cash:+,.0f})  "
                        f"equity now ${self.broker.cash:,.0f}")
            elif kind == "filled":
                BOOK.opened(self.inst_name)
                self.log(f"  {when:%m-%d %H:%M}  FILLED {obj.side} {obj.size:g} @ {obj.entry:.2f}")
            elif kind in ("expired", "invalidated"):
                BOOK.closed(self.inst_name)
                self.journal.record_decision(when, self.inst_name, kind,
                                             f"order {kind} before filling")

        # outside the window we manage the book but take nothing new
        if self.session and not self.window(when):
            return

        s = setups_by_bar.get(i)
        if s is None:
            return

        # One position at a time across correlated instruments. NQ and ES
        # correlate at +0.954, so holding both is one bet of double the size
        # while looking like two independent ones.
        ok, why = BOOK.can_open(self.inst_name)
        if not ok:
            self.journal.record_decision(when, self.inst_name, "rejected", why, s)
            return

        nb, ev = self._news_blocked(when)
        eq = self.broker.equity(float(bar["close"]), self.inst)
        # volatility sizing needs recent prices; the gate does not fetch data
        lo = max(0, i - 240)
        self.gate.set_context(df["close"].to_numpy(float)[lo:i + 1])
        d = self.gate.check(s, eq, when, self.inst,
                            open_positions=len(self.broker.positions) + len(self.broker.orders),
                            news_blocked=nb, news_event=ev)
        if not d.approved:
            self.journal.record_decision(when, self.inst_name, "rejected", d.reason, s)
            if getattr(self.gate, "halted", False) and not getattr(self, "_said_halt", False):
                self._said_halt = True
                self.log("")
                self.log(f"  !! {self.gate.halt_reason}")
                self.log("     No further trades will be taken. This is the rule")
                self.log("     working, not a crash, but the run is over from here.")
                if self.alerts:
                    # this one wakes him up, because the system has stopped
                    notify.send(f"TRADING HALTED: {self.gate.halt_reason}. "
                                f"No further trades will be taken today.",
                                urgent=True)
                self.log("")
            return

        placed = self.broker.place(self.inst_name, s.side, d.size, s.entry,
                                   s.stop, s.target, when, tags=s.tags,
                                   confluences=s.confluences)
        if placed is not None:
            # claim the group at PLACEMENT, not at fill: between the two a
            # second runner could otherwise put on the correlated trade.
            BOOK.opened(self.inst_name)
        self.journal.record_decision(when, self.inst_name, "approved", "placed", s)
        self.log(f"  {when:%m-%d %H:%M}  PLACE  {s.side} {d.size:g} @ {s.entry:.2f} "
                 f"stop {s.stop:.2f} target {s.target:.2f}  "
                 f"({s.confluences} confluences, risk ${d.risk_cash:,.0f})")

    # ---- setup discovery -------------------------------------------------
    def pair_feed(self, interval="5m"):
        """The correlated index, for the alignment veto and for SMT.

        Returns None when the config does not need it, so a run with the veto
        off pays nothing for this. `pair_df` can be set by a caller (replay
        against history, tests) and is used in preference to fetching.
        """
        if not (getattr(self.cfg, "require_index_align", False)
                or getattr(self.cfg, "use_smt", False)):
            return None
        if getattr(self, "pair_df", None) is not None:
            return self.pair_df
        sym = PAIR_FEED.get(self.feed_sym)
        if sym is None:
            return None
        try:
            # same 45-second cache as the main feed: a longer one would compare
            # a live chart against a stale one and call that disagreement
            return yahoo(sym, interval, "5d", max_age=45)
        except Exception as e:
            self.log(f"  pair feed {sym} unavailable: {type(e).__name__}")
            return None

    def find(self, df, session_filter=None):
        """Where setups come from. One seam, so a subclass can change the
        entry timeframe without duplicating the polling loop. Whatever it
        returns must be indexed against `df`, because step() looks up by bar."""
        return find_setups(df, self.cfg, session_filter=session_filter,
                           smt_df=self.pair_feed())

    # ---- replay ----------------------------------------------------------
    def replay(self, df, session_filter=None):
        self.log(f"replay {self.inst_name}  {len(df):,} bars  "
                 f"{df.index[0]:%Y-%m-%d} -> {df.index[-1]:%Y-%m-%d}")
        setups = self.find(df, session_filter=session_filter)
        by_bar = {s.bar: s for s in setups}
        self.log(f"  {len(setups)} raw setups before the risk gate\n")
        for i in range(len(df)):
            self.step(df, i, by_bar)
            if i % 500 == 0:
                self.journal.record_equity(df.index[i], self.broker.cash,
                                           len(self.broker.positions))
        if self.broker.positions:
            for kind, obj in self.broker.force_close(
                    float(df["close"].iloc[-1]), df.index[-1], self.inst):
                if kind == "closed":
                    self.journal.record_trade(obj)
                    self.gate.record_result(obj.r_multiple, obj.pnl_cash)
        self.journal.record_equity(df.index[-1], self.broker.cash, 0)

    # ---- live ------------------------------------------------------------
    def live(self, poll_sec=60, max_minutes=None):
        self.source = ("live-alpaca" if isinstance(self.broker, LiveBroker)
                       else "live-sim")
        if isinstance(self.broker, LiveBroker) and not isinstance(self.broker, CryptoBroker):
            from data.freshness import check as fresh_check
            self.log("checking the feed before trusting anything it says:")
            f = fresh_check(self.broker.symbol)
            if f and f["verdict"] in ("DELAYED", "VERY STALE"):
                self.log("")
                self.log("  The feed is too far behind to place orders on.")
                self.log("  Entries would be priced off events that already")
                self.log("  finished, so any result would be meaningless.")
                self.log("  Stopping rather than producing a number to believe.")
                notify.send(f"AITrader did not start: {f['verdict']}, feed is "
                            f"{f['age_sec']/60:.0f} minutes behind.", urgent=True)
                return
            self.log("")
        src = ("consolidated tape, executing via Alpaca"
               if isinstance(self.broker, LiveBroker) else self.feed_sym)
        self.log(f"live {self.inst_name} via {src}, polling every {poll_sec}s")
        if isinstance(self.broker, LiveBroker):
            self.log("  The VALIDATED edge is spot EURUSD, which this broker cannot")
            self.log("  trade. This is the same rule set on QQQ: significance and")
            self.log("  walk-forward pass, the second-source check is still pending.")
            self.log("  Provisional, not validated.")
        else:
            self.log("  Paper account, no money at risk. His 09:45-10:30 window")
            self.log("  produces roughly one setup a month, so long stretches of")
            self.log("  nothing are the strategy behaving, not a fault. This run")
            self.log("  tests the plumbing; it is far too short to test the edge.")
        seen = None
        started = time.time()
        while True:
            if max_minutes and (time.time() - started) / 60 > max_minutes:
                self.log("  time limit reached")
                break
            try:
                df = self.feed()
            except Exception as e:
                self.log(f"  feed error: {type(e).__name__}"); time.sleep(poll_sec); continue
            if df.empty:
                time.sleep(poll_sec); continue
            last = df.index[-1]
            if last != seen:
                seen = last
                setups = self.find(df, session_filter=self.window)
                by_bar = {s.bar: s for s in setups}
                self.step(df, len(df) - 1, by_bar)
                self.journal.record_equity(last, self.broker.cash,
                                           len(self.broker.positions))
            time.sleep(poll_sec)

    def feed(self):
        """Latest bars. Prefer the broker's own feed when we are trading with
        it, so the prices we decide on are the prices it fills against."""
        if isinstance(self.broker, CryptoBroker):
            from paper.crypto_broker import bars
            return bars(self.broker.symbol, "5Min", 6000)
        if isinstance(self.broker, LiveBroker):
            # Signals come from the CONSOLIDATED tape, not Alpaca's free feed.
            # Alpaca free serves IEX only, a small slice of US volume, and on
            # the same symbol over the same window it produced -0.206R against
            # the consolidated tape's +0.005R. This strategy enters on wicks
            # through levels, and a feed that under-reports extremes misreads
            # exactly the events being traded. Execution still goes to Alpaca;
            # only the decision data changes.
            try:
                # 45 seconds, not the research default of an hour. The runner
                # polls every sixty seconds and a longer cache means it trades
                # off an hour-old chart.
                df = yahoo(self.broker.symbol, "5m", "5d", max_age=45)
                if df is not None and not df.empty:
                    return df
            except Exception:
                pass
            from data.alpaca_pull import latest
            df = latest(self.broker.symbol, minutes=1200)
            if df is not None and not df.empty:
                return df
        return yahoo(self.feed_sym, "5m", "5d")

    def report(self):
        print("\n" + "=" * 62)
        print(f"  PAPER ACCOUNT  -  {self.inst_name}")
        print("=" * 62)
        for k, v in self.broker.summary().items():
            print(f"  {k:<22} {v}")
        perf = self.journal.performance()
        if perf.get("trades"):
            print("-" * 62)
            for k in ("win_rate", "avg_win_R", "avg_loss_R", "expectancy_R",
                      "worst_losing_streak", "max_drawdown_R",
                      "trading_days", "profitable_days_pct"):
                if k in perf:
                    print(f"  {k:<22} {perf[k]}")
        ref = self.journal.refusals(8)
        if ref:
            print("-" * 62)
            print("  why setups were refused:")
            for reason, n in ref:
                print(f"    {n:>5}  {reason}")
        print("=" * 62)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=["replay", "live"], default="replay")
    ap.add_argument("--symbol", default="nq")
    ap.add_argument("--equity", type=float, default=100_000.0)
    ap.add_argument("--days", type=int, default=0, help="replay only the last N days")
    ap.add_argument("--no-session", action="store_true", help="ignore the NY window")
    ap.add_argument("--no-news", action="store_true")
    ap.add_argument("--minutes", type=int, default=None, help="live: stop after N minutes")
    ap.add_argument("--risk", type=float, default=0.5, help="percent of equity risked per trade")
    ap.add_argument("--broker", choices=["sim", "alpaca", "crypto"], default="sim",
                    help="sim = local simulation, alpaca = real paper stocks, "
                         "crypto = real paper crypto (trades around the clock)")
    ap.add_argument("--alpaca-symbol", default="QQQ")
    ap.add_argument("--window", default="TJR New York (08:30-18:00)",
                    help="session window; must match the one the backtest used")
    ap.add_argument("--dry-run", action="store_true",
                    help="with --broker alpaca: print orders instead of sending them")
    a = ap.parse_args()

    from paper.risk import RiskRules as _RR
    # The gate's reward bounds MUST come from the strategy config, never a
    # literal. Hardcoding min_rr=1.0 against a config that caps reward at 0.5R
    # refuses EVERY setup the strategy produces, and the refusal reads
    # "reward too small", which looks like a quiet market rather than a
    # misconfiguration. Deriving them here makes that drift impossible.
    _t = Runner._tuned()
    _min_rr = getattr(_t, "min_rr", 1.0)
    _max_rr = getattr(_t, "max_rr", 1.5)
    rules = _RR(risk_pct=a.risk, max_total_drawdown_pct=10.0,
                min_rr=_min_rr, max_rr=_max_rr)
    bk = None
    if a.broker == "crypto":
        sym = a.alpaca_symbol if "/" in a.alpaca_symbol else "BTC/USD"
        bk = CryptoBroker(equity=a.equity, symbol=sym, dry_run=a.dry_run)
        print(f"trading the REAL Alpaca paper account: {sym}, "
              f"equity ${bk.start_equity:,.0f}"
              + ("  [DRY RUN, nothing will be sent]" if a.dry_run else ""))
        print("  Crypto has no bracket orders here, so the stop rests at the")
        print("  broker and the target is watched by this process.")
        a.equity = bk.start_equity
        a.no_session = True
        rules = _RR(risk_pct=a.risk, max_total_drawdown_pct=10.0,
                    min_rr=_min_rr, max_rr=_max_rr)
    elif a.broker == "alpaca":
        bk = LiveBroker(equity=a.equity, symbol=a.alpaca_symbol, dry_run=a.dry_run)
        print(f"trading the REAL Alpaca paper account: {a.alpaca_symbol}, "
              f"equity ${bk.start_equity:,.0f}"
              + ("  [DRY RUN, nothing will be sent]" if a.dry_run else ""))
        a.equity = bk.start_equity
        rules = _RR(risk_pct=a.risk, max_total_drawdown_pct=10.0,
                    min_rr=_min_rr, max_rr=_max_rr)

    win = None
    if a.window:
        from tjr_study import SESSIONS
        win = SESSIONS.get(a.window)
        if win is None:
            print(f"unknown window {a.window!r}; options:")
            for k in SESSIONS:
                print(f"    {k}")
            return
        print(f"session window: {a.window}")

    r = Runner(a.symbol, equity=a.equity, rules=rules,
               session=not a.no_session, use_news=not a.no_news, broker=bk,
               window=win)

    if a.mode == "replay":
        df = load_store(r.store_tag, "5m")
        if df.empty:
            print("no stored data - run  python collector.py  first")
            return
        if a.days:
            df = df[df.index >= df.index[-1] - pd.Timedelta(days=a.days)]
        r.replay(df)
    else:
        r.live(max_minutes=a.minutes)
    r.report()


if __name__ == "__main__":
    main()
