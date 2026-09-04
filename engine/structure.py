"""ICT / SMC structural primitives, exactly as the two courses define them.

THE ONE RULE IN THIS FILE: no lookahead. Every function may only use bars at or
before the index it is asked about. A swing high is not confirmed until N bars
have closed after it, and this code refuses to know about it before then. That
single discipline is what separates a backtest from a fantasy, and it is the
most common way these systems end up showing 65% win rates that do not exist.
"""
from dataclasses import dataclass, field
import numpy as np


# --------------------------------------------------------------------------
# swings
# --------------------------------------------------------------------------
@dataclass
class Swing:
    idx: int          # bar where the extreme actually sits
    price: float
    kind: str         # "high" | "low"
    confirmed_at: int # bar at which we were ALLOWED to know about it


def find_swings(high, low, left=2, right=2):
    """Fractal pivots. A pivot at i needs `left` lower bars before and `right`
    after, so it is only knowable at i + right. That is recorded explicitly."""
    n = len(high)
    out = []
    for i in range(left, n - right):
        h = high[i]
        if all(high[i - k] < h for k in range(1, left + 1)) and \
           all(high[i + k] < h for k in range(1, right + 1)):
            out.append(Swing(i, float(h), "high", i + right))
        l = low[i]
        if all(low[i - k] > l for k in range(1, left + 1)) and \
           all(low[i + k] > l for k in range(1, right + 1)):
            out.append(Swing(i, float(l), "low", i + right))
    out.sort(key=lambda s: s.confirmed_at)
    return out


def swings_known_at(swings, bar):
    """Only the swings a live trader could already have seen at `bar`.

    `find_swings` returns them sorted by confirmed_at, so this is a binary
    search rather than a scan. That matters: the naive filter made the whole
    backtest O(bars x swings), which is fine over three months and never
    finishes over four years.
    """
    return swings[:known_count(swings, bar)]


def known_count(swings, bar):
    """How many swings are knowable at `bar`. Binary search, no copying."""
    lo, hi = 0, len(swings)
    while lo < hi:
        mid = (lo + hi) // 2
        if swings[mid].confirmed_at <= bar:
            lo = mid + 1
        else:
            hi = mid
    return lo


def known_tail(swings, bar, n=60):
    """The last `n` knowable swings only.

    Callers here never need more than a handful of recent pivots, and slicing
    the whole prefix each time was copying a six-figure list on every bar.
    """
    k = known_count(swings, bar)
    return swings[max(0, k - n):k]


# --------------------------------------------------------------------------
# market structure  (Phase 3, TJR Part 3)
# --------------------------------------------------------------------------
def structure_state(swings, bar):
    """Return ('bull'|'bear'|'range', last_high_swing, last_low_swing) as known
    at `bar`. Bullish = the most recent confirmed highs and lows are rising."""
    known = known_tail(swings, bar, 24)
    highs = [s for s in known if s.kind == "high"][-3:]
    lows = [s for s in known if s.kind == "low"][-3:]
    if len(highs) < 2 or len(lows) < 2:
        return "range", (highs[-1] if highs else None), (lows[-1] if lows else None)
    hh = highs[-1].price > highs[-2].price
    hl = lows[-1].price > lows[-2].price
    lh = highs[-1].price < highs[-2].price
    ll = lows[-1].price < lows[-2].price
    if hh and hl:
        state = "bull"
    elif lh and ll:
        state = "bear"
    else:
        state = "range"
    return state, highs[-1], lows[-1]


def break_of_structure(close, swings, bar, direction):
    """Has the level that mattered just been broken, as known at `bar`?

    Bearish BOS = close below the most recent confirmed swing LOW.
    Bullish BOS = close above the most recent confirmed swing HIGH.
    This is the "watch one line" rule from the Phase 8 notes.
    """
    known = known_tail(swings, bar, 16)
    if direction == "bear":
        lows = [s for s in known if s.kind == "low"]
        if not lows:
            return None
        lvl = lows[-1]
        if close[bar] < lvl.price <= close[bar - 1]:
            return lvl
    else:
        highs = [s for s in known if s.kind == "high"]
        if not highs:
            return None
        lvl = highs[-1]
        if close[bar] > lvl.price >= close[bar - 1]:
            return lvl
    return None


