"""The two courses' strategy, coded as they actually teach it.

TJR's sequence (6-hour video, Parts 3/4/6/7/13):
    identify the HIGHER TIMEFRAME trend
    find the DRAWS ON LIQUIDITY  (previous day high/low, session highs/lows)
    wait for price into a fair value gap and see it RESPECTED
    a break of structure needs a candle CLOSURE, not a wick
    target the draw

The phase course adds (Phase 3/5/6/8):
    EFFICIENCY OF THE PULLBACK - the retrace must actually reach the external
      zone. He calls this the strongest invalidation there is: no matter how
      many boxes are ticked, if this one fails there is no trade.
    INTERNAL vs EXTERNAL structure - internal runs counter-trend during a
      proper complex pullback, and an internal break is often a TRAP
    the refined IFC - order block + imbalance + engulf + follow-through
    confluence stacking - which this file SCORES rather than assumes

Nothing peeks forward. Every decision at bar i uses bars <= i only.
"""
from dataclasses import dataclass, asdict
import numpy as np

from . import structure as S


@dataclass
class Config:
    # --- structure scales -------------------------------------------------
    swing_left: int = 2           # internal structure
    swing_right: int = 2
    ext_left: int = 6             # external structure (the impulse legs)
    ext_right: int = 6
    eq_tol_pct: float = 0.05
    min_touches: int = 2
    range_lookback: int = 120
    # --- higher timeframe -------------------------------------------------
    htf_bias: bool = True
    htf_factor: int = 12
    # --- the course's non-negotiables ------------------------------------
    # The efficiency filter was a no-op until 2026-08-23: it measured a window
    # that included the sweep spike, so the ratio was always at or above 1.0.
    # Now that it measures the actual retrace, a 0.80 requirement removes about
    # 90% of setups (697 down to 66 on EURUSD). That is a large behavioural
    # change nobody has validated, and no threshold survived a train/test split
    # on either market, so the default is OFF rather than silently on at a
    # setting that used to mean nothing.
    require_efficiency: bool = False
    min_efficiency: float = 0.50  # 0.50 is equilibrium, the best of a bad set
    require_valid_gap: bool = True
    require_real_draw: bool = True
    premium_min: float = 0.55
    require_premium: bool = True
    # --- timing -----------------------------------------------------------
    sweep_lookback: int = 30
    ifc_lookback: int = 12
    fvg_lookback: int = 12
    # --- risk -------------------------------------------------------------
    max_rr: float = 3.0
    min_rr: float = 1.5
    min_stop_pct: float = 0.20
    max_stop_pct: float = 1.50
    # --- confluence gate --------------------------------------------------
    min_confluences: int = 0      # 0 keeps the claim testable
    # Named confluences that MUST be present. Only two survived being tested
    # on a second market: htf_trend and complex_pullback. Requiring the others
    # would be fitting to whichever market they were measured on.
    require_tags: tuple = ()
    # Target the far end of a stack of resting stops rather than the nearest
    # pool. This is TJR's pairing: sweep a session level to get in, target the
    # low-resistance liquidity to get out.
    # How the entry is located.
    #   "bos_gap"  wait for the break of structure, enter at its imbalance
    #   "inverse"  enter at an inverted gap, which happens EARLIER
    #   "either"   take whichever presents first
    # TJR on why this matters: entering at the inverse gap rather than waiting
    # for the break of structure made his stop "literally two times" smaller
    # and turned a 1:0.5 into a 1:1.3. Risk is the denominator of every R, so
    # halving it is worth more than any filter.
    # "bos_gap"      break of structure, enter at the imbalance
    # "inverse"      enter at an inverted gap, which happens earlier
    # "equilibrium"  enter at the 50% of the leg
    # "either"       break of structure OR inversion
    # "tjr"          his step 3 as written: pull back into a fair value gap
    #                OR into equilibrium, whichever presents. The guide gives
    #                them as alternatives, and the engine only ever accepted
    #                the gap, so roughly half his valid entries were invisible.
    entry_mode: str = "bos_gap"
    inv_within: int = 6          # the inversion must be recent to count
    inv_lookback: int = 40
    require_eq_filled: bool = True   # price must actually reach the 50%
    eq_zone_frac: float = 0.05       # how thick to treat the 50% level
    use_stacked_target: bool = False
    stack_min_run: int = 3
    stack_band_pct: float = 2.5
    # --- which liquidity pools count as a build-up ------------------------
    use_equal_levels: bool = True   # equal highs / lows
    # SMT divergence: his signature confluence, and the only one that brings
    # information from OUTSIDE the chart being traded. It was implemented in
    # engine/smt.py and then imported by nothing, so it has never once fired.
    use_smt: bool = False           # count it as a confluence
    require_smt: bool = False       # refuse any setup without it
    # How big a swing counts as a divergence. At 2/2 on five-minute bars it
    # fired on 45% of setups, which is precisely the "shows up all the time and
    # is pretty much useless" case he warns about. His divergences sit at HIGH
    # timeframe swings at significant draws, so these need to be much larger.
    smt_left: int = 2
    smt_right: int = 2
    # How the target is chosen. "nearest" takes whichever pool is closest,
    # which made 65% of targets equal highs/lows because those are dense and
    # near. "bias" ranks by significance and by the four-hour trend, which is
    # the order he does it in: read the draw on the high timeframe, then drop
    # to the five-minute to watch the orders fill.
    # Which gap to enter from. "recent" takes whichever formed last, which is
    # what find_imbalance returns; "all" considers every unfilled gap and picks
    # the one price has actually traded back into. He reads them all, not just
    # the newest, and reuses a level as often as price returns to it.
    # What counts as MANIPULATION. Any confirmed swing was enough, and 53.5% of
    # setups swept nothing a trader would have marked: some minor five-minute
    # high, not a session level. He waits for price to run a LEVEL he drew on
    # the chart, then reverse, and refuses a trade off a random high because it
    # may only be a higher-timeframe retrace. Named pools carry a "source";
    # equal highs and lows do not, which makes the distinction exact.
    require_named_sweep: bool = False
    # Where the stop goes. "sweep" puts it at the level just swept, which is
    # what this engine has always done. "second" is his rule: beyond the SECOND
    # low on a long, the second high on a short, so the stop sits outside the
    # noise the sweep itself created rather than inside it.
    stop_rule: str = "sweep"        # sweep | second
    # HIS VETO. "I would highly recommend you guys don't take trades when the
    # two indexes are not aligned... if both the indexes are telling us two
    # different things, then the market is probably indecisive." So a setup on
    # NQ is refused unless ES has ALSO broken structure the same way, and the
    # reverse. This is a refusal rule, not a confluence: it is about the trades
    # it stops us taking. Distinct from SMT, which compares swings at a sweep.
    require_index_align: bool = False
    align_window: int = 6           # bars either side to find the pair's break
    gap_mode: str = "recent"        # recent | all
    min_gap_pts: float = 0.0        # ignore gaps thinner than this
    draw_mode: str = "nearest"      # nearest | bias
    aligned_reach: float = 1.0      # with the 4h trend, a further pool is live
    against_reach: float = 0.15     # against it, this is likely just a retrace
    smt_window: int = 6             # bars either side of the sweep it may sit
    use_session_levels: bool = True # prev day/week high-low, Asia range
    pool_tol_pct: float = 0.03      # how close a sweep must be to the level


