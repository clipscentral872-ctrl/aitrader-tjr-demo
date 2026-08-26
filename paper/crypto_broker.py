"""Crypto on the Alpaca paper account, where brackets do not exist.

Alpaca refuses advanced order classes on crypto:

    crypto orders not allowed for advanced order_class: otoco

So the stop and the target cannot ride along with the entry. They have to be
managed, and how you manage them is a real decision with a real failure mode.

The approach here:

  * a stop_limit sits AT THE BROKER as a safety net, so a position is never
    naked if this process dies, the laptop sleeps, or the network drops
  * the target is watched locally and taken with a market order

That leaves a small race: if price reaches the target we cancel the resting
stop and then sell. If the stop filled in between, the sell is rejected and we
reconcile from the broker rather than from what we assumed. Reconciling from
the broker is the rule everywhere in this file.

Crypto also differs in the boring ways that break things quietly: symbols carry
a slash, quantities are fractional, prices need more than two decimals, and
time in force must be gtc.
"""
import json
import urllib.request as u
import urllib.parse as up
import uuid

from paper.broker import Position, Order, Fill
from paper.alpaca_broker import AlpacaPaperBroker, AlpacaError, _call, _keys
from paper.live_broker import LiveBroker

CRYPTO_DATA = "https://data.alpaca.markets/v1beta3/crypto/us"


def last_price(symbol="BTC/USD"):
    kid, sec = _keys()
    if not kid:
        raise AlpacaError("no keys")
    q = up.urlencode({"symbols": symbol})
    r = u.Request(f"{CRYPTO_DATA}/latest/bars?{q}",
                  headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec})
    d = json.loads(u.urlopen(r, timeout=30).read())
    return float(d["bars"][symbol]["c"])


def bars(symbol="BTC/USD", timeframe="5Min", minutes=4000):
    import pandas as pd
    kid, sec = _keys()
    start = (pd.Timestamp.now("UTC") - pd.Timedelta(minutes=minutes)
             ).strftime("%Y-%m-%dT%H:%M:%SZ")
    q = up.urlencode({"symbols": symbol, "timeframe": timeframe,
                      "start": start, "limit": 10000})
    r = u.Request(f"{CRYPTO_DATA}/bars?{q}",
                  headers={"APCA-API-KEY-ID": kid, "APCA-API-SECRET-KEY": sec})
    d = json.loads(u.urlopen(r, timeout=40).read())
    rows = (d.get("bars") or {}).get(symbol) or []
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df["t"] = pd.to_datetime(df["t"], utc=True)
    df = df.set_index("t").rename(columns={"o": "open", "h": "high", "l": "low",
                                           "c": "close", "v": "volume"})
    return df[["open", "high", "low", "close", "volume"]].sort_index()


def _fmt(x, dp=2):
    return f"{x:.{dp}f}"