# --------------------------------------------------------------------------
# liquidity  (Phase 4-6, TJR Part 4)
# --------------------------------------------------------------------------
def nth_swing(swings, bar, kind, n=2):
    """The nth most recent CONFIRMED swing of a kind, as known at `bar`.

    His stop rule is not the level that was just swept: he places it beyond the
    SECOND low on a long, the second high on a short. A stop at the first swing
    sits inside the noise the sweep just created and gets taken out by the same
    spike that made the setup; one swing further back sits beyond it.

    Returns None when fewer than n such swings have confirmed yet.
    """
    got = [x for x in known_tail(swings, bar, 60) if x.kind == kind]
    return got[-n] if len(got) >= n else None


def equal_levels(swings, bar, tol_pct=0.05, min_touches=2):
    """Equal highs / equal lows: the stop-loss magnets. `tol_pct` is how close
    two swings must be, as a percentage of price, to count as 'equal'."""
    known = known_tail(swings, bar, 60)
    pools = []
    for kind in ("high", "low"):
        pts = [s for s in known if s.kind == kind][-12:]
        used = set()
        for i, a in enumerate(pts):
            if i in used:
                continue
            grp = [a]
            for j in range(i + 1, len(pts)):
                b = pts[j]
                if abs(b.price - a.price) / a.price * 100 <= tol_pct:
                    grp.append(b); used.add(j)
            if len(grp) >= min_touches:
                pools.append({
                    "kind": kind,
                    "price": float(np.mean([g.price for g in grp])),
                    "touches": len(grp),
                    "last_idx": max(g.idx for g in grp),
                })
    return pools


def sweep(high, low, close, bar, level, side):
    """A liquidity sweep, the INDUCEMENT of the courses.

    Price must WICK THROUGH the level and CLOSE BACK on the original side.
    That closing-back is what makes it a sweep rather than a real break, and
    it is the distinction both courses hammer on.
    """
    if side == "high":
        return high[bar] > level and close[bar] < level
    return low[bar] < level and close[bar] > level


def pool_spent(pool, high, low, bar, lookback=60):
    """Has the liquidity at this level already been taken?

    A pool is a shelf of resting stops, and it is the reason price is drawn
    there at all. Once price has traded through it those orders are filled and
    there is nothing left to reach for.

    This is the mistake TJR walks through on the losing trade in his teaching
    session: every step of the setup was right, but the lows below had already
    been swept earlier in the move. Entering short into spent liquidity puts
    you in exactly where the desk that filled those orders is taking profit,
    which is the opposite side of the trade you think you are on.

    Measured from the pool's last touch when the pool knows it (equal highs and
    lows carry `last_idx`), and over a bounded recent window when it does not
    (the named session and daily levels carry no index).
    """
    a = int(pool["last_idx"]) if pool.get("last_idx") is not None \
        else bar - int(lookback)
    a = max(0, min(a, bar - 1))
    if a >= bar:
        return False
    seg_hi, seg_lo = high[a + 1:bar + 1], low[a + 1:bar + 1]
    if len(seg_hi) == 0:
        return False
    if pool["kind"] == "low":
        return float(np.min(seg_lo)) < pool["price"]
    return float(np.max(seg_hi)) > pool["price"]


# --------------------------------------------------------------------------
# order blocks and imbalances  (Phase 5, Phase 8)
# --------------------------------------------------------------------------
def find_ifc(open_, close, bar, direction, lookback=12):
    """The institutionally funded candle / order block.

    Bearish: the LAST UP candle before price dropped away.
    Bullish: the LAST DOWN candle before price rose.
    Searched backwards from `bar`, never forwards.
    """
    lo = max(1, bar - lookback)
    if direction == "bear":
        for i in range(bar, lo - 1, -1):
            if close[i] > open_[i]:
                return i
    else:
        for i in range(bar, lo - 1, -1):
            if close[i] < open_[i]:
                return i
    return None


def find_imbalance(high, low, bar, direction, lookback=12):
    """Fair value gap: a 3-candle gap where candle 1 and candle 3 do not overlap.

    Returns (gap_low, gap_high, middle_index) for the most recent qualifying gap
    at or before `bar`. This is the level the Phase 8 entry limit sits on.
    """
    lo = max(2, bar - lookback)
    for i in range(bar, lo - 1, -1):
        a, c = i - 2, i
        if a < 0:
            break
        if direction == "bear" and low[a] > high[c]:
            return float(high[c]), float(low[a]), i - 1
        if direction == "bull" and high[a] < low[c]:
            return float(high[a]), float(low[c]), i - 1
    return None


