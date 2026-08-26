"""A paper broker that fills against real market bars.

There is no free paper-trading API for futures, so this is it: a local account
that takes real NQ/ES bars and simulates orders against them. It carries the
same pessimistic assumptions as the backtester, on purpose, so that paper
results and backtest results mean the same thing:

  * a limit order only fills if price actually trades through it
  * if one bar covers both the stop and the target, the STOP wins
  * commission and slippage are charged on every round turn

If paper and backtest disagree, that is a bug worth chasing, not a discovery.
"""
from dataclasses import dataclass, field, asdict
import datetime as dt
import uuid


@dataclass
class Position:
    id: str
    symbol: str
    side: str            # long | short
    size: float
    entry: float
    stop: float
    target: float
    opened_at: dt.datetime
    risk_cash: float
    setup_tags: str = ""
    confluences: int = 0

    def unrealised(self, price, inst):
        move = (price - self.entry) if self.side == "long" else (self.entry - price)
        if inst.is_futures:
            return move / inst.tick_size * inst.tick_value * self.size
        return move * self.size


@dataclass
class Order:
    id: str
    symbol: str
    side: str
    size: float
    limit: float
    stop: float
    target: float
    placed_at: dt.datetime
    expires_bars: int = 60
    bars_waited: int = 0
    setup_tags: str = ""
    confluences: int = 0


@dataclass
class Fill:
    id: str
    symbol: str
    side: str
    size: float
    entry: float
    exit: float
    stop: float
    target: float
    opened_at: dt.datetime
    closed_at: dt.datetime
    outcome: str          # win | loss | timeout | cancelled
    pnl_cash: float
    r_multiple: float
    risk_cash: float
    costs: float
    setup_tags: str = ""
    confluences: int = 0


