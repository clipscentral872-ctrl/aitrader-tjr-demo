"""The pre-trade risk gate and position sizer.

Chris's rules, from the scoping questions:
    1% risk per trade
    maximum 5 trades a day
    stop for the day after 3 losses
    reward capped at 1:3

The gate runs BEFORE anything is sized, and every rejection is recorded with a
reason. Rejections are data: "the setup never appeared" and "the setup appeared
but was refused" are different numbers and both matter.

Sizing runs in one direction only:  size = money at risk / stop distance.
Never the other way round.
"""
from dataclasses import dataclass, field
import datetime as dt


# --------------------------------------------------------------------------
# instrument specifications
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Instrument:
    symbol: str
    tick_size: float
    tick_value: float      # dollars per tick, per contract
    min_size: float = 1.0
    size_step: float = 1.0
    is_futures: bool = True

    def ticks(self, price_distance):
        return abs(price_distance) / self.tick_size

    def risk_per_contract(self, price_distance):
        return self.ticks(price_distance) * self.tick_value


INSTRUMENTS = {
    "NQ":   Instrument("NQ", 0.25, 5.00),
    "MNQ":  Instrument("MNQ", 0.25, 0.50),
    "ES":   Instrument("ES", 0.25, 12.50),
    "MES":  Instrument("MES", 0.25, 1.25),
    "GC":   Instrument("GC", 0.10, 10.00),
    # The Nasdaq cash index. Chris would trade this via MNQ, so the contract
    # specs below are MNQ's - the index is just the price feed.
    "NSXUSD": Instrument("NSXUSD", 0.25, 0.50),
    # Shares. One unit moves one dollar per dollar of price, so the tick
    # framing collapses to 1:1 and size must be a whole number.
    "SHARES": Instrument("SHARES", 0.01, 0.01, min_size=1.0, size_step=1.0,
                         is_futures=False),
    # Spot BTC on Alpaca. Size steps are tiny, so the position can be sized
    # to the risk almost exactly rather than rounded into a different trade.
    "BTCUSD": Instrument("BTCUSD", 0.01, 0.01, min_size=0.00002,
                         size_step=0.000001, is_futures=False),
    # crypto sizes in fractional units, so the "tick" framing does not apply
    "BTCUSDT": Instrument("BTCUSDT", 0.01, 0.01, min_size=0.001,
                          size_step=0.001, is_futures=False),
}


# --------------------------------------------------------------------------
# the rules
# --------------------------------------------------------------------------
@dataclass
class RiskRules:
    risk_pct: float = 1.0          # of account equity, per trade
    # Volatility targeting and the drawdown throttle. These do not change what
    # is traded, only how large. See paper/volsize.py for why this is the one
    # lever worth pulling: risk capacity, not signal quality, caps the income.
    vol_target: bool = False
    vol_target_pct: float = 1.0
    dd_throttle: bool = False
    max_trades_per_day: int = 5
    max_losses_per_day: int = 3
    max_open_positions: int = 1
    # These MUST match config/tuned.json. The strategy now caps reward at 1.5R,
    # so a gate demanding >=1.5R would reject almost every setup it produced.
    max_rr: float = 1.5
    min_rr: float = 1.0
    # Stop trading once the day is up by this much. A profit target is a real
    # discipline: it stops a good day being handed back. Set it to 0 to disable.
    # Note this can only ever REDUCE returns, never raise them, since it refuses
    # trades that were positive expectancy. What it buys is a smoother day and
    # fewer decisions made while elated.
    daily_profit_target: float = 0.0   # in account currency
    max_daily_loss_pct: float = 3.0   # hard stop on the day
    max_total_drawdown_pct: float = 10.0


@dataclass
class DayState:
    date: dt.date = None
    trades: int = 0
    losses: int = 0
    realised_r: float = 0.0
    realised_cash: float = 0.0

    def reset(self, d):
        self.date, self.trades, self.losses = d, 0, 0
        self.realised_r = self.realised_cash = 0.0


@dataclass
class Decision:
    approved: bool
    reason: str
    size: float = 0.0
    risk_cash: float = 0.0
    risk_ticks: float = 0.0