def all_imbalances(high, low, bar, direction, lookback=48):
    """EVERY three-candle gap in range, newest first.

    find_imbalance returns on the first match scanning backwards, so it only
    ever sees the most recent gap. On 17 Aug 2026 that meant a 1.75-point gap
    formed at 09:20 beat the 20-point gap from 08:30 that price was actually
    trading into, and raising the lookback changed nothing because the loop
    exited before reaching it. He treats every UNFILLED gap as live, so all of
    them have to be candidates.
    """
    out = []
    lo = max(2, bar - lookback)
    for i in range(bar, lo - 1, -1):
        a, c_ = i - 2, i
        if a < 0:
            break
        if direction == "bear" and low[a] > high[c_]:
            out.append((float(high[c_]), float(low[a]), i - 1))
        elif direction == "bull" and high[a] < low[c_]:
            out.append((float(high[a]), float(low[c_]), i - 1))
    return out


def pick_gap(gaps, high_i, low_i, min_size=0.0):
    """Of several live gaps, the one price has actually come back into.

    A gap only matters when price returns to it: that is the whole premise of
    the continuation entry. So candidates the current bar has traded into win
    outright, and among those the LARGER gap wins, being the more significant
    imbalance rather than a two-tick artefact of a quiet minute.

    Falls back to the most recent gap when price is not in any of them, which
    preserves the old behaviour rather than silently finding nothing.
    """
    if not gaps:
        return None
    touched = [g for g in gaps
               if high_i >= g[0] and low_i <= g[1] and (g[1] - g[0]) >= min_size]
    if touched:
        return max(touched, key=lambda g: g[1] - g[0])
    return gaps[0]


# --------------------------------------------------------------------------
# premium / discount  (Phase 3)
# --------------------------------------------------------------------------
def dealing_range(high, low, bar, lookback=120):
    """The range premium/discount is measured INSIDE.

    Using only the last two pivots gives a range so tight that price is almost
    always pinned at one end. The courses mean the recent swing range, so that
    is what this returns: the highest high and lowest low over `lookback` bars
    up to and including `bar`.
    """
    lo_i = max(0, bar - lookback)
    seg_h = high[lo_i:bar + 1]
    seg_l = low[lo_i:bar + 1]
    if len(seg_h) == 0:
        return None, None
    return float(seg_h.max()), float(seg_l.min())


def premium_discount(price, hi, lo):
    """>0.5 premium (expensive, look to sell), <0.5 discount (cheap, look to buy)."""
    if hi is None or lo is None or hi <= lo:
        return 0.5
    return float(np.clip((price - lo) / (hi - lo), 0.0, 1.0))


# --------------------------------------------------------------------------
# internal vs external structure  (Phase 3 videos 1-2)
# --------------------------------------------------------------------------
def external_swings(high, low, left=6, right=6):
    """The BIG swings - the impulse legs. Wider fractal = fewer, more meaningful
    pivots. This is the 'staircase' in the notes."""
    return find_swings(high, low, left, right)


def impulse_zone(ext_swings, bar, direction):
    """The external supply (bear) or demand (bull) zone the pullback must reach.

    In a downtrend that is the most recent confirmed external LOWER HIGH: the
    ceiling the pullback is climbing back toward.
    """
    known = known_tail(ext_swings, bar, 12)
    want = "high" if direction == "bear" else "low"
    pts = [s for s in known if s.kind == want]
    return pts[-1] if pts else None


