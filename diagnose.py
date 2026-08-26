"""Count how many candidates survive each stage of the rule sequence.

When a strategy produces zero setups the useful question is not "why" but
"where" - which filter is eating everything. This prints the funnel.
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from collections import Counter
from data.fetch import binance, resample
from engine import structure as S
from engine.strategy import Config


def funnel(df, cfg=None):
    cfg = cfg or Config()
    o = df["open"].to_numpy(float); h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float);  c = df["close"].to_numpy(float)
    idx = df.index
    swings = S.find_swings(h, l, cfg.swing_left, cfg.swing_right)
    n_hi = sum(1 for s in swings if s.kind == "high")
    n_lo = len(swings) - n_hi
    print(f"  swings found            {len(swings):,}  ({n_hi} high / {n_lo} low)")

    k = Counter()
    pools_seen = 0
    recent = []
    start = max(cfg.sweep_lookback, 60)

    for i in range(start, len(df) - 1):
        pools = S.equal_levels(swings, i, cfg.eq_tol_pct)
        pools_seen = max(pools_seen, len(pools))
        if pools:
            k["bars_with_pools"] += 1
        for p in pools:
            if S.sweep(h, l, c, i, p["price"], p["kind"]):
                k["sweeps"] += 1
                recent.append((i, p["kind"], p["price"],
                               h[i] if p["kind"] == "high" else l[i]))
        recent = [r for r in recent if i - r[0] <= cfg.sweep_lookback]
        if not recent:
            continue
        k["bars_with_live_sweep"] += 1

        state, sh, sl = S.structure_state(swings, i)
        for (sbar, skind, slevel, sextreme) in list(recent):
            if sbar == i:
                continue
            direction = "bear" if skind == "high" else "bull"
            if S.break_of_structure(c, swings, i, direction) is None:
                continue
            k["1_sweep_then_BOS"] += 1

            if cfg.require_premium:
                rhi, rlo = S.dealing_range(h, l, sbar, cfg.range_lookback)
                pd_pos = S.premium_discount(slevel, rhi, rlo)
                if (direction == "bear" and pd_pos < cfg.premium_min) or \
                   (direction == "bull" and pd_pos > (1.0 - cfg.premium_min)):
                    k["x_failed_premium"] += 1
                    continue
            k["2_passed_premium"] += 1

            ifc = S.find_ifc(o, c, i, direction, cfg.ifc_lookback)
            if ifc is None:
                k["x_no_IFC"] += 1; continue
            k["3_found_IFC"] += 1

            gap = S.find_imbalance(h, l, i, direction, cfg.fvg_lookback)
            if gap is None:
                k["x_no_imbalance"] += 1; continue
            k["4_found_imbalance"] += 1
            gap_lo, gap_hi, _ = gap

            entry = gap_hi if direction == "bear" else gap_lo
            stop = max(sextreme, h[i]) if direction == "bear" else min(sextreme, l[i])
            if (direction == "bear" and stop <= entry) or \
               (direction == "bull" and stop >= entry):
                k["x_stop_wrong_side"] += 1; continue
            k["5_stop_valid"] += 1

            risk = abs(entry - stop)
            sp = risk / entry * 100
            if sp < cfg.min_stop_pct:
                k["x_stop_too_tight"] += 1; continue
            if sp > cfg.max_stop_pct:
                k["x_stop_too_wide"] += 1; continue
            k["6_stop_size_ok"] += 1

            want = "low" if direction == "bear" else "high"
            cands = [p["price"] for p in pools if p["kind"] == want and
                     (p["price"] < entry if direction == "bear" else p["price"] > entry)]
            tgt = (max(cands) if direction == "bear" else min(cands)) if cands else (
                entry - risk * cfg.max_rr if direction == "bear" else entry + risk * cfg.max_rr)
            rr = abs(tgt - entry) / risk
            if rr > cfg.max_rr:
                rr = cfg.max_rr
            if rr < cfg.min_rr:
                k["x_rr_too_low"] += 1; continue
            k["7_SETUP"] += 1
            recent.remove((sbar, skind, slevel, sextreme))
            break

    print(f"  max pools at one time   {pools_seen}")
    for key in sorted(k):
        print(f"  {key:<24} {k[key]:,}")
    return k


if __name__ == "__main__":
    tf = sys.argv[1] if len(sys.argv) > 1 else "5min"
    print(f"loading BTCUSDT ... resampling to {tf}")
    df = binance("BTCUSDT", "1m", "2025-01-01", "2025-04-01", quiet=True)
    d = resample(df, tf) if tf != "1min" else df
    print(f"  {len(d):,} bars\n")
    funnel(d)
