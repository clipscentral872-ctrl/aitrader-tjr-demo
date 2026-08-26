"""Trade the real Alpaca paper account instead of a local simulation.

A simulated broker is optimistic in ways you only discover by leaving it. It
never rejects an order, never partially fills, never has a position out of sync,
never rate-limits. Alpaca's paper account does all of those, for free, with no
real money at stake. That is exactly the right place to find out.

Presents the same surface as PaperBroker so `live.py` can use either.
"""
import json, os, time, uuid
import urllib.request as u
import urllib.parse as up
import datetime as dt

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEYFILE = os.path.join(ROOT, "config", "alpaca.key")
BASE = "https://paper-api.alpaca.markets/v2"


def _keys():
    kid = os.environ.get("ALPACA_KEY_ID")
    sec = os.environ.get("ALPACA_SECRET")
    if kid and sec:
        return kid.strip(), sec.strip()
    if os.path.exists(KEYFILE):
        d = {}
        for line in open(KEYFILE, encoding="utf-8"):
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                d[k.strip().lower()] = v.strip()
        return d.get("key_id"), d.get("secret")
    return None, None


class AlpacaError(Exception):
    pass


def _call(path, method="GET", body=None, tries=3):
    kid, sec = _keys()
    if not kid:
        raise AlpacaError("no Alpaca keys found")
    data = json.dumps(body).encode() if body is not None else None
    req = u.Request(BASE + path, data=data, method=method, headers={
        "APCA-API-KEY-ID": kid,
        "APCA-API-SECRET-KEY": sec,
        "Content-Type": "application/json",
        "User-Agent": "AITrader/1.0",
    })
    for i in range(tries):
        try:
            r = u.urlopen(req, timeout=30)
            raw = r.read()
            return json.loads(raw) if raw else {}
        except Exception as e:
            # 429 and 5xx are worth retrying; a 4xx is our own mistake
            code = getattr(e, "code", None)
            if code and 400 <= code < 500 and code != 429:
                detail = ""
                try:
                    detail = e.read().decode()[:200]
                except Exception:
                    pass
                raise AlpacaError(f"HTTP {code}: {detail}") from e
            if i == tries - 1:
                raise AlpacaError(f"{type(e).__name__}: {str(e)[:120]}") from e
            time.sleep(1.5 * (i + 1))


class AlpacaPaperBroker:
    """Same surface as PaperBroker, backed by a real brokerage account."""

    def __init__(self, equity=None, dry_run=False):
        self.dry_run = dry_run
        self.fills = []
        self._orders = {}
        acct = self.account()
        self.start_equity = float(acct.get("equity", equity or 100_000))
        self.cash = self.start_equity

    # ---- account ---------------------------------------------------------
    def account(self):
        return _call("/account")

    def equity(self, price=None, inst=None):
        try:
            return float(self.account().get("equity", self.cash))
        except AlpacaError:
            return self.cash

    def positions(self):
        try:
            return _call("/positions")
        except AlpacaError:
            return []

    def clock(self):
        return _call("/clock")

    def is_open(self):
        try:
            return bool(self.clock().get("is_open"))
        except AlpacaError:
            return False

    # ---- orders ----------------------------------------------------------
    def place_bracket(self, symbol, side, qty, limit, stop, target,
                      tif="day", client_id=None):
        """A limit entry with a stop and a target attached.

        Alpaca calls this a bracket. Doing it in one request matters: placing
        the entry and then the exits separately leaves a window where a fill
        has no protection on it.
        """
        qty = int(qty)
        if qty < 1:
            raise AlpacaError("quantity rounds to zero")
        body = {
            "symbol": symbol.upper(),
            "qty": str(qty),
            "side": "buy" if side in ("long", "buy") else "sell",
            "type": "limit",
            "limit_price": f"{limit:.2f}",
            "time_in_force": tif,
            "order_class": "bracket",
            "take_profit": {"limit_price": f"{target:.2f}"},
            "stop_loss": {"stop_price": f"{stop:.2f}"},
            "client_order_id": client_id or f"ai-{uuid.uuid4().hex[:12]}",
        }
        if self.dry_run:
            print(f"    [dry run] would place {body['side']} {qty} {symbol} "
                  f"limit {limit:.2f} stop {stop:.2f} target {target:.2f}")
            return {"id": "dry-run", "status": "accepted", **body}
        o = _call("/orders", "POST", body)
        self._orders[o.get("id")] = o
        return o

    def open_orders(self):
        try:
            return _call("/orders?" + up.urlencode({"status": "open", "limit": 100}))
        except AlpacaError:
            return []

    def cancel_all(self):
        if self.dry_run:
            return
        try:
            _call("/orders", "DELETE")
        except AlpacaError:
            pass

    def close_all(self):
        if self.dry_run:
            return
        try:
            _call("/positions", "DELETE")
        except AlpacaError:
            pass

    # ---- reconciliation --------------------------------------------------
    def recent_fills(self, since_minutes=1440):
        """What actually happened, read back from the broker rather than
        assumed. Local state drifts; the broker is the truth."""
        after = (dt.datetime.now(dt.timezone.utc)
                 - dt.timedelta(minutes=since_minutes)).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            return _call("/orders?" + up.urlencode({
                "status": "closed", "after": after, "limit": 200, "direction": "desc"}))
        except AlpacaError:
            return []

    def summary(self):
        try:
            a = self.account()
            eq = float(a.get("equity", 0))
            return {
                "equity": round(eq, 2),
                "cash": round(float(a.get("cash", 0)), 2),
                "buying_power": round(float(a.get("buying_power", 0)), 2),
                "pnl": round(eq - self.start_equity, 2),
                "return_pct": round((eq / self.start_equity - 1) * 100, 3)
                if self.start_equity else 0,
                "open_positions": len(self.positions()),
                "resting_orders": len(self.open_orders()),
                "status": a.get("status"),
            }
        except AlpacaError as e:
            return {"error": str(e)}


if __name__ == "__main__":
    try:
        b = AlpacaPaperBroker()
        print("connected to the real paper account")
        for k, v in b.summary().items():
            print(f"  {k:<16} {v}")
        c = b.clock()
        print(f"  market open      {c.get('is_open')}")
        print(f"  next open        {c.get('next_open')}")
        print(f"  next close       {c.get('next_close')}")
    except AlpacaError as e:
        print("could not connect:", e)