class PaperBroker:
    """Deliberately small. It holds cash, at most one position, and a history."""

    def __init__(self, equity=100_000.0, commission_per_contract=0.75,
                 slippage_ticks=1.0):
        # 0.75 per SIDE = 1.50 round turn, which is realistic for MNQ at a
        # discount futures broker. The old 2.50 was full-size NQ pricing and it
        # made the paper system disagree with the backtest by 0.1R a trade.
        self.start_equity = equity
        self.cash = equity
        self.commission = commission_per_contract
        self.slippage_ticks = slippage_ticks
        self.orders = []
        self.positions = []
        self.fills = []

    # ---- account ---------------------------------------------------------
    def equity(self, price=None, inst=None):
        eq = self.cash
        if price is not None and inst is not None:
            for p in self.positions:
                eq += p.unrealised(price, inst)
        return eq

    def _costs(self, size, inst):
        c = self.commission * size * 2                      # in and out
        if inst.is_futures:
            c += self.slippage_ticks * inst.tick_value * size
        return c

    # ---- orders ----------------------------------------------------------
    def place(self, symbol, side, size, limit, stop, target, when,
              tags="", confluences=0, expires_bars=60):
        o = Order(id=uuid.uuid4().hex[:8], symbol=symbol, side=side, size=size,
                  limit=limit, stop=stop, target=target, placed_at=when,
                  expires_bars=expires_bars, setup_tags=tags,
                  confluences=confluences)
        self.orders.append(o)
        return o

    def cancel(self, order):
        if order in self.orders:
            self.orders.remove(order)

    # ---- the tick --------------------------------------------------------
    def on_bar(self, bar, when, inst, risk_lookup=None):
        """Advance one bar: try to fill resting orders, then manage positions.

        `bar` is a mapping with open/high/low/close.
        Returns a list of events for the journal.
        """
        events = []
        hi, lo, close = float(bar["high"]), float(bar["low"]), float(bar["close"])

        # ---- resting limit orders ---------------------------------------
        for o in list(self.orders):
            o.bars_waited += 1
            touched = (hi >= o.limit) if o.side == "short" else (lo <= o.limit)
            invalidated = (hi > o.stop) if o.side == "short" else (lo < o.stop)

            if touched:
                risk = abs(o.limit - o.stop)
                rc = (risk_lookup or (lambda *_: 0.0))(o, inst)
                p = Position(id=o.id, symbol=o.symbol, side=o.side, size=o.size,
                             entry=o.limit, stop=o.stop, target=o.target,
                             opened_at=when, risk_cash=rc,
                             setup_tags=o.setup_tags, confluences=o.confluences)
                self.positions.append(p)
                self.orders.remove(o)
                events.append(("filled", p))
                continue

            if invalidated:
                self.orders.remove(o)
                events.append(("invalidated", o))
                continue

            if o.bars_waited >= o.expires_bars:
                self.orders.remove(o)
                events.append(("expired", o))

        # ---- open positions ---------------------------------------------
        for p in list(self.positions):
            hit_stop = (hi >= p.stop) if p.side == "short" else (lo <= p.stop)
            hit_tgt = (lo <= p.target) if p.side == "short" else (hi >= p.target)
            out = px = None
            if hit_stop and hit_tgt:
                out, px = "loss", p.stop      # pessimistic, same as the backtest
            elif hit_stop:
                out, px = "loss", p.stop
            elif hit_tgt:
                out, px = "win", p.target
            if out is None:
                continue

            move = (px - p.entry) if p.side == "long" else (p.entry - px)
            gross = (move / inst.tick_size * inst.tick_value * p.size
                     if inst.is_futures else move * p.size)
            costs = self._costs(p.size, inst)
            pnl = gross - costs
            r = pnl / p.risk_cash if p.risk_cash else 0.0

            self.cash += pnl
            self.positions.remove(p)
            f = Fill(id=p.id, symbol=p.symbol, side=p.side, size=p.size,
                     entry=p.entry, exit=px, stop=p.stop, target=p.target,
                     opened_at=p.opened_at, closed_at=when, outcome=out,
                     pnl_cash=round(pnl, 2), r_multiple=round(r, 3),
                     risk_cash=round(p.risk_cash, 2), costs=round(costs, 2),
                     setup_tags=p.setup_tags, confluences=p.confluences)
            self.fills.append(f)
            events.append(("closed", f))

        return events

    def force_close(self, price, when, inst, reason="session end"):
        """Flatten everything, e.g. at the end of the trading window."""
        events = []
        for p in list(self.positions):
            move = (price - p.entry) if p.side == "long" else (p.entry - price)
            gross = (move / inst.tick_size * inst.tick_value * p.size
                     if inst.is_futures else move * p.size)
            costs = self._costs(p.size, inst)
            pnl = gross - costs
            r = pnl / p.risk_cash if p.risk_cash else 0.0
            self.cash += pnl
            self.positions.remove(p)
            f = Fill(id=p.id, symbol=p.symbol, side=p.side, size=p.size,
                     entry=p.entry, exit=price, stop=p.stop, target=p.target,
                     opened_at=p.opened_at, closed_at=when, outcome="timeout",
                     pnl_cash=round(pnl, 2), r_multiple=round(r, 3),
                     risk_cash=round(p.risk_cash, 2), costs=round(costs, 2),
                     setup_tags=p.setup_tags, confluences=p.confluences)
            self.fills.append(f)
            events.append(("closed", f))
        for o in list(self.orders):
            self.orders.remove(o)
            events.append(("cancelled", o))
        return events

    def summary(self):
        n = len(self.fills)
        if not n:
            return {"trades": 0, "equity": round(self.cash, 2)}
        rs = [f.r_multiple for f in self.fills]
        wins = [r for r in rs if r > 0]
        return {
            "trades": n,
            "equity": round(self.cash, 2),
            "pnl": round(self.cash - self.start_equity, 2),
            "return_pct": round((self.cash / self.start_equity - 1) * 100, 2),
            "win_rate": round(100 * len(wins) / n, 1),
            "total_R": round(sum(rs), 2),
            "expectancy_R": round(sum(rs) / n, 3),
            "open_positions": len(self.positions),
            "resting_orders": len(self.orders),
        }