def pullback_efficiency(high, low, bar, zone, direction, since_bar,
                        sweep_bar=None, sweep_extreme=None):
    """How deep the pullback retraced back into the impulse leg.

    The previous version of this could not filter anything, and the reason is
    worth keeping written down. It measured from `since_bar`, which sits thirty
    bars BEFORE the sweep, so the highest high in its window was the sweep
    spike itself. A sweep exceeds the level by definition, so the ratio was
    always at or above 1.0. Varying the threshold from 50% to 80% changed
    nothing at all: identical trade counts, identical expectancy.

    What it should measure is the retrace AFTER the impulse:

        sweep       price spikes through the level        (the high, for a bear)
        impulse     price drops away from it              (the low)
        pullback    price climbs back toward the sweep    (how far is the answer)

    So efficiency is (pullback reach - impulse extreme) as a fraction of
    (sweep extreme - impulse extreme). 1.0 means price came all the way back to
    where the sweep happened. 0.5 means it managed half.

    Everything is measured up to `bar` and nothing after it.
    """
    if direction not in ("bear", "bull"):
        return 0.0

    # fall back to the old anchor only if the caller has not supplied a sweep
    if sweep_bar is None or sweep_extreme is None:
        if zone is None or since_bar >= bar:
            return 0.0
        sweep_bar = since_bar
        seg = high[since_bar:bar + 1] if direction == "bear" else low[since_bar:bar + 1]
        if len(seg) == 0:
            return 0.0
        sweep_extreme = float(seg.max() if direction == "bear" else seg.min())

    if sweep_bar >= bar:
        return 0.0

    # ---- the impulse: how far price travelled away from the sweep ---------
    seg_h = high[sweep_bar:bar + 1]
    seg_l = low[sweep_bar:bar + 1]
    if len(seg_h) < 2:
        return 0.0

    if direction == "bear":
        j = int(np.argmin(seg_l))              # the impulse low
        impulse = float(seg_l[j])
        span = float(sweep_extreme) - impulse
        if span <= 0:
            return 0.0
        # ---- the pullback: only what happened AFTER that low --------------
        after = seg_h[j:]
        if len(after) == 0:
            return 0.0
        reach = float(after.max())
        return float(np.clip((reach - impulse) / span, 0.0, 2.0))

    j = int(np.argmax(seg_h))                  # the impulse high
    impulse = float(seg_h[j])
    span = impulse - float(sweep_extreme)
    if span <= 0:
        return 0.0
    after = seg_l[j:]
    if len(after) == 0:
        return 0.0
    reach = float(after.min())
    return float(np.clip((impulse - reach) / span, 0.0, 2.0))


def internal_counter_trend(int_swings, bar, direction, window=40):
    """Did internal structure run AGAINST the external trend during the pullback?

    That is what a proper complex pullback looks like: in a downtrend the
    retrace makes internal higher highs and higher lows on its way up.
    """
    known = [s for s in known_tail(int_swings, bar, 30) if s.idx >= bar - window]
    highs = [s for s in known if s.kind == "high"][-2:]
    lows = [s for s in known if s.kind == "low"][-2:]
    if len(highs) < 2 or len(lows) < 2:
        return False
    rising = highs[-1].price > highs[-2].price and lows[-1].price > lows[-2].price
    falling = highs[-1].price < highs[-2].price and lows[-1].price < lows[-2].price
    return rising if direction == "bear" else falling


def gap_still_valid(close, gap_lo, gap_hi, from_bar, bar, direction):
    """TJR: a fair value gap dies when a candle CLOSES through it."""
    for i in range(from_bar, bar + 1):
        if direction == "bear" and close[i] > gap_hi:
            return False
        if direction == "bull" and close[i] < gap_lo:
            return False
    return True


def draw_on_liquidity(pools, price, direction, min_dist_pct=0.15):
    """TJR's target: the next real pool price is being drawn toward, not an
    arbitrary R multiple. Returns None when there is no genuine draw."""
    want = "low" if direction == "bear" else "high"
    cands = [p["price"] for p in pools if p["kind"] == want and
             (p["price"] < price if direction == "bear" else p["price"] > price)
             and abs(p["price"] - price) / price * 100 >= min_dist_pct]
    if not cands:
        return None
    return max(cands) if direction == "bear" else min(cands)


# How significant a pool is, independent of how near it happens to be.
# Picking the NEAREST pool made 65% of targets equal highs and lows, because
# those are dense and close, while the session levels he actually names were
# chosen only when they happened to be nearest. Weight is what he reads off the
# high timeframe; distance is not.
SIGNIFICANCE = {
    "prev_week_high": 3.0, "prev_week_low": 3.0,
    "news_data_high": 2.5, "news_data_low": 2.5,
    "prev_day_high": 2.5, "prev_day_low": 2.5,
    "asia_high": 2.0, "asia_low": 2.0,
    "london_high": 2.0, "london_low": 2.0,
    "ny_high": 2.0, "ny_low": 2.0,
}


