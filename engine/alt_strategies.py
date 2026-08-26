"""Alternative entry models, tested on the same engine as the ICT one.

Everything here produces the same `Setup` objects and runs through the same
backtester with the same costs and the same pessimistic fills, so the numbers
are directly comparable. Only the entry logic differs.

THE STATISTICAL HEALTH WARNING: testing many strategies on one dataset
guarantees that the best-looking one is flattered by luck. With N strategies the
expected maximum result rises even when every single one is worthless. So the
train/test split is not optional here, and a strategy is only interesting if it
holds up on data it was not chosen on.

Each model is a classic that predates this project, which matters: they were not
invented by looking at this data.
"""
from dataclasses import dataclass
import numpy as np

from .strategy import Setup


def _mk(bar, side, entry, stop, target, name, max_rr=1.5, min_rr=1.0,
        min_stop_pct=0.05, max_stop_pct=1.0):
    """Build a Setup, refusing anything with an unusable stop.

    The floor matters more than it looks. Without it, a bar with a tiny range
    gives a tiny risk, and dividing by a tiny risk produces R multiples in the
    millions. That is not a strategy result, it is a divide-by-almost-zero.
    """
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    stop_pct = risk / entry * 100
    if stop_pct < min_stop_pct or stop_pct > max_stop_pct:
        return None
    rr = abs(target - entry) / risk
    if rr > max_rr:
        target = entry - risk * max_rr if side == "short" else entry + risk * max_rr
        rr = max_rr
    if rr < min_rr:
        return None
    return Setup(bar=bar, side=side, entry=float(entry), stop=float(stop),
                 target=float(target), rr=float(rr), swept_price=0.0,
                 confluences=0, tags=name, efficiency=0.0, reason=name)


