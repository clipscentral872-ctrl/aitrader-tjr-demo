"""One position at a time across correlated instruments.

Nasdaq and S&P futures have a daily correlation of +0.954 over the last two
years. They are not two markets; they are one market quoted two ways. Holding
MNQ and MES at once is not diversification, it is a single directional bet of
roughly double the size, and both stops tend to be hit by the same move.

The trap is that it does not look like doubling up. Sizing each leg at 1% feels
like 1% per market. It is 2% on one bet, and the drawdown maths that made 1%
survivable assumed the positions were independent.

So instruments are grouped by what they actually track, and only one position
is allowed open per group. When setups appear on both at once, the better one
is taken and the other is refused with a reason that says why.

Adding an uncorrelated market later (a currency, a commodity) means adding it
to a DIFFERENT group, where a simultaneous position is genuinely a second bet.
"""
from dataclasses import dataclass, field
import datetime as dt

# instruments that track the same underlying move
GROUPS = {
    "us_index": ["NQ", "MNQ", "ES", "MES", "NQ1!", "ES1!", "QQQ", "SPY",
                 "NSXUSD", "SPXUSD"],
    "fx_eur": ["EURUSD", "FXE"],
    "crypto": ["BTCUSD", "BTC/USD", "BTCUSDT", "ETHUSD"],
}

# measured, not assumed: NQ against ES on daily closes over two years
KNOWN_CORRELATION = {("us_index", "us_index"): 0.954}


def group_of(symbol):
    s = (symbol or "").upper().replace("/", "")
    for g, members in GROUPS.items():
        for m in members:
            if s == m.upper().replace("/", ""):
                return g
    return f"other:{s}"


@dataclass
class Book:
    """Which groups currently hold a position, shared across runners.

    Kept deliberately simple. The alternative was a lock file, and a stale lock
    after a crash would silently stop all trading with no obvious cause. An
    in-memory book that resets on restart fails in the safer direction.
    """
    open_by_group: dict = field(default_factory=dict)   # group -> symbol
    refused: list = field(default_factory=list)

    def can_open(self, symbol):
        g = group_of(symbol)
        held = self.open_by_group.get(g)
        if held is None:
            return True, ""
        if held == symbol:
            return False, f"already in {symbol}"
        corr = KNOWN_CORRELATION.get((g, g))
        note = f" (correlation {corr:.2f})" if corr else ""
        return False, (f"{held} is open and tracks the same move as {symbol}"
                       f"{note}; taking both would be one bet of double size")

    def opened(self, symbol):
        self.open_by_group[group_of(symbol)] = symbol

    def closed(self, symbol):
        g = group_of(symbol)
        if self.open_by_group.get(g) == symbol:
            self.open_by_group.pop(g, None)

    def record_refusal(self, symbol, why, when=None):
        self.refused.append((when or dt.datetime.now(), symbol, why))


# One book shared by every runner in the process. Two runners each holding
# their own would defeat the point: the whole rule is that MNQ and MES must
# see each other.
BOOK = Book()


def better_of(a, b):
    """When both fire at once, which setup to take.

    Ranked on what the research actually supports rather than gut feel:
    confluence count first, since two of the eight replicated across markets,
    then reward-to-risk, then the tighter stop. A tie goes to the first, which
    keeps the choice deterministic rather than order-dependent on a dict.
    """
    if a is None:
        return b
    if b is None:
        return a
    ka = (getattr(a, "confluences", 0), getattr(a, "rr", 0),
          -abs(a.entry - a.stop) / max(a.entry, 1e-9))
    kb = (getattr(b, "confluences", 0), getattr(b, "rr", 0),
          -abs(b.entry - b.stop) / max(b.entry, 1e-9))
    return a if ka >= kb else b


def pick_one(setups_by_symbol):
    """Given {symbol: setup_or_None}, return (symbol, setup) or (None, None)."""
    best_sym, best = None, None
    for sym, s in setups_by_symbol.items():
        if s is None:
            continue
        chosen = better_of(best, s)
        if chosen is s:
            best_sym, best = sym, s
    return best_sym, best


if __name__ == "__main__":
    b = Book()
    print("one position at a time across correlated instruments\n")
    for sym in ("MNQ", "MES", "EURUSD", "MNQ"):
        ok, why = b.can_open(sym)
        print(f"  open {sym:<8} {'YES' if ok else 'no '}   {why}")
        if ok:
            b.opened(sym)
    print()
    b.closed("MNQ")
    ok, why = b.can_open("MES")
    print(f"  after closing MNQ, open MES: {'YES' if ok else 'no'}   {why}")
