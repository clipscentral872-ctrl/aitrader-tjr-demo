"""SMT divergence: TJR's signature confluence, and the only one that brings
information from outside the chart being traded.

Every confluence in strategy.py is derived from the same price series. They
describe the same bars from eight angles, which is why they correlate with each
other and why stacking them added so little. SMT is different in kind: it asks
what a second, correlated instrument is doing at the same moment.

TJR's rule, in his own framing:

    Bearish SMT   one index makes a high then a LOWER high, while the other
                  makes a high then a HIGHER high. Bearish for both.
    Bullish SMT   one index makes a low then a HIGHER low, while the other
                  makes a low then a LOWER low. Bullish for both.

And the condition he is emphatic about:

    "outside of sweeping out draws and liquidity, these things will show up all
    the time and will be pretty much useless to us"

So divergence is only counted when it coincides with a liquidity sweep. Counting
it everywhere would generate a signal on most bars and mean nothing, which is
exactly what he warns about.

The pair used here is QQQ and SPY, which is his Nasdaq versus S&P 500.

No-lookahead throughout: swings come from `known_tail`, so a pivot is invisible
until the bars that confirm it have closed.
"""
from dataclasses import dataclass
import numpy as np
import pandas as pd

from engine import structure as S


@dataclass
class Divergence:
    bar: int
    direction: str        # "bull" | "bear"
    leader: str           # which instrument is leading
    detail: str


def align(a, b):
    """Put two instruments on one shared clock.

    Anything not present in both is dropped. A divergence measured across two
    series with different timestamps is comparing different moments, which
    would manufacture signals rather than find them.
    """
    idx = a.index.intersection(b.index)
    return a.loc[idx].sort_index(), b.loc[idx].sort_index()


def _last_two(swings, bar, kind):
    known = S.known_tail(swings, bar, 40)
    got = [s for s in known if s.kind == kind][-2:]
    return got if len(got) == 2 else None


def detect(df_a, df_b, name_a="A", name_b="B", left=2, right=2, lookback=60):
    """Every bar where the two instruments disagree about direction.

    Returns a dict of bar index -> Divergence, for the FIRST instrument.
    """
    ha, la = df_a["high"].to_numpy(float), df_a["low"].to_numpy(float)
    hb, lb = df_b["high"].to_numpy(float), df_b["low"].to_numpy(float)
    sw_a = S.find_swings(ha, la, left, right)
    sw_b = S.find_swings(hb, lb, left, right)

    out = {}
    for i in range(lookback, len(df_a)):
        # ---- bearish: one makes a lower high while the other makes a higher high
        Ah, Bh = _last_two(sw_a, i, "high"), _last_two(sw_b, i, "high")
        if Ah and Bh:
            a_lower = Ah[1].price < Ah[0].price
            b_higher = Bh[1].price > Bh[0].price
            if a_lower and b_higher:
                out[i] = Divergence(i, "bear", name_a,
                                    f"{name_a} lower high while {name_b} higher high")
                continue
            if (not a_lower) and Bh[1].price < Bh[0].price and Ah[1].price > Ah[0].price:
                out[i] = Divergence(i, "bear", name_b,
                                    f"{name_b} lower high while {name_a} higher high")
                continue

        # ---- bullish: one makes a higher low while the other makes a lower low
        Al, Bl = _last_two(sw_a, i, "low"), _last_two(sw_b, i, "low")
        if Al and Bl:
            a_higher = Al[1].price > Al[0].price
            b_lower = Bl[1].price < Bl[0].price
            if a_higher and b_lower:
                out[i] = Divergence(i, "bull", name_a,
                                    f"{name_a} higher low while {name_b} lower low")
                continue
            if (not a_higher) and Bl[1].price > Bl[0].price and Al[1].price < Al[0].price:
                out[i] = Divergence(i, "bull", name_b,
                                    f"{name_b} higher low while {name_a} lower low")
    return out


def agrees(divs, bar, side, window=6):
    """Is there a divergence near this bar pointing the same way as the trade?

    A small window, because TJR ties the divergence to the sweep itself. Allowing
    a wide window would let any divergence in the neighbourhood count, which is
    the "shows up all the time" failure he warns about.
    """
    want = "bear" if side == "short" else "bull"
    for b in range(max(0, bar - window), bar + 1):
        d = divs.get(b)
        if d and d.direction == want:
            return d
    return None


def summarise(divs, n_bars):
    if not divs:
        print("  no divergences found")
        return
    bull = sum(1 for d in divs.values() if d.direction == "bull")
    bear = len(divs) - bull
    print(f"  {len(divs):,} divergences over {n_bars:,} bars "
          f"({len(divs)/n_bars*100:.1f}% of bars)")
    print(f"    {bull:,} bullish, {bear:,} bearish")
    if len(divs) / n_bars > 0.25:
        print("    That is a lot. TJR's point stands: on its own this fires too")
        print("    often to be worth anything. It only means something at a sweep.")