# --------------------------------------------------------------------------
# 1. Opening range breakout
# --------------------------------------------------------------------------
def opening_range(df, minutes=30, session_filter=None, stop_buffer=0.25, **kw):
    """Mark the first N minutes of the session, then trade a break of it.

    The oldest day-trading idea there is. Included precisely because it is
    well known: if the data is sane, this should produce a mediocre result
    rather than a brilliant one.
    """
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    idx = df.index
    bars_in_range = max(1, minutes // 5)
    out, day, hi, lo, start_i, fired = [], None, None, None, None, False

    for i in range(1, len(df)):
        if session_filter and not session_filter(idx[i]):
            continue
        d = idx[i].date()
        if d != day:
            day, hi, lo, start_i, fired = d, None, None, i, False
        if start_i is not None and i - start_i < bars_in_range:
            hi = h[i] if hi is None else max(hi, h[i])
            lo = l[i] if lo is None else min(lo, l[i])
            continue
        if hi is None or fired:
            continue
        rng = hi - lo
        if rng <= 0:
            continue
        if c[i] > hi:
            out.append(_mk(i, "long", c[i], lo - rng * stop_buffer, c[i] + rng * 2, "ORB"))
            fired = True
        elif c[i] < lo:
            out.append(_mk(i, "short", c[i], hi + rng * stop_buffer, c[i] - rng * 2, "ORB"))
            fired = True
    return [s for s in out if s]


# --------------------------------------------------------------------------
# 2. Mean reversion off a stretched move
# --------------------------------------------------------------------------
def mean_reversion(df, lookback=20, z=2.0, session_filter=None, **kw):
    """Fade price when it stretches z standard deviations from its own mean.

    High win rate by construction, small winners. A good illustration of why
    win rate on its own tells you nothing.
    """
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    idx = df.index
    out = []
    for i in range(lookback + 1, len(df) - 1):
        if session_filter and not session_filter(idx[i]):
            continue
        w = c[i - lookback:i]
        m, sd = w.mean(), w.std()
        if sd <= 0:
            continue
        dev = (c[i] - m) / sd
        if dev >= z:
            stop = max(h[i - 3:i + 1].max(), c[i] + sd)
            out.append(_mk(i, "short", c[i], stop, m, "meanrev"))
        elif dev <= -z:
            stop = min(l[i - 3:i + 1].min(), c[i] - sd)
            out.append(_mk(i, "long", c[i], stop, m, "meanrev"))
    return [s for s in out if s]


# --------------------------------------------------------------------------
# 3. VWAP reversion
# --------------------------------------------------------------------------
def vwap_reversion(df, dist_pct=0.30, session_filter=None, **kw):
    """Trade back toward the session volume-weighted average price.

    VWAP is what a lot of institutional execution is benchmarked against, so
    there is at least a mechanism behind it rather than pure pattern fitting.
    """
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    v = df["volume"].to_numpy(float)
    idx = df.index
    out, day, cum_pv, cum_v = [], None, 0.0, 0.0
    for i in range(1, len(df) - 1):
        d = idx[i].date()
        if d != day:
            day, cum_pv, cum_v = d, 0.0, 0.0
        tp = (h[i] + l[i] + c[i]) / 3
        cum_pv += tp * max(v[i], 1)
        cum_v += max(v[i], 1)
        if session_filter and not session_filter(idx[i]):
            continue
        if cum_v <= 0:
            continue
        vwap = cum_pv / cum_v
        gap = (c[i] - vwap) / vwap * 100
        if gap >= dist_pct:
            out.append(_mk(i, "short", c[i], h[i - 3:i + 1].max() * 1.0005, vwap, "vwap"))
        elif gap <= -dist_pct:
            out.append(_mk(i, "long", c[i], l[i - 3:i + 1].min() * 0.9995, vwap, "vwap"))
    return [s for s in out if s]


# --------------------------------------------------------------------------
# 4. Trend continuation on a moving-average pullback
# --------------------------------------------------------------------------
def ma_pullback(df, fast=20, slow=50, session_filter=None, **kw):
    """Only trade with the slower trend, entering on a pullback to the faster
    average. Trend following, the other great family besides mean reversion."""
    c = df["close"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    idx = df.index
    s = np.convolve(c, np.ones(fast) / fast, mode="full")[:len(c)]
    L = np.convolve(c, np.ones(slow) / slow, mode="full")[:len(c)]
    out = []
    for i in range(slow + 2, len(df) - 1):
        if session_filter and not session_filter(idx[i]):
            continue
        up = s[i] > L[i]
        touched_up = l[i] <= s[i] and c[i] > s[i]
        touched_dn = h[i] >= s[i] and c[i] < s[i]
        rng = max(h[i] - l[i], 1e-9)
        if up and touched_up:
            out.append(_mk(i, "long", c[i], l[i] - rng * 0.25, c[i] + rng * 2, "ma_pb"))
        elif (not up) and touched_dn:
            out.append(_mk(i, "short", c[i], h[i] + rng * 0.25, c[i] - rng * 2, "ma_pb"))
    return [s_ for s_ in out if s_]


# --------------------------------------------------------------------------
# 5. Previous-day level reversion
# --------------------------------------------------------------------------
def pdh_pdl_fade(df, session_filter=None, **kw):
    """Fade the first touch of yesterday's high or low.

    Uses the same levels as the ICT model but with the opposite logic: rather
    than waiting for a sweep and a structure break, it simply fades the touch.
    A useful control - if this does as well as the ICT model, the elaborate
    sequence is not adding anything.
    """
    import pandas as pd
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    idx = df.index
    day = idx.normalize()
    dh = pd.Series(h, index=idx).groupby(day).max().shift(1).reindex(day).to_numpy()
    dl = pd.Series(l, index=idx).groupby(day).min().shift(1).reindex(day).to_numpy()
    out, seen_hi, seen_lo, cur = [], False, False, None
    for i in range(1, len(df) - 1):
        d = idx[i].date()
        if d != cur:
            cur, seen_hi, seen_lo = d, False, False
        if session_filter and not session_filter(idx[i]):
            continue
        if np.isnan(dh[i]) or np.isnan(dl[i]):
            continue
        rng = max(h[i] - l[i], 1e-9)
        if not seen_hi and h[i] >= dh[i]:
            seen_hi = True
            out.append(_mk(i, "short", c[i], h[i] + rng * 0.3, c[i] - rng * 2, "pdh_fade"))
        if not seen_lo and l[i] <= dl[i]:
            seen_lo = True
            out.append(_mk(i, "long", c[i], l[i] - rng * 0.3, c[i] + rng * 2, "pdl_fade"))
    return [s for s in out if s]


ALL = {
    "opening_range": opening_range,
    "mean_reversion": mean_reversion,
    "vwap_reversion": vwap_reversion,
    "ma_pullback": ma_pullback,
    "pdh_pdl_fade": pdh_pdl_fade,
}
