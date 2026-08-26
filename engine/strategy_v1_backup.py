"""The course strategy, coded exactly as taught.

Sequence (Phase 5 -> 6 -> 7 -> 8, and TJR Parts 4/6/7/13):

    1. BUILD-UP        a liquidity pool exists (equal highs or equal lows)
    2. INDUCEMENT      price sweeps that pool and closes back
    3. CHoCH / BOS     the structure then breaks the other way
    4. IFC             find the last opposite candle before the impulse
    5. IMBALANCE       confirm the move away left a gap
    6. ENTRY           limit at the close of the gap
    7. STOP            at the extreme of the sweep
    8. TARGET          the next opposing liquidity pool, capped at max R

Nothing here peeks forward. Every decision at bar i uses bars <= i only.
"""
from dataclasses import dataclass, asdict
import numpy as np

from . import structure as S


@dataclass
class Config:
    # structure
    swing_left: int = 2
    swing_right: int = 2
    eq_tol_pct: float = 0.05      # how close two swings must be to be "equal"
    range_lookback: int = 120     # bars used to define the dealing range
    premium_min: float = 0.55     # a sell needs the swept high above this
    # sequence timing, in bars
    sweep_lookback: int = 30      # sweep must have happened this recently
    ifc_lookback: int = 12
    fvg_lookback: int = 12
    # risk
    max_rr: float = 3.0           # Chris: cap reward at 1:3
    min_rr: float = 1.5           # below this the trade is not worth taking
    min_stop_pct: float = 0.03    # Phase 8: too-tight a stop is a REASON TO SKIP
    max_stop_pct: float = 1.50
    # filters
    require_premium: bool = True  # only sell in premium, only buy in discount
    htf_bias: bool = True         # Phase 6: MAJOR inducement sets DIRECTION.
    htf_factor: int = 12          # how many base bars make one HTF bar
    min_touches: int = 2          # a pool with more touches is better fuel
    min_confluences: int = 0      # 0 = take everything, so the claim stays testable
    max_bars_in_trade: int = 240


@dataclass
class Setup:
    confluences: int = 0     # how many independent reasons agreed
    tags: str = ""           # which ones, so the claim can be audited
    bar: int = 0
    side: str = ""       # "long" | "short"
    entry: float = 0.0
    stop: float = 0.0
    target: float = 0.0
    rr: float = 0.0
    swept_price: float = 0.0
    reason: str = ""

    def as_dict(self):
        return asdict(self)


