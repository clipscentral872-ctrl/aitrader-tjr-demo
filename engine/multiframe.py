"""Three timeframes, the way the guide actually describes the method.

The engine has always run on a single timeframe. The guide does not:

    "Read the 4-hour structure. Uptrend, downtrend or range."
    "Drop to the 5-minute chart and watch for step 2: a candle CLOSING
     beyond the most recent swing point against the sweep."
    "Drop to the 1-minute chart. Wait for step 3: price pulling back into
     the marked gap."

Three charts, three jobs. Bias on the 4-hour, confirmation on the 5-minute,
entry on the 1-minute. Running everything on the 5-minute collapses the last
two into one and loses the reason the third exists.

That reason is the stop. A fair value gap on a 5-minute chart spans five
minutes of range; the same structure on a 1-minute chart is a fifth of the
size. Same idea, same target, much smaller risk, so the reward-to-risk on an
identical trade is several times better. The guide names this directly:

    "The advantage is a much tighter stop-loss, which means a much better
     risk-to-reward ratio. That is the entire point."

Measured on a live example: the engine on 5-minute found no setup at all where
a 1-minute read found two, and the trade in question ran 95 points off a
62-point stop.

No-lookahead is stricter here than usual, because two clocks make it easy to
cheat by accident. The confirmation bar must have CLOSED on the 5-minute before
any 1-minute bar is consulted, and only 1-minute bars stamped at or after that
close are eligible.
"""
from dataclasses import replace
import numpy as np
import pandas as pd

from engine import structure as S
from engine.strategy import find_setups, Setup


def lower_confirms(h, l, c, int_sw, i, direction, within=4, lookback=25):
    """His step 4: the lower timeframe must CONFIRM before entering.

    From the updated strategy video: after price pushes into the continuation
    zone on the five-minute, he scales to the one-minute and looks for "a break
    of structure to the downside or an inverse fair value gap to show
    confirmation that we are actually going to continue".

    The first version of this module entered as soon as price REACHED the zone.
    That is a different trade: it buys the level and hopes, where he waits for
    the lower timeframe to turn first. Reaching a zone is an event that happens
    to every zone; turning inside it is not.
    """
    if S.break_of_structure(c, int_sw, i, direction) is not None:
        return "1m break of structure"
    inv = S.recent_inversion(h, l, c, i, direction, within=within,
                             lookback=lookback)
    if inv is not None:
        return "1m gap inversion"
    return None