class RiskGate:
    def __init__(self, rules=None, start_equity=100_000.0, halt_on_drawdown=True):
        self.rules = rules or RiskRules()
        self.start_equity = start_equity
        self.peak_equity = start_equity
        self.day = DayState()
        # Hitting the drawdown cap is TERMINAL by design - that is what it means
        # on a funded account. But it must be loud, not a silent stream of
        # refusals: without this flag the system quietly stops trading forever
        # and still reports itself as running.
        self.halt_on_drawdown = halt_on_drawdown
        self.halted = False
        self.halt_reason = None

    # ---- daily bookkeeping ------------------------------------------------
    def roll_day(self, when):
        d = when.date() if hasattr(when, "date") else when
        if self.day.date != d:
            self.day.reset(d)

    def record_result(self, r_multiple, cash):
        self.day.trades += 1
        self.day.realised_r += r_multiple
        self.day.realised_cash += cash
        if r_multiple <= 0:
            self.day.losses += 1

    # ---- the gate ---------------------------------------------------------
    def set_context(self, closes):
        """Recent closes, for the volatility estimate. Called by the runner
        each bar so the gate never has to reach for data itself."""
        self._closes = closes

    def check(self, setup, equity, when, instrument, open_positions=0,
              news_blocked=False, news_event=None):
        """Approve or refuse, with the reason recorded either way."""
        self.roll_day(when)
        R = self.rules
        self.peak_equity = max(self.peak_equity, equity)

        if news_blocked:
            title = news_event["title"] if news_event else "high impact release"
            return Decision(False, f"news window: {title}")

        if open_positions >= R.max_open_positions:
            return Decision(False, "already in a position")

        if R.daily_profit_target and self.day.realised_cash >= R.daily_profit_target:
            return Decision(False,
                            f"daily target reached "
                            f"(${self.day.realised_cash:,.0f} of "
                            f"${R.daily_profit_target:,.0f}), standing down")

        if self.day.trades >= R.max_trades_per_day:
            return Decision(False, f"daily trade cap ({R.max_trades_per_day}) reached")

        if self.day.losses >= R.max_losses_per_day:
            return Decision(False, f"{self.day.losses} losses today, standing down")

        day_loss_pct = -self.day.realised_cash / equity * 100 if equity else 0
        if day_loss_pct >= R.max_daily_loss_pct:
            return Decision(False, f"daily loss limit hit ({day_loss_pct:.1f}%)")

        dd = (self.peak_equity - equity) / self.peak_equity * 100 if self.peak_equity else 0
        if dd >= R.max_total_drawdown_pct:
            if self.halt_on_drawdown and not self.halted:
                self.halted = True
                self.halt_reason = (f"ACCOUNT HALTED: drawdown {dd:.1f}% exceeded "
                                    f"the {R.max_total_drawdown_pct:.0f}% limit")
            if self.halt_on_drawdown:
                return Decision(False, self.halt_reason)
            # when not halting we still refuse, but only until equity recovers

        if setup.rr < R.min_rr:
            return Decision(False, f"reward too small ({setup.rr:.1f}R)")

        # ---- sizing: risk first, stop second, SIZE LAST ------------------
        dist = abs(setup.entry - setup.stop)
        if dist <= 0:
            return Decision(False, "stop is at the entry")

        # ---- how large, before what size that implies -------------------
        from paper.volsize import VolTarget, DrawdownThrottle, combined
        # VolTarget was rewritten to use a RELATIVE target (recent volatility
        # against the market's own longer-run volatility), which removed
        # target_vol_pct. This caller was never updated, and because the object
        # is built unconditionally it raised even with the overlay switched
        # off. It only surfaced when a setup actually reached the risk gate.
        vt = VolTarget(enabled=R.vol_target)
        th = DrawdownThrottle(enabled=R.dd_throttle)
        vs = vt.scale(getattr(self, "_closes", []) or [])
        ds = th.scale(equity, self.peak_equity)
        scale = combined(vs, ds)
        self.last_scale = scale

        risk_cash = equity * R.risk_pct / 100 * scale
        if instrument.is_futures:
            per_contract = instrument.risk_per_contract(dist)
            if per_contract <= 0:
                return Decision(False, "cannot price the risk")
            raw = risk_cash / per_contract
            size = int(raw // instrument.size_step) * instrument.size_step
            if size < instrument.min_size:
                # This is the honest answer that beginners override: the
                # smallest tradeable size risks more than the rules allow.
                return Decision(
                    False,
                    f"account too small: 1 contract risks "
                    f"${per_contract:,.0f} vs ${risk_cash:,.0f} allowed")
            actual = size * per_contract
        else:
            raw = risk_cash / dist
            size = round(raw / instrument.size_step) * instrument.size_step
            if size < instrument.min_size:
                return Decision(False, "position below minimum size")
            actual = size * dist

        return Decision(True, "approved", size=size, risk_cash=actual,
                        risk_ticks=instrument.ticks(dist))

    def summary(self):
        return {
            "date": str(self.day.date),
            "trades_today": self.day.trades,
            "losses_today": self.day.losses,
            "realised_R_today": round(self.day.realised_r, 2),
            "realised_cash_today": round(self.day.realised_cash, 2),
        }