def find_setups(df, cfg=None, session_filter=None):
    """Walk the data bar by bar and return every setup the rules produce.

    `session_filter` is a callable(timestamp) -> bool used for the futures
    session windows. Crypto runs without one by default.
    """
    cfg = cfg or Config()
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    idx = df.index

    swings = S.find_swings(h, l, cfg.swing_left, cfg.swing_right)

    # ---- higher timeframe bias -------------------------------------------
    # Phase 6: major = direction, medium = place, minor = time. Build the HTF
    # swing structure once, then only trade WITH it. Index maps back to the
    # base timeframe so there is still no lookahead.
    htf_state = None
    if cfg.htf_bias:
        f = cfg.htf_factor
        n = len(df) // f * f
        hh = h[:n].reshape(-1, f).max(1)
        ll = l[:n].reshape(-1, f).min(1)
        hsw = S.find_swings(hh, ll, 2, 2)
        htf_state = []
        for b in range(len(hh)):
            st, _, _ = S.structure_state(hsw, b)
            htf_state.append(st)

    def htf_at(bar):
        if htf_state is None:
            return None
        j = bar // cfg.htf_factor
        return htf_state[j] if 0 <= j < len(htf_state) else None

    setups = []
    start = max(cfg.sweep_lookback, 60)

    # remember recent sweeps so a later BOS can be paired with one
    recent = []          # list of (bar, side, level_price, extreme_price)

    for i in range(start, len(df) - 1):
        if session_filter is not None and not session_filter(idx[i]):
            continue

        pools = S.equal_levels(swings, i, cfg.eq_tol_pct, cfg.min_touches)

        # ---- step 1+2: did this bar sweep a pool? -------------------------
        for p in pools:
            if S.sweep(h, l, c, i, p["price"], p["kind"]):
                extreme = h[i] if p["kind"] == "high" else l[i]
                recent.append((i, p["kind"], p["price"], extreme))
        recent = [r for r in recent if i - r[0] <= cfg.sweep_lookback]
        if not recent:
            continue

        # ---- step 3: has structure now broken against the sweep? ---------
        state, sh, sl = S.structure_state(swings, i)

        for (sbar, skind, slevel, sextreme) in list(recent):
            if sbar == i:
                continue                      # need at least one bar after
            direction = "bear" if skind == "high" else "bull"
            bos = S.break_of_structure(c, swings, i, direction)
            if bos is None:
                continue

            # only trade in the direction the bigger picture is already leaning
            if cfg.htf_bias:
                bias = htf_at(i)
                if bias == "bull" and direction == "bear":
                    continue
                if bias == "bear" and direction == "bull":
                    continue

            # ---- premium / discount filter (Phase 3) ---------------------
            # Measured at the SWEPT LEVEL, not at the breakdown bar. By the time
            # structure breaks, price has already travelled, so testing the
            # break bar rejects almost everything and rejects it wrongly.
            if cfg.require_premium:
                rhi, rlo = S.dealing_range(h, l, sbar, cfg.range_lookback)
                pd_pos = S.premium_discount(slevel, rhi, rlo)
                if direction == "bear" and pd_pos < cfg.premium_min:
                    continue
                if direction == "bull" and pd_pos > (1.0 - cfg.premium_min):
                    continue

            # ---- step 4+5: IFC and the imbalance -------------------------
            ifc = S.find_ifc(o, c, i, direction, cfg.ifc_lookback)
            if ifc is None:
                continue
            gap = S.find_imbalance(h, l, i, direction, cfg.fvg_lookback)
            if gap is None:
                continue
            gap_lo, gap_hi, _ = gap

            # ---- step 6+7: entry and stop --------------------------------
            # The gap must sit BELOW the swept high (or above the swept low),
            # otherwise the stop ends up on the wrong side of the entry. When
            # the gap is above the sweep it belongs to an older move, so skip.
            if direction == "bear":
                entry = gap_hi                 # limit at the top of the gap
                stop = max(sextreme, h[i])     # beyond the sweep extreme
                if stop <= entry:
                    continue
            else:
                entry = gap_lo
                stop = min(sextreme, l[i])
                if stop >= entry:
                    continue

            risk = abs(entry - stop)
            stop_pct = risk / entry * 100
            # Phase 8: a 1-2 pip stop means the move had no force. Skip it.
            if stop_pct < cfg.min_stop_pct or stop_pct > cfg.max_stop_pct:
                continue

            # ---- step 8: target the next opposing pool -------------------
            want = "low" if direction == "bear" else "high"
            cands = [p["price"] for p in pools if p["kind"] == want and
                     (p["price"] < entry if direction == "bear" else p["price"] > entry)]
            if cands:
                tgt = max(cands) if direction == "bear" else min(cands)
            else:
                tgt = entry - risk * cfg.max_rr if direction == "bear" else entry + risk * cfg.max_rr

            rr = abs(tgt - entry) / risk
            if rr > cfg.max_rr:                 # cap at Chris's 1:3
                tgt = entry - risk * cfg.max_rr if direction == "bear" else entry + risk * cfg.max_rr
                rr = cfg.max_rr
            if rr < cfg.min_rr:
                continue

            # ---- confluence scoring --------------------------------------
            # The courses claim stacking reasons raises probability. Rather than
            # assume that, score each setup and let the results say whether the
            # high-confluence ones actually do better.
            tags = []
            pool_touch = next((p["touches"] for p in pools
                               if abs(p["price"] - slevel) < 1e-9), 2)
            if pool_touch >= 3:
                tags.append("pool3+")
            if cfg.htf_bias and htf_at(i) in ("bull", "bear"):
                tags.append("htf_aligned")
            # engulfing candle at the break (Phase 5: intention, with aggression)
            if abs(c[i] - o[i]) > abs(c[i-1] - o[i-1]):
                tags.append("engulf")
            # follow-through: the break bar closed near its extreme
            rng = max(h[i] - l[i], 1e-9)
            if direction == "bear" and (c[i] - l[i]) / rng < 0.35:
                tags.append("follow_through")
            if direction == "bull" and (h[i] - c[i]) / rng < 0.35:
                tags.append("follow_through")
            # a meaty imbalance, not a hairline gap
            if abs(gap_hi - gap_lo) / entry * 100 > cfg.min_stop_pct * 0.5:
                tags.append("real_gap")
            # deep in premium / discount
            rhi2, rlo2 = S.dealing_range(h, l, sbar, cfg.range_lookback)
            pdp = S.premium_discount(slevel, rhi2, rlo2)
            if (direction == "bear" and pdp > 0.75) or (direction == "bull" and pdp < 0.25):
                tags.append("deep_pd")

            if len(tags) < cfg.min_confluences:
                continue

            setups.append(Setup(
                confluences=len(tags),
                tags="|".join(tags),
                bar=i,
                side="short" if direction == "bear" else "long",
                entry=float(entry), stop=float(stop), target=float(tgt),
                rr=float(rr), swept_price=float(slevel),
                reason=f"swept {skind} @{slevel:.2f} then {direction} BOS",
            ))
            recent.remove((sbar, skind, slevel, sextreme))
            break

    return setups