def draw_by_bias(pools, price, direction, htf_dir=None, min_dist_pct=0.15,
                 aligned_reach=1.0, against_reach=0.35):
    """The draw the HIGHER TIMEFRAME says price is being pulled toward.

    His sequence is to read the draw on the high timeframe first, then drop to
    the five-minute to watch those orders being filled. So the target is chosen
    by significance and by direction, not by whichever pool happens to sit
    closest to the entry.

    Reach is what makes the bias matter. With the four-hour trend behind it a
    move can carry to a distant, more significant pool. Against that trend the
    same setup is likely only a higher-timeframe retrace, which is exactly the
    trade he refuses to hold out for: it gets the nearer pool instead.

    Returns a price, or None when there is no genuine draw.
    """
    want = "low" if direction == "bear" else "high"
    cands = []
    for p in pools:
        if p.get("kind") != want:
            continue
        px = float(p["price"])
        if (px >= price) if direction == "bear" else (px <= price):
            continue
        dist = abs(px - price) / price * 100.0
        if dist < min_dist_pct:
            continue
        cands.append((p, px, dist))
    if not cands:
        return None

    aligned = (htf_dir == direction)
    reach = aligned_reach if aligned else against_reach

    best, best_score = None, -1.0
    for p, px, dist in cands:
        src = p.get("source")
        if src in SIGNIFICANCE:
            sig = SIGNIFICANCE[src]
        else:
            # equal highs/lows: more touches is a heavier pool, which is his
            # reasoning for why they hold orders at all
            sig = 1.0 + 0.25 * max(0, int(p.get("touches", 2)) - 2)
        score = sig / (1.0 + dist / max(reach, 1e-9))
        if score > best_score:
            best, best_score = px, score
    return best


# --------------------------------------------------------------------------
# session and daily liquidity  (Phase 7 Asia range, TJR draws on liquidity)
# --------------------------------------------------------------------------
def session_levels(index, high, low,
                   asia=(18 * 60, 3 * 60),          # 18:00 -> 03:00 New York
                   london=(3 * 60, 8 * 60 + 30),    # 03:00 -> 08:30
                   ny=(9 * 60 + 30, 16 * 60)):      # 09:30 -> 16:00
    """Pre-compute the liquidity levels TJR names, in NEW YORK time.

    Returns, for every bar, the levels a live trader would ALREADY know:
    previous day and week high/low, and each session's range once that session
    has CLOSED. Nothing is visible before it has finished forming.

    The boundaries are his, to the minute. They are evaluated in
    America/New_York rather than as fixed UTC hours, which was wrong twice
    over: fixed hours ended Asia at 02:00 and London at 08:00, so both ranges
    lost their final stretch and every target built on them was slightly off,
    and because the market lives on Eastern time while UTC ignores US daylight
    saving, the whole grid silently shifted by an hour twice a year.
    """
    import numpy as _np
    import pandas as _pd

    idx = index if getattr(index, "tz", None) is not None else index.tz_localize("UTC")
    ny_idx = idx.tz_convert("America/New_York")
    mins = ny_idx.hour.values * 60 + ny_idx.minute.values
    day = ny_idx.normalize()

    df = _pd.DataFrame({"h": high, "l": low}, index=idx)

    # ---- previous day / week, on New York days ------------------------
    dh = df.groupby(day)["h"].max()
    dl = df.groupby(day)["l"].min()
    pdh = dh.shift(1).reindex(day).values
    pdl = dl.shift(1).reindex(day).values

    wk = day.tz_localize(None).to_period("W")
    wh = df.groupby(wk)["h"].max()
    wl = df.groupby(wk)["l"].min()
    pwh = wh.shift(1).reindex(wk).values
    pwl = wl.shift(1).reindex(wk).values

    def _range(lo, hi):
        """One session's high and low, revealed only once it has closed."""
        wraps = lo > hi
        inside = ((mins >= lo) | (mins < hi)) if wraps else ((mins >= lo) & (mins < hi))
        sess_day = day.values.copy()
        if wraps:
            # a session opening at 18:00 belongs to the NEXT trading day
            roll = mins >= lo
            sess_day[roll] = (day + _pd.Timedelta(days=1)).values[roll]
        sdf = _pd.DataFrame({"h": high, "l": low, "d": sess_day, "in": inside})
        hh = sdf[sdf["in"]].groupby("d")["h"].max()
        ll_ = sdf[sdf["in"]].groupby("d")["l"].min()
        out_h = _pd.Series(sess_day).map(hh).values
        out_l = _pd.Series(sess_day).map(ll_).values
        # Reveal AFTER the close only. For a same-day session, ~inside would
        # also be true BEFORE it opens, and the groupby spans the whole series,
        # so that would hand back a level built from bars that have not
        # printed yet.
        closed = (~inside) if wraps else (mins >= hi)
        return (_np.where(closed, out_h, _np.nan),
                _np.where(closed, out_l, _np.nan))

    asia_h, asia_l = _range(*asia)
    lon_h, lon_l = _range(*london)
    ny_h, ny_l = _range(*ny)

    return {"pdh": pdh, "pdl": pdl, "pwh": pwh, "pwl": pwl,
            "asia_h": asia_h, "asia_l": asia_l,
            "london_h": lon_h, "london_l": lon_l,
            "ny_h": ny_h, "ny_l": ny_l}