class CryptoBroker(LiveBroker):
    """Same surface again, with exits managed by hand because the venue
    will not manage them for us."""

    def __init__(self, equity=100_000.0, symbol="BTC/USD", dry_run=False,
                 log=print, qty_dp=6, px_dp=2):
        self.api = AlpacaPaperBroker(equity=equity, dry_run=dry_run)
        self.symbol = symbol.upper()
        self.log = log
        self.dry_run = dry_run
        self.start_equity = self.api.start_equity
        self.cash = self.start_equity
        self.orders, self.positions, self.fills, self.slippage = [], [], [], []
        self._by_client = {}
        self._stops = {}          # position id -> the broker-side stop order id
        self.qty_dp, self.px_dp = qty_dp, px_dp

    # ---- placing ---------------------------------------------------------
    def place(self, symbol, side, size, limit, stop, target, when,
              expires_bars=60, tags="", confluences=0):
        if side != "long":
            # Alpaca does not allow shorting spot crypto. Silently sizing a
            # short to zero would look like a quiet day rather than a refusal.
            self.log("    skipped: cannot short spot crypto on this account")
            return None

        qty = round(float(size), self.qty_dp)
        try:
            bp = float(self.api.account().get("buying_power", 0))
        except AlpacaError:
            bp = 0.0
        if bp and qty * limit > bp * 0.90:
            qty = round((bp * 0.90) / limit, self.qty_dp)
            self.log(f"    trimmed to {qty} on buying power")
        if qty <= 0:
            self.log("    skipped: size rounds to zero")
            return None

        cid = f"ai-{uuid.uuid4().hex[:12]}"
        body = {"symbol": self.symbol, "qty": _fmt(qty, self.qty_dp),
                "side": "buy", "type": "limit",
                "limit_price": _fmt(limit, self.px_dp),
                "time_in_force": "gtc", "client_order_id": cid}
        if self.dry_run:
            self.log(f"    [dry run] buy {qty} {self.symbol} at {limit:.2f}, "
                     f"stop {stop:.2f}, target {target:.2f}")
            return None
        try:
            r = _call("/orders", "POST", body)
        except AlpacaError as e:
            self.log(f"    order REJECTED by broker: {e}")
            return None

        o = Order(id=r.get("id", cid), symbol=self.symbol, side="long", size=qty,
                  limit=limit, stop=stop, target=target, placed_at=when,
                  expires_bars=expires_bars, setup_tags=tags,
                  confluences=confluences)
        self.orders.append(o)
        return o

    def _place_protective_stop(self, p):
        """A stop that lives at the broker, so the position survives this
        process dying. This is the difference between a bug and a disaster."""
        body = {"symbol": self.symbol, "qty": _fmt(p.size, self.qty_dp),
                "side": "sell", "type": "stop_limit",
                "stop_price": _fmt(p.stop, self.px_dp),
                # a limit slightly through the stop, so it still fills in a
                # fast move rather than sitting there while price runs away
                "limit_price": _fmt(p.stop * 0.997, self.px_dp),
                "time_in_force": "gtc"}
        try:
            r = _call("/orders", "POST", body)
            self._stops[p.id] = r.get("id")
            self.log(f"    protective stop resting at {p.stop:.2f}")
        except AlpacaError as e:
            self.log(f"    COULD NOT PLACE THE STOP: {e}")
            self.log("    closing immediately rather than holding it unprotected")
            self._market_out(p)

    def _market_out(self, p):
        try:
            _call("/orders", "POST", {
                "symbol": self.symbol, "qty": _fmt(p.size, self.qty_dp),
                "side": "sell", "type": "market", "time_in_force": "gtc"})
            return True
        except AlpacaError as e:
            self.log(f"    exit order failed: {e}")
            return False

    # ---- reconciling -----------------------------------------------------
    def on_bar(self, bar, when, inst=None, risk_lookup=None):
        events = []
        if self.dry_run:
            return events
        try:
            live_orders = {o.get("id"): o for o in self.api.open_orders()}
            live_pos = {p.get("symbol"): p for p in self.api.positions()}
        except AlpacaError as e:
            self.log(f"    could not read broker state: {e}")
            return events

        held = live_pos.get(self.symbol)

        # ---- entries ------------------------------------------------------
        for o in list(self.orders):
            if o.id in live_orders:
                o.bars_waited += 1
                if o.bars_waited > o.expires_bars:
                    try:
                        _call(f"/orders/{o.id}", "DELETE")
                    except AlpacaError:
                        pass
                    self.orders.remove(o)
                    events.append(("expired", o))
                continue

            self.orders.remove(o)
            if held:
                actual = float(held.get("avg_entry_price", o.limit))
                self.slippage.append(actual - o.limit)
                p = Position(id=o.id, symbol=o.symbol, side="long", size=o.size,
                             entry=actual, stop=o.stop, target=o.target,
                             opened_at=when, risk_cash=abs(actual - o.stop) * o.size,
                             setup_tags=o.setup_tags, confluences=o.confluences)
                self.positions.append(p)
                events.append(("filled", p))
                self._place_protective_stop(p)
            else:
                events.append(("invalidated", o))

        # ---- exits ---------------------------------------------------------
        for p in list(self.positions):
            if self.symbol not in live_pos:
                # the broker-side stop did its job while we were not looking
                self.positions.remove(p)
                self._stops.pop(p.id, None)
                f = self._close_from_broker(p, when)
                if f:
                    self.cash = self.equity()
                    events.append(("closed", f))
                continue

            try:
                px = last_price(self.symbol)
            except AlpacaError:
                continue
            if px >= p.target:
                self.log(f"    target {p.target:.2f} reached at {px:.2f}")
                sid = self._stops.pop(p.id, None)
                if sid:
                    try:
                        _call(f"/orders/{sid}", "DELETE")
                    except AlpacaError:
                        pass
                self._market_out(p)

        return events

    def force_close(self, price, when, inst=None, reason="session end"):
        events = []
        if self.dry_run:
            return events
        try:
            _call("/orders", "DELETE")
            _call("/positions", "DELETE")
        except AlpacaError:
            pass
        for p in list(self.positions):
            self.positions.remove(p)
            f = self._close_from_broker(p, when)
            if f:
                f.outcome = "timeout"
                events.append(("closed", f))
        self.orders.clear()
        self._stops.clear()
        self.cash = self.equity()
        return events

    def summary(self):
        s = super().summary()
        s["broker"] = "alpaca paper crypto (real)"
        s["protective_stops"] = len(self._stops)
        return s
