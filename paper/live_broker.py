"""Adapter: the PaperBroker surface, but orders go to the real Alpaca account.

live.py should not care which broker it is driving. It calls place(), then
on_bar() each bar and reads back events. This class keeps that shape and
translates it into real orders, then reads the fills back from Alpaca rather
than assuming them.

The important difference from the simulation: we do not decide what filled.
The broker does, and we ask. Every discrepancy between what we expected and
what happened is recorded rather than smoothed over, because those
discrepancies are the entire reason for trading a real paper account.
"""
import uuid

from paper.broker import Position, Order, Fill
from paper.alpaca_broker import AlpacaPaperBroker, AlpacaError


class LiveBroker:
    def __init__(self, equity=100_000.0, symbol="QQQ", dry_run=False, log=print):
        self.api = AlpacaPaperBroker(equity=equity, dry_run=dry_run)
        self.symbol = symbol.upper()
        self.log = log
        self.dry_run = dry_run
        self.start_equity = self.api.start_equity
        self.cash = self.start_equity
        self.orders = []          # submitted, not yet filled
        self.positions = []       # what Alpaca says we hold
        self.fills = []
        self.slippage = []        # expected entry vs actual, in price terms
        self._by_client = {}

    # ---- account ---------------------------------------------------------
    def equity(self, price=None, inst=None):
        eq = self.api.equity()
        self.cash = eq
        return eq

    # ---- placing ---------------------------------------------------------
    def place(self, symbol, side, size, limit, stop, target, when,
              expires_bars=60, tags="", confluences=0):
        """Submit a bracket. Size is contracts in the simulation; here it is
        shares, so it must be a whole number and at least one."""
        qty = max(1, int(round(size)))

        # The risk gate sizes off the stop distance, which says nothing about
        # notional. A tight stop asks for a very large position, and the broker
        # would reject the whole order. Cap it here instead, and say so.
        try:
            bp = float(self.api.account().get("buying_power", 0))
        except AlpacaError:
            bp = 0.0
        if bp:
            room = int((bp * 0.90) / max(limit, 0.01))
            if qty > room:
                self.log(f"    trimming {qty} shares to {room}, the most buying "
                         f"power allows. Risk on this trade is now smaller than planned.")
                qty = max(1, room)

        cid = f"ai-{uuid.uuid4().hex[:12]}"
        o = Order(id=cid, symbol=self.symbol, side=side, size=qty, limit=limit,
                  stop=stop, target=target, placed_at=when,
                  expires_bars=expires_bars, setup_tags=tags,
                  confluences=confluences)
        try:
            r = self.api.place_bracket(self.symbol, side, qty, limit, stop, target,
                                       client_id=cid)
        except AlpacaError as e:
            # A rejection is information, not a failure to hide. The simulation
            # never rejected anything, which is what made it optimistic.
            self.log(f"    order REJECTED by broker: {e}")
            return None
        o.id = r.get("id", cid)
        self._by_client[o.id] = o
        self.orders.append(o)
        return o

    def cancel(self, order):
        if order in self.orders:
            self.orders.remove(order)

    # ---- reconciling -----------------------------------------------------
    def on_bar(self, bar, when, inst=None, risk_lookup=None):
        """Ask the broker what happened, and turn it into the same events the
        simulation emits."""
        events = []
        if self.dry_run:
            return events
        try:
            live_orders = {o.get("id"): o for o in self.api.open_orders()}
            live_pos = {p.get("symbol"): p for p in self.api.positions()}
        except AlpacaError as e:
            self.log(f"    could not read broker state: {e}")
            return events

        # ---- orders that are no longer resting -----------------------------
        for o in list(self.orders):
            if o.id in live_orders:
                o.bars_waited += 1
                if o.bars_waited > o.expires_bars:
                    self.api.cancel_all()
                    self.orders.remove(o)
                    events.append(("expired", o))
                continue

            self.orders.remove(o)
            pos = live_pos.get(self.symbol)
            if pos:
                actual = float(pos.get("avg_entry_price", o.limit))
                slip = actual - o.limit if o.side == "long" else o.limit - actual
                self.slippage.append(slip)
                risk = abs(actual - o.stop) * o.size
                p = Position(id=o.id, symbol=o.symbol, side=o.side, size=o.size,
                             entry=actual, stop=o.stop, target=o.target,
                             opened_at=when, risk_cash=risk,
                             setup_tags=o.setup_tags, confluences=o.confluences)
                self.positions.append(p)
                self._by_client[o.id] = p
                events.append(("filled", p))
                if abs(slip) > 0.005:
                    self.log(f"    filled {slip:+.3f} away from the price we asked for")
            else:
                events.append(("invalidated", o))

        # ---- positions that have closed -------------------------------------
        for p in list(self.positions):
            if self.symbol in live_pos:
                continue
            self.positions.remove(p)
            f = self._close_from_broker(p, when)
            if f:
                self.cash = self.equity()
                events.append(("closed", f))
        return events

    def _close_from_broker(self, p, when):
        """Find the exit price from the broker's own record of the fill."""
        exit_px = None
        for o in self.api.recent_fills(since_minutes=2880):
            if o.get("symbol") != self.symbol or o.get("status") != "filled":
                continue
            sd = o.get("side")
            closing = (sd == "sell") if p.side == "long" else (sd == "buy")
            if closing and o.get("filled_avg_price"):
                exit_px = float(o["filled_avg_price"])
                break
        if exit_px is None:
            self.log("    position closed but no matching fill found; using the stop")
            exit_px = p.stop

        move = (exit_px - p.entry) if p.side == "long" else (p.entry - exit_px)
        pnl = move * p.size
        r = pnl / p.risk_cash if p.risk_cash else 0.0
        hit_target = (exit_px >= p.target) if p.side == "long" else (exit_px <= p.target)
        f = Fill(id=p.id, symbol=p.symbol, side=p.side, size=p.size, entry=p.entry,
                 exit=exit_px, stop=p.stop, target=p.target, opened_at=p.opened_at,
                 closed_at=when, outcome="win" if pnl > 0 else "loss",
                 pnl_cash=round(pnl, 2), r_multiple=round(r, 3),
                 risk_cash=round(p.risk_cash, 2), costs=0.0,
                 setup_tags=p.setup_tags + (" target" if hit_target else " stop"),
                 confluences=p.confluences)
        self.fills.append(f)
        return f

    # ---- shutdown ---------------------------------------------------------
    def force_close(self, price, when, inst=None, reason="session end"):
        events = []
        if self.dry_run:
            return events
        self.api.cancel_all()
        self.api.close_all()
        for p in list(self.positions):
            self.positions.remove(p)
            f = self._close_from_broker(p, when)
            if f:
                f.outcome = "timeout"
                events.append(("closed", f))
        self.orders.clear()
        self.cash = self.equity()
        return events

    def summary(self):
        s = self.api.summary()
        s["trades"] = len(self.fills)
        if self.slippage:
            s["avg_slippage"] = round(sum(self.slippage) / len(self.slippage), 4)
            s["worst_slippage"] = round(max(self.slippage), 4)
        s["broker"] = "alpaca paper (real)"
        return s