def entry_on_lower(df_lo, setup, cfg, confirm_time, max_wait_min=45,
                   require_confirm=True, stop_mode="ltf"):
    """Find the entry on the lower timeframe, after the confirmation closed.

    Returns a new Setup with the tighter entry and stop, or None.
    """
    idx = df_lo.index
    # only bars at or after the confirmation bar's CLOSE are visible
    start = idx.searchsorted(confirm_time, side="left")
    if start >= len(idx) - 3:
        return None
    end = min(len(idx), start + max_wait_min)

    h = df_lo["high"].to_numpy(float)
    l = df_lo["low"].to_numpy(float)
    c = df_lo["close"].to_numpy(float)
    o = df_lo["open"].to_numpy(float)
    direction = "bear" if setup.side == "short" else "bull"

    int_sw = S.find_swings(h, l, cfg.swing_left, cfg.swing_right)

    for i in range(start + 2, end):
        gap = S.find_imbalance(h, l, i, direction, cfg.fvg_lookback)
        zone = None
        if gap is not None:
            glo, ghi, gm = gap
            if not cfg.require_valid_gap or S.gap_still_valid(
                    c, glo, ghi, gm, i, direction):
                zone = (glo, ghi)
        if zone is None and cfg.entry_mode == "tjr":
            eq = S.equilibrium(int_sw, i, direction)
            if eq is not None:
                lvl, ehi, elo = eq
                if not cfg.require_eq_filled or S.equilibrium_filled(
                        h, l, i, lvl, direction):
                    pad = (ehi - elo) * cfg.eq_zone_frac
                    zone = (lvl - pad, lvl + pad)
        if zone is None:
            continue

        # his step 4: the one-minute has to turn, not merely arrive
        if require_confirm:
            why = lower_confirms(h, l, c, int_sw, i, direction)
            if why is None:
                continue
        else:
            why = "zone touched"

        glo, ghi = zone
        if direction == "bear":
            entry = ghi
            tight = max(ghi + (ghi - glo) * 0.15,
                        float(h[max(0, i - 3):i + 1].max()))
            stop = float(setup.stop) if stop_mode == "structural" else tight
            if stop <= entry:
                stop = tight
            if stop <= entry:
                continue
        else:
            entry = glo
            tight = min(glo - (ghi - glo) * 0.15,
                        float(l[max(0, i - 3):i + 1].min()))
            stop = float(setup.stop) if stop_mode == "structural" else tight
            if stop >= entry:
                stop = tight
            if stop >= entry:
                continue

        risk = abs(entry - stop)
        if risk <= 0:
            continue
        stop_pct = risk / entry * 100
        # A four-bar one-minute range is noise, not invalidation. Anchoring the
        # stop to the five-minute level that actually disproves the setup keeps
        # the better entry without being wicked out by a two-tick spike, which
        # is what halved the win rate to 37.8% in his window.
        floor = cfg.min_stop_pct * (1.0 if stop_mode == "structural" else 0.35)
        if stop_pct < floor or stop_pct > cfg.max_stop_pct:
            continue

        target = setup.target          # the draw on liquidity does not change
        rr = abs(target - entry) / risk
        if rr < cfg.min_rr:
            continue
        if rr > cfg.max_rr:
            target = (entry - risk * cfg.max_rr if direction == "bear"
                      else entry + risk * cfg.max_rr)
            rr = cfg.max_rr

        return replace(setup, bar=i, entry=float(entry), stop=float(stop),
                       target=float(target), rr=float(rr),
                       reason=setup.reason + f" | {why}")
    return None


def find_setups_mtf(df_lo, df_hi, cfg, session_filter=None, max_wait_min=45,
                    require_confirm=True, stop_mode="ltf", smt_df=None):
    """Confirmation on the higher timeframe, entry on the lower one.

    `df_hi` is the 5-minute series, `df_lo` the 1-minute. Returns setups
    indexed against `df_lo`, so the backtester runs on 1-minute bars.
    """
    # the pair is compared on the CONFIRMATION timeframe, which is where
    # the swings he reads the divergence off actually live
    hi_setups = find_setups(df_hi, cfg, session_filter=session_filter,
                            smt_df=smt_df)
    if not hi_setups:
        return []

    step = df_hi.index[1] - df_hi.index[0] if len(df_hi) > 1 else pd.Timedelta("5min")
    out = []
    for s in hi_setups:
        # the confirmation bar closes at the END of its interval
        confirm_close = df_hi.index[s.bar] + step
        e = entry_on_lower(df_lo, s, cfg, confirm_close, max_wait_min,
                           require_confirm=require_confirm,
                           stop_mode=stop_mode)
        if e is not None:
            out.append(e)
    out.sort(key=lambda x: x.bar)
    return out


def compare(df_lo, df_hi, cfg, session_filter=None):
    """What the extra timeframe buys, in stop size and reward."""
    single = find_setups(df_hi, cfg, session_filter=session_filter)
    multi = find_setups_mtf(df_lo, df_hi, cfg, session_filter=session_filter)
    def stats(ss, label):
        if not ss:
            print(f"  {label:<28} no setups")
            return
        stops = np.array([abs(x.entry - x.stop) / x.entry * 100 for x in ss])
        rr = np.array([x.rr for x in ss])
        print(f"  {label:<28} {len(ss):>5} setups   stop {stops.mean():.4f}%   "
              f"reward {rr.mean():.2f}R")
    stats(single, "5-minute entry (old)")
    stats(multi, "1-minute entry (his way)")
    return single, multi