@dataclass
class Setup:
    bar: int
    side: str
    entry: float
    stop: float
    target: float
    rr: float
    swept_price: float
    confluences: int
    tags: str
    efficiency: float
    reason: str

    def as_dict(self):
        return asdict(self)


def find_setups(df, cfg=None, session_filter=None, smt_df=None):
    cfg = cfg or Config()
    o = df["open"].to_numpy(float)
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    c = df["close"].to_numpy(float)
    idx = df.index
    n = len(df)

    int_sw = S.find_swings(h, l, cfg.swing_left, cfg.swing_right)
    ext_sw = S.external_swings(h, l, cfg.ext_left, cfg.ext_right)

    # The named levels both courses actually trade: previous day and week
    # extremes, and the Asia range. Leaving these out was why the first build
    # found only ~30 setups a year.
    named = S.session_levels(idx, h, l) if cfg.use_session_levels else None

    # SMT divergence against the correlated index (NQ vs ES). align() drops any
    # timestamp the two do not share, so positions in the aligned frame do NOT
    # match positions here. Mapping through timestamps keeps them honest; using
    # the raw index would silently compare different moments.
    # the pair's break-of-structure bars, for his index-alignment veto
    pair_bos, pair_at = None, None
    pair_why = "no correlated index was supplied"
    if smt_df is not None and cfg.require_index_align:
        try:
            from engine import smt as SMT
            a_al, b_al = SMT.align(df, smt_df)
            if len(a_al) <= 50:
                # a pair WAS given, it just does not overlap this slice. Saying
                # "not supplied" here sent me hunting a wiring bug that did not
                # exist: the S&P feed starts 2023 and the early folds do not.
                pair_why = (f"the correlated index overlaps this slice on only "
                            f"{len(a_al)} bars ({df.index[0]:%Y-%m-%d} to "
                            f"{df.index[-1]:%Y-%m-%d}); trim the run to the "
                            f"period both feeds cover")
            if len(a_al) > 50:
                pb_h = b_al["high"].to_numpy(float)
                pb_l = b_al["low"].to_numpy(float)
                pb_c = b_al["close"].to_numpy(float)
                pb_sw = S.find_swings(pb_h, pb_l, cfg.swing_left, cfg.swing_right)
                pair_bos = {"bull": set(), "bear": set()}
                for k in range(len(a_al)):
                    for dirn in ("bull", "bear"):
                        if S.break_of_structure(pb_c, pb_sw, k, dirn) is not None:
                            pair_bos[dirn].add(k)
                pair_at = {t: k for k, t in enumerate(a_al.index)}
        except Exception:
            pair_bos, pair_at = None, None

    smt_divs, smt_at = None, None
    if smt_df is not None and (cfg.use_smt or cfg.require_smt):
        try:
            from engine import smt as SMT
            a_al, b_al = SMT.align(df, smt_df)
            if len(a_al) > 50:
                smt_divs = SMT.detect(a_al, b_al, "traded", "pair",
                                      left=cfg.smt_left, right=cfg.smt_right)
                smt_at = {t: k for k, t in enumerate(a_al.index)}
                smt_mod = SMT
        except Exception:
            smt_divs, smt_at = None, None

    # ---- higher timeframe bias (Phase 6: major = DIRECTION) --------------
    htf_state = None
    if cfg.htf_bias:
        f = cfg.htf_factor
        m = n // f * f
        if m >= f * 10:
            hh = h[:m].reshape(-1, f).max(1)
            ll = l[:m].reshape(-1, f).min(1)
            hsw = S.find_swings(hh, ll, 2, 2)
            htf_state = [S.structure_state(hsw, b)[0] for b in range(len(hh))]

    def htf_at(bar):
        """Higher-timeframe bias as of the last COMPLETED higher-timeframe bar.

        Reading the bar we are currently inside would consult a candle that has
        not closed yet, and whose high and low include five-minute bars still in
        the future. That is a small leak, and small leaks are how the Nasdaq
        result happened. One bar back costs a little responsiveness and removes
        the doubt entirely.
        """
        if not htf_state:
            return None
        j = bar // cfg.htf_factor - 1
        return htf_state[j] if 0 <= j < len(htf_state) else None

    setups = []
    recent = []       # live sweeps: (bar, kind, level, extreme)
    start = max(cfg.sweep_lookback, cfg.ext_left * 4, 60)

    # Liquidity pools only change when a NEW swing confirms, so recomputing them
    # on every single bar is wasted work. Cache against the swing count.
    _pool_cache = {"n": -1, "pools": []}
    conf_at = [sw.confirmed_at for sw in int_sw]

    def pools_at(bar):
        lo, hi = 0, len(conf_at)
        while lo < hi:
            mid = (lo + hi) // 2
            if conf_at[mid] <= bar:
                lo = mid + 1
            else:
                hi = mid
        if lo != _pool_cache["n"]:
            _pool_cache["n"] = lo
            _pool_cache["pools"] = (S.equal_levels(int_sw, bar, cfg.eq_tol_pct,
                                                   cfg.min_touches)
                                    if cfg.use_equal_levels else [])
        pools = list(_pool_cache["pools"])
        if named is not None:
            pools += S.levels_at(named, bar)
        return pools

    for i in range(start, n - 1):
        if session_filter is not None and not session_filter(idx[i]):
            continue

        pools = pools_at(i)

        # ---- 1+2: build-up swept (the inducement) ------------------------
        for p in pools:
            if cfg.require_named_sweep and "source" not in p:
                continue
            if S.sweep(h, l, c, i, p["price"], p["kind"]):
                recent.append((i, p["kind"], p["price"],
                               h[i] if p["kind"] == "high" else l[i]))
        recent = [r for r in recent if i - r[0] <= cfg.sweep_lookback]
        if not recent:
            continue

        for (sbar, skind, slevel, sextreme) in list(recent):
            if sbar == i:
                continue
            direction = "bear" if skind == "high" else "bull"

            # ---- 3: confirmation that order flow has turned --------------
            # Either a break of structure, or a gap inverting. He uses the
            # second "almost every single day, almost more than break of
            # structure, because more often than not it happens before" it.
            has_bos = S.break_of_structure(c, int_sw, i, direction) is not None
            inv = None
            if cfg.entry_mode in ("inverse", "either"):
                inv = S.recent_inversion(h, l, c, i, direction,
                                         within=cfg.inv_within,
                                         lookback=cfg.inv_lookback)
            if cfg.entry_mode in ("equilibrium", "tjr") and not has_bos:
                continue
            if cfg.entry_mode == "bos_gap" and not has_bos:
                continue
            if cfg.entry_mode == "inverse" and inv is None:
                continue
            if cfg.entry_mode == "either" and not has_bos and inv is None:
                continue

            # ---- NON-NEGOTIABLE: higher timeframe agrees ----------------
            if cfg.htf_bias:
                bias = htf_at(i)
                if bias == "bull" and direction == "bear":
                    continue
                if bias == "bear" and direction == "bull":
                    continue

            # ---- NON-NEGOTIABLE: efficiency of the pullback -------------
            zone = S.impulse_zone(ext_sw, i, direction)
            eff = S.pullback_efficiency(h, l, i, zone, direction,
                                        max(0, sbar - cfg.sweep_lookback),
                                        sweep_bar=sbar, sweep_extreme=sextreme)
            if cfg.require_efficiency and eff < cfg.min_efficiency:
                continue

            # ---- premium / discount at the SWEPT level ------------------
            rhi, rlo = S.dealing_range(h, l, sbar, cfg.range_lookback)
            pdp = S.premium_discount(slevel, rhi, rlo)
            if cfg.require_premium:
                if direction == "bear" and pdp < cfg.premium_min:
                    continue
                if direction == "bull" and pdp > (1.0 - cfg.premium_min):
                    continue

            # ---- 4+5: the IFC and its imbalance -------------------------
            if cfg.entry_mode == "tjr":
                # a gap if there is one, otherwise equilibrium. Not both
                # required, which is how it had effectively been treated.
                zone = None
                if cfg.gap_mode == "all":
                    g = S.pick_gap(
                        S.all_imbalances(h, l, i, direction, cfg.fvg_lookback),
                        h[i], l[i], cfg.min_gap_pts)
                else:
                    g = S.find_imbalance(h, l, i, direction, cfg.fvg_lookback)
                if g is not None:
                    glo, ghi, gm = g
                    if not cfg.require_valid_gap or S.gap_still_valid(
                            c, glo, ghi, gm, i, direction):
                        zone = (glo, ghi, gm)
                if zone is None:
                    eq = S.equilibrium(int_sw, i, direction)
                    if eq is not None:
                        lvl, ehi, elo = eq
                        if not cfg.require_eq_filled or S.equilibrium_filled(
                                h, l, i, lvl, direction):
                            pad = (ehi - elo) * cfg.eq_zone_frac
                            zone = (lvl - pad, lvl + pad, lvl)
                if zone is None:
                    continue
                gap_lo, gap_hi, gmid = zone
            elif cfg.entry_mode == "equilibrium":
                # the other continuation confluence: enter at the 50% of the
                # most recent leg rather than at an imbalance
                eq = S.equilibrium(int_sw, i, direction)
                if eq is None:
                    continue
                eq_level, eq_hi, eq_lo = eq
                if cfg.require_eq_filled and not S.equilibrium_filled(
                        h, l, i, eq_level, direction):
                    continue
                # a thin zone around the 50%, so it behaves like a gap
                pad = (eq_hi - eq_lo) * cfg.eq_zone_frac
                gap_lo, gap_hi = eq_level - pad, eq_level + pad
                gmid = eq_level
            elif inv is not None and (cfg.entry_mode == "inverse"
                                    or (cfg.entry_mode == "either" and not has_bos)):
                # the inverted gap IS the zone we enter from
                gap_lo, gap_hi = inv["lo"], inv["hi"]
                gmid = (gap_lo + gap_hi) / 2
            else:
                ifc = S.find_ifc(o, c, i, direction, cfg.ifc_lookback)
                if ifc is None:
                    continue
                if cfg.gap_mode == "all":
                    gap = S.pick_gap(
                        S.all_imbalances(h, l, i, direction, cfg.fvg_lookback),
                        h[i], l[i], cfg.min_gap_pts)
                else:
                    gap = S.find_imbalance(h, l, i, direction, cfg.fvg_lookback)
                if gap is None:
                    continue
                gap_lo, gap_hi, gmid = gap

            # TJR: a gap dies when a candle CLOSES through it. An INVERTED gap
            # is one that already died in the other direction, so this check is
            # about ordinary gaps only.
            using_inv = cfg.entry_mode in ("equilibrium", "tjr") or (
                inv is not None and (
                    cfg.entry_mode == "inverse"
                    or (cfg.entry_mode == "either" and not has_bos)))
            if not using_inv and cfg.require_valid_gap and not S.gap_still_valid(
                    c, gap_lo, gap_hi, gmid, i, direction):
                continue

            # ---- 6+7: entry and stop -----------------------------------
            if direction == "bear":
                entry, stop = gap_hi, max(sextreme, h[i])
                if cfg.stop_rule == "second":
                    sw2 = S.nth_swing(int_sw, i, "high", 2)
                    # only ever widens: a second swing INSIDE the sweep would
                    # tighten the stop, which is the opposite of his intent
                    if sw2 is not None and sw2.price > stop:
                        stop = float(sw2.price)
                if stop <= entry:
                    continue
            else:
                entry, stop = gap_lo, min(sextreme, l[i])
                if cfg.stop_rule == "second":
                    sw2 = S.nth_swing(int_sw, i, "low", 2)
                    if sw2 is not None and sw2.price < stop:
                        stop = float(sw2.price)
                if stop >= entry:
                    continue

            risk = abs(entry - stop)
            stop_pct = risk / entry * 100
            if stop_pct < cfg.min_stop_pct or stop_pct > cfg.max_stop_pct:
                continue

            # ---- 8: target a REAL draw on liquidity --------------------
            draw = None
            draw_src = "none"
            if cfg.use_stacked_target:
                # the far side of the stack, when there is a stack
                draw = S.stacked_target(int_sw, i, entry, direction,
                                        band_pct=cfg.stack_band_pct,
                                        min_run=cfg.stack_min_run)
                if draw is not None:
                    draw_src = "swing_stack"
            if draw is None:
                if cfg.draw_mode == "bias":
                    draw = S.draw_by_bias(pools, entry, direction, htf_at(i),
                                          aligned_reach=cfg.aligned_reach,
                                          against_reach=cfg.against_reach)
                else:
                    draw = S.draw_on_liquidity(pools, entry, direction)
                if draw is not None:
                    # WHICH high or low we are drawing to. The setup recorded
                    # the sweep but never the target, so there was no way to
                    # check we were aiming at the levels he names rather than
                    # at some arbitrary swing.
                    # equal highs/lows carry no "source" key, and they are a
                    # named pool type of his in their own right, so label them
                    # rather than letting them fall through as anonymous
                    draw_src = next(
                        (q.get("source") or ("equal_" + q["kind"] + "s")
                         for q in pools if abs(q["price"] - draw) < 1e-9),
                        "swing")
            if draw is None:
                if cfg.require_real_draw:
                    continue
                draw = (entry - risk * cfg.max_rr if direction == "bear"
                        else entry + risk * cfg.max_rr)
                draw_src = "no_pool"
            rr = abs(draw - entry) / risk
            if rr > cfg.max_rr:
                # his pool sits further than the ceiling allows, so we exit
                # early and this is NOT the target he would have used
                draw = (entry - risk * cfg.max_rr if direction == "bear"
                        else entry + risk * cfg.max_rr)
                rr = cfg.max_rr
                draw_src += "+capped"
            if rr < cfg.min_rr:
                continue

            # ---- confluence scoring, using what the courses NAME --------
            tags = []
            touches = next((p["touches"] for p in pools
                            if abs(p["price"] - slevel) < 1e-9), 2)
            if touches >= 3:
                tags.append("pool3+")                    # stronger build-up
            if htf_at(i) in ("bull", "bear"):
                tags.append("htf_trend")                 # major = direction
            if S.internal_counter_trend(int_sw, i, direction):
                tags.append("complex_pullback")          # proper internal retrace
            if eff >= 0.95:
                tags.append("full_efficiency")           # reached the zone
            if abs(c[i] - o[i]) > abs(c[i - 1] - o[i - 1]):
                tags.append("engulf")                    # intention, with aggression
            rng = max(h[i] - l[i], 1e-9)
            ft = (c[i] - l[i]) / rng if direction == "bear" else (h[i] - c[i]) / rng
            if ft < 0.35:
                tags.append("follow_through")
            if abs(gap_hi - gap_lo) / entry * 100 > cfg.min_stop_pct * 0.5:
                tags.append("real_gap")
            if (direction == "bear" and pdp > 0.75) or (direction == "bull" and pdp < 0.25):
                tags.append("deep_pd")

            # his veto: both indexes must be saying the same thing
            if cfg.require_index_align:
                if pair_bos is None:
                    # The veto needs the correlated index. Without it this
                    # branch refused EVERY setup and reported as "no edge"
                    # rather than "misconfigured", which is how it ran live in
                    # the demo while being invisible to evaluate.py.
                    raise ValueError(
                        f"require_index_align is on but {pair_why}. Pass "
                        f"smt_df=<the other index> to find_setups, or turn the "
                        f"veto off.")
                k = pair_at.get(idx[i])
                if k is None:
                    continue
                lo_k = max(0, k - cfg.align_window)
                hi_k = k + cfg.align_window + 1
                if not any(b in pair_bos[direction] for b in range(lo_k, hi_k)):
                    continue

            # his condition: divergence only counts AT a sweep, never on its
            # own, or it "shows up all the time and is pretty much useless"
            if smt_divs is not None:
                k = smt_at.get(idx[i])
                side_now = "short" if direction == "bear" else "long"
                hit = (smt_mod.agrees(smt_divs, k, side_now,
                                      window=cfg.smt_window)
                       if k is not None else None)
                if hit is not None:
                    tags.append("smt")
                elif cfg.require_smt:
                    continue
            elif cfg.require_smt:
                continue

            if len(tags) < cfg.min_confluences:
                continue
            if cfg.require_tags and not set(cfg.require_tags) <= set(tags):
                continue

            setups.append(Setup(
                bar=i, side="short" if direction == "bear" else "long",
                entry=float(entry), stop=float(stop), target=float(draw),
                rr=float(rr), swept_price=float(slevel),
                confluences=len(tags), tags="|".join(tags),
                efficiency=round(float(eff), 2),
                reason=f"swept {skind}@{slevel:.1f} -> {direction} BOS, "
                       f"eff {eff:.2f}, target {draw_src}",
            ))
            recent.remove((sbar, skind, slevel, sextreme))
            break

    return setups