def levels_at(levels, bar):
    """The named pools known at `bar`, as [{kind, price, source, touches}]."""
    import math as _m
    out = []
    for key, kind, src in (("pdh", "high", "prev_day_high"),
                           ("pdl", "low", "prev_day_low"),
                           ("pwh", "high", "prev_week_high"),
                           ("pwl", "low", "prev_week_low"),
                           ("asia_h", "high", "asia_high"),
                           ("asia_l", "low", "asia_low"),
                           ("london_h", "high", "london_high"),
                           ("london_l", "low", "london_low"),
                           # he names New York session highs and lows as draws
                           # just as often as London's; computing them and then
                           # not exposing them here made them dead weight
                           ("ny_h", "high", "ny_high"),
                           ("ny_l", "low", "ny_low"),
                           # "data highs and data lows": the extremes of a
                           # high-impact news candle, which he marks and targets
                           ("news_h", "high", "news_data_high"),
                           ("news_l", "low", "news_data_low")):
        if key not in levels:
            continue
        v = levels[key][bar]
        if v is not None and not (isinstance(v, float) and _m.isnan(v)):
            out.append({"kind": kind, "price": float(v), "source": src,
                        "touches": 2})
    return out


def inverse_gaps(h, l, c, bar, lookback=60, min_size=0.0):
    """Fair value gaps that price has traded THROUGH, which then flip polarity.

    TJR leans on this more than almost anything else when he narrates a live
    trade: "we inverse this gap", "we also got a one minute inversion". The
    idea is simple. A gap is unfilled imbalance and acts as support. Once price
    closes decisively through it, the traders who bought there are trapped, and
    the same zone becomes resistance on the way back up.

    So an ordinary gap and an inverted gap point in OPPOSITE directions, and
    treating them the same is worse than ignoring both.

    Returns the inverted gaps known at `bar`, each as
    {lo, hi, dir, broken_at}, where `dir` is the direction it now supports.
    Nothing here looks past `bar`.
    """
    out = []
    lo_i = max(2, bar - lookback)
    for i in range(lo_i, bar):
        # a bullish gap: low[i] above high[i-2], leaving a hole
        if l[i] > h[i - 2]:
            g_lo, g_hi, side = h[i - 2], l[i], "bull"
        elif h[i] < l[i - 2]:
            g_lo, g_hi, side = h[i], l[i - 2], "bear"
        else:
            continue
        if g_hi - g_lo <= min_size:
            continue
        # has price CLOSED through it since? that is the inversion
        for j in range(i + 1, bar + 1):
            if side == "bull" and c[j] < g_lo:
                out.append({"lo": float(g_lo), "hi": float(g_hi),
                            "dir": "bear", "broken_at": j})
                break
            if side == "bear" and c[j] > g_hi:
                out.append({"lo": float(g_lo), "hi": float(g_hi),
                            "dir": "bull", "broken_at": j})
                break
    return out


def in_inverse_gap(inv, price, direction):
    """Is `price` inside an inverted gap that now supports `direction`?"""
    for g in inv:
        if g["dir"] == direction and g["lo"] <= price <= g["hi"]:
            return g
    return None


def recent_inversion(h, l, c, bar, direction, within=6, lookback=40):
    """Did a gap invert in the last few bars, pointing our way?

    The first version of this asked "is there any inverted gap in the last sixty
    bars", and the answer was yes on every single setup, which made it useless.
    Listening to how TJR actually uses it shows why:

        "If we inverse this gap, then..."   "we haven't inversed it yet"
        "ES inversed it and NASDAQ [hasn't]"

    He is watching ONE specific nearby gap and waiting for price to close
    through it. The inversion is an EVENT that triggers the entry, not a
    background condition that is always true somewhere on the chart.

    So this asks the narrow question: in the last `within` bars, did price close
    through a gap in a way that now supports `direction`?
    """
    for g in inverse_gaps(h, l, c, bar, lookback=lookback):
        if g["dir"] == direction and bar - g["broken_at"] < within:
            return g
    return None


def low_resistance_pools(swings, bar, price, direction, band_pct=2.5, min_run=3):
    """Stacked highs or lows sitting AHEAD of price: TJR's "low resistance
    liquidity".

    His words, and this is a targeting rule the engine did not have:

        "We use session highs and lows as our entry point and then low
         resistance draws and liquidity as our exit point."

    And how he counts it, pointing at the chart:

        "one low, two low, three low, four low, five low ... we end up dumping
         and taking out all of them"

    So it is not a strict unbroken sequence. It is simply several resting stops
    stacked ahead of price with little structure between them, which lets one
    move sweep the lot. The first version of this demanded an unbroken run and
    found almost nothing, which is a good reminder to implement what he does
    rather than what sounds rigorous.

    Returns the levels ahead of price, nearest first, all known at `bar`.
    """
    kind = "low" if direction == "bear" else "high"
    known = known_tail(swings, bar, 40)
    ahead = [x.price for x in known if x.kind == kind and
             (x.price < price if direction == "bear" else x.price > price) and
             abs(x.price - price) / price * 100 <= band_pct]
    if len(ahead) < min_run:
        return []
    return sorted(ahead, reverse=(direction == "bear"))


def stacked_target(swings, bar, price, direction, min_dist_pct=0.15,
                   band_pct=2.5, min_run=3):
    """The far end of a stack of resting stops, if there is one worth reaching.

    Returns None when no stack exists, so the caller falls back to the ordinary
    draw on liquidity rather than inventing a target.
    """
    levels = low_resistance_pools(swings, bar, price, direction,
                                  band_pct=band_pct, min_run=min_run)
    if not levels:
        return None
    far = levels[-1]
    if abs(far - price) / price * 100 < min_dist_pct:
        return None
    return far


def equilibrium(swings, bar, direction, n=30):
    """The 50% of the most recent leg. TJR's other continuation confluence.

    He splits his confluences into two kinds, and the engine only ever
    implemented one of them:

        confirmation   break of structure, inverse fair value gap
        continuation   fair value gap, EQUILIBRIUM

    So equilibrium is an alternative place to enter, not another filter. Price
    fills the 50%, respects it, and continues.

    He is emphatic about how it is drawn, having watched people get it wrong:

        "it's the easiest confluence on earth. the most recent low to the most
         recent high"

    Which is exactly what this does: the most recent confirmed swing low and
    the most recent confirmed swing high, and the midpoint between them. Not an
    arbitrary pair of pivots, and nothing that is not yet confirmed at `bar`.

    Returns (level, hi, lo) or None.
    """
    known = known_tail(swings, bar, n)
    highs = [x for x in known if x.kind == "high"]
    lows = [x for x in known if x.kind == "low"]
    if not highs or not lows:
        return None
    hi, lo = highs[-1].price, lows[-1].price
    if hi <= lo:
        return None
    return (hi + lo) / 2.0, hi, lo


def equilibrium_filled(h, l, bar, level, direction, within=12):
    """Has price actually traded into the 50% in the last few bars?

    "we filled equilibrium. We respected it. We moved up." Filling it is the
    event; without that it is just a line on the chart.
    """
    lo_i = max(0, bar - within)
    for i in range(lo_i, bar + 1):
        if l[i] <= level <= h[i]:
            return True
    return False
