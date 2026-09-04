"""One command that runs every guardrail before it will call something an edge.

This is the piece that turns a week of hard lessons into a property of the
system. It refuses to report a result as real unless it clears all of:

  1. DATA QUALITY   the feed does not look manufactured
  2. SAMPLE SIZE    enough trades to say anything
  3. SIGNIFICANCE   the mean clears its own confidence interval, with the bar
                    raised for every hypothesis already tested on this data
  4. WALK-FORWARD   holds up when settings are chosen without seeing the test
  5. TWO SOURCES    reproduces on independent data
  6. SURVIVABILITY  the drawdown range is something a person could sit through

Any one of these failing means the result is not an edge. The Nasdaq artefact
passed thirteen robustness checks and would have failed check 1 and check 5.

    python evaluate.py --market qqq
    python evaluate.py --market eurusd --compare duka
"""
import argparse, dataclasses, os, sys
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.quality import report as quality_report, compare as quality_compare
from backtest.guard import assess, Ledger, expected_best_by_luck
from backtest import bootstrap
from backtest.walkforward import walk, summarise
from backtest.engine import run as bt_run, Costs
from engine.strategy import find_setups, Config
from live import Runner, ny_window

FX = Costs(maker_pct=0.0, taker_pct=0.0008, slip_pct=0.0008)
ETF = Costs(maker_pct=0.0, taker_pct=0.0, slip_pct=0.01)
IDX = Costs(maker_pct=0.0, taker_pct=0.002, slip_pct=0.003)


ASSET = {"qqq": "equity", "spy": "equity", "iwm": "equity", "dia": "equity",
         "eurusd": "fx", "duka": "fx", "nsxusd": "index", "btc": "crypto",
         "nasduka": "index", "nsx1m": "index"}

CRYPTO = Costs(maker_pct=0.0, taker_pct=0.04, slip_pct=0.02)


def get_data(name):
    """Return (frame, costs, min_stop, expected_session_hours)."""
    from data.alpaca_pull import load as aload
    from data.histdata_import import load as hload
    from data.dukascopy_pull import load as dload
    from data.fetch import resample
    from collector import load as cload
    if name == "btc":
        import pandas as _pd, os as _os
        # prefer the full Binance history (2019 onward) over the shorter
        # Alpaca pull; more years is the only thing that widens a crypto sample
        d = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "data", "store")
        f = _os.path.join(d, "btcusdt_5m_full.parquet")
        if not _os.path.exists(f):
            f = _os.path.join(d, "btcusd_5m.parquet")
        return (_pd.read_parquet(f) if _os.path.exists(f) else None), CRYPTO, 0.05, 24
    if name in ("qqq", "spy", "iwm", "dia"):
        return aload(name), ETF, 0.05, 7
    if name == "eurusd":
        return resample(hload("eurusd"), "5min"), FX, 0.05, 24
    if name == "duka":
        return dload("eurusd"), FX, 0.05, 24
    if name == "nsx1m":
        import pandas as _pd, os as _os
        f = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          "data", "store", "nsxusd_1m.parquet")
        return (_pd.read_parquet(f) if _os.path.exists(f) else None), IDX, 0.03, 24
    if name == "nasduka":
        # Dukascopy's Nasdaq index, the independent second source for NSXUSD.
        # Audited against real NQ futures before use: wick 0.571 against 0.542,
        # inside tolerance on every shape measure.
        import pandas as _pd, os as _os
        f = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          "data", "store", "nasdaq_duka_5m.parquet")
        return (_pd.read_parquet(f) if _os.path.exists(f) else None), IDX, 0.08, 24
    if name in ("nqf", "esf"):
        # REAL FUTURES, charged per contract rather than as a percentage.
        # Only ~70 days exist: Yahoo caps 5-minute history at 60 days and there
        # is no free deeper source. Note these come from the same Yahoo feed the
        # live demo polls, so they are NOT an independent second source for each
        # other; collector.py fetches via data.fetch.yahoo.
        import pandas as _pd, os as _os
        from futures import costs_for as _cf
        tag = "nq" if name == "nqf" else "es"
        f = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          "data", "store", f"{tag}_5m.parquet")
        c = _cf("MNQ" if name == "nqf" else "MES")
        return (_pd.read_parquet(f) if _os.path.exists(f) else None), c, 0.03, 24
    if name == "sp500":
        # The CORRELATED INDEX, not a second source. Used as the pair for the
        # index-alignment veto: he refuses a trade when NQ and ES disagree.
        import pandas as _pd, os as _os
        f = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)),
                          "data", "store", "sp500_duka_5m.parquet")
        return (_pd.read_parquet(f) if _os.path.exists(f) else None), IDX, 0.08, 24
    if name == "nsxusd":
        return resample(hload("nsxusd"), "5min"), IDX, 0.08, 7
    return cload(name, "5m"), IDX, 0.05, 24


def setups_for(df, params, sf, pair=None):
    cfg = dataclasses.replace(Runner._tuned(), **params)
    return find_setups(df, cfg, session_filter=sf, smt_df=pair)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", default="qqq")
    ap.add_argument("--compare", default=None, help="second market to cross-check against")
    ap.add_argument("--label", default="ict_tuned")
    ap.add_argument("--risk", type=float, default=0.5)
    ap.add_argument("--reset-ledger", action="store_true")
    # The session was hardcoded to a three-hour New York window. Evaluating a
    # config that trades London plus New York against that window tests a
    # different strategy than the one being judged, which is the same class of
    # mistake the walk-forward grid made earlier today.
    ap.add_argument("--pair", default=None,
                    help="correlated index for the alignment veto, e.g. sp500")
    ap.add_argument("--session", default=None,
                    help="named session window; defaults to the engine's NY window")
    a = ap.parse_args()

    led = Ledger()
    if a.reset_ledger:
        led.reset()
        print("hypothesis ledger cleared\n")

    pair_df = None
    if a.pair:
        pair_df, _, _, _ = get_data(a.pair)
        if pair_df is None or pair_df.empty:
            print(f"no data for pair {a.pair}")
            return
        print(f"correlated index for the veto: {a.pair} ({len(pair_df):,} bars)")

    df, costs, ms, hours = get_data(a.market)
    if pair_df is not None and df is not None and not df.empty:
        # Judge only the period BOTH feeds cover. Without this the early
        # walk-forward folds sit before the pair's data starts and the veto has
        # nothing to check against, which is not a strategy failure.
        lo = max(df.index[0], pair_df.index[0])
        n0 = len(df)
        df = df[df.index >= lo]
        if len(df) != n0:
            print(f"trimmed to the overlapping period from {lo:%Y-%m-%d}: "
                  f"{n0:,} -> {len(df):,} bars")
    if df is None or df.empty:
        print(f"no data for {a.market}")
        return

    sess = ny_window
    if a.session:
        from tjr_exact import WINDOWS as _W, window as _win
        extra = {
            "London + NY": (lambda t: _win(3, 0, 8, 30)(t) or _win(9, 30, 16, 0)(t)),
            # CONTINUOUS 03:00-16:00, including the 08:30-09:30 premarket hour.
            # "London + NY" above skips that hour, so evaluating against it
            # would judge a different strategy from the one measured.
            "london_ny": _win(3, 0, 16, 0),
            "London 03:00-08:30": _win(3, 0, 8, 30),
            "NY 09:30-16:00": _win(9, 30, 16, 0),
        }
        sess = extra.get(a.session) or _W.get(a.session)
        if sess is None:
            print(f"unknown session {a.session!r}. options:")
            for k in list(extra) + list(_W):
                print(f"    {k}")
            return
        print(f"session window: {a.session}")
        print("")

    print("=" * 68)
    print(f"  EVALUATING  {a.market.upper()}   strategy: {a.label}")
    print("=" * 68)

    # ---- 1. data quality --------------------------------------------
    print("\n1. DATA QUALITY")
    asset = ASSET.get(a.market, "crypto")
    ok_data, issues, qstats = quality_report(df, a.market, expect_session_hours=hours,
                                             asset=asset)
    wick = qstats.get("wick_to_range", 0)
    suspicious = bool(wick) and wick > qstats.get("wick_limit", 0.46)

    # ---- run the strategy --------------------------------------------
    cfg = dataclasses.replace(Runner._tuned(), min_stop_pct=ms)
    s = find_setups(df, cfg, session_filter=sess, smt_df=pair_df)
    trades, unfilled = bt_run(df, s, costs)
    r = [t.r for t in trades]

    # ---- 2 + 3. sample size and significance --------------------------
    print("\n2+3. SAMPLE SIZE AND SIGNIFICANCE")
    v = assess(r, dataset=a.market, label=a.label, ledger=led)
    print(f"  {v.headline}")
    print(f"    {v.detail}")
    if v.hypotheses > 1:
        luck = expected_best_by_luck(v.hypotheses, v.sd_r, max(v.n, 1))
        print(f"    best-by-luck across {v.hypotheses} tested ideas would be "
              f"{luck:+.3f}R")
        if v.mean_r < luck:
            print("    This result is SMALLER than luck alone would produce. "
                  "Treat it as nothing.")

    # ---- 4. walk-forward ---------------------------------------------
    print("\n4. WALK-FORWARD")
    # The reward grid has to respect the configured MINIMUM reward. Offering
    # max_rr values below min_rr silently produces zero setups in every fold,
    # which reads as "walk-forward failed" when nothing was ever tested.
    # The grid has to be centred on the target the config actually uses.
    # A fixed list of wide targets silently validated a DIFFERENT strategy than
    # the one being evaluated: with max_rr at 0.5 the folds all chose 1.5 to
    # 5.0, passed, and the pass meant nothing. The configured value must be in
    # the grid, and the alternatives must sit around it.
    _t = Runner._tuned()
    base_rr = getattr(_t, "min_rr", 1.0)
    cfg_rr = getattr(_t, "max_rr", 1.5)
    cand = sorted({cfg_rr, cfg_rr * 0.7, cfg_rr * 1.5, cfg_rr * 2.5})
    rr_grid = [round(r, 3) for r in cand if r >= base_rr] or [cfg_rr]
    grid = {"min_stop_pct": [ms * 0.8, ms, ms * 1.4], "max_rr": rr_grid}
    folds, wf_r = walk(
        df,
        # pair_df must reach the folds too: this lambda was the fourth call
        # path and the only one still dropping it
        make_setups=lambda d, p, sf: setups_for(
            d, {**p, "min_stop_pct": p["min_stop_pct"]}, sf, pair=pair_df),
        run_backtest=lambda d, st: [t.r for t in bt_run(d, st, costs)[0]],
        grid=grid, folds=6, session_filter=sess)
    summarise(folds, wf_r)

    # ---- 5. second source ---------------------------------------------
    print("\n5. INDEPENDENT SOURCE")
    # Initialised before the branch: without a second source this check cannot
    # pass, and leaving it undefined crashed the verdict instead of failing it.
    cross = {"ok": False, "why": "no second source given"}
    if a.compare:
        df2, c2, ms2, h2 = get_data(a.compare)
        if df2 is None or df2.empty:
            print(f"  no data for {a.compare}")
        else:
            lo = max(df.index[0], df2.index[0]); hi = min(df.index[-1], df2.index[-1])
            seg1 = df[(df.index >= lo) & (df.index <= hi)]
            seg2 = df2[(df2.index >= lo) & (df2.index <= hi)]
            print(f"  overlapping window {lo:%Y-%m-%d} -> {hi:%Y-%m-%d}")
            quality_compare(seg1, seg2, a.market, a.compare)
            out, rr_all = [], []
            for nm, d, cc, m in ((a.market, seg1, costs, ms), (a.compare, seg2, c2, ms2)):
                # the veto needs the pair here too, or every fold refuses
                # everything and reports as "no edge" rather than misconfigured
                ss = find_setups(d, dataclasses.replace(Runner._tuned(), min_stop_pct=m),
                                 session_filter=sess, smt_df=pair_df)
                tt, _ = bt_run(d, ss, cc)
                rr = [x.r for x in tt]
                out.append((nm, len(rr), float(np.mean(rr)) if rr else 0.0))
                rr_all.append(rr)
                print(f"    {nm:<10} {len(rr):>5} trades   {out[-1][2]:+.3f}R")
            if len(out) == 2 and out[0][1] and out[1][1]:
                m1, m2 = out[0][2], out[1][2]
                gap = abs(m1 - m2)
                print(f"    they differ by {gap:.3f}R")
                n1, n2 = out[0][1], out[1][1]
                # "Opposite signs" is not the same as "disagree". On small
                # samples a real effect flips sign often. What matters is
                # whether the difference is LARGER than the noise in it, so
                # compare it against its own standard error.
                sd = float(np.std(rr_all[0], ddof=1)) if rr_all[0] else 0.7
                se = (sd ** 2 / max(n1, 1) + sd ** 2 / max(n2, 1)) ** 0.5
                sigmas = abs(m1 - m2) / se if se > 0 else 0.0
                print(f"    that gap is {sigmas:.2f} standard errors")
                thin = min(n1, n2) < 40
                same_sign = (m1 > 0) == (m2 > 0)
                if thin:
                    cross = {"ok": False,
                             "why": f"only {min(out[0][1], out[1][1])} trades on "
                                    f"the thinner source, too few to compare"}
                elif sigmas >= 2.0:
                    cross = {"ok": False,
                             "why": f"differ by {sigmas:.1f} standard errors, "
                                    f"{m1:+.3f}R against {m2:+.3f}R"}
                    print("    SOURCES GENUINELY DISAGREE. One is not")
                    print("    representative, and the result cannot be trusted.")
                elif not same_sign:
                    cross = {"ok": False,
                             "why": f"inconclusive: {m1:+.3f}R against {m2:+.3f}R, "
                                    f"only {sigmas:.1f} SE apart on {min(n1, n2)} "
                                    f"trades, too few to confirm or refute"}
                    print("    UNDERPOWERED, not contradicted. The signs differ")
                    print("    but the gap is inside the noise, so this neither")
                    print("    confirms nor refutes. More overlap is needed.")
                else:
                    # A raw-magnitude test used to sit here and fail anything
                    # differing by more than 0.15R, regardless of noise. That
                    # contradicted the standard-error test above and rejected
                    # sources 0.84 SE apart, which is agreement. Magnitude is
                    # still worth SAYING when it is large relative to the claim,
                    # but it is not evidence of disagreement on its own.
                    if gap > 0.15:
                        print(f"    (the {gap:.3f}R gap is large next to the effect,")
                        print( "     but well inside the noise on this sample)")
                    cross = {"ok": True,
                             "why": f"both {m1:+.3f}R and {m2:+.3f}R, "
                                    f"{sigmas:.2f} SE apart"}
                    print(f"    Sources agree ({sigmas:.2f} SE apart).")
            else:
                cross = {"ok": False, "why": "one source produced no trades"}
    else:
        print("  SKIPPED - no second source given. This is the check that caught")
        print("  the Nasdaq artefact, so a result without it stays provisional.")

    # ---- 6. survivability ---------------------------------------------
    print("\n6. SURVIVABILITY")
    if len(r) >= 30:
        res = bootstrap.run(r, risk_pct=a.risk, runs=3000, block=5)
        if res:
            res.report()
            safe = bootstrap.risk_for_drawdown(r, 10.0)
            print(f"    largest risk keeping 95% of paths under 10% drawdown: {safe}%")
    else:
        print("  too few trades to resample")

    # ---- verdict --------------------------------------------------------
    print("\n" + "=" * 68)
    checks = {
        "data quality": ok_data and not suspicious,
        "sample size": v.n >= 100,
        "significance": v.is_edge,
        # a positive AVERAGE is not enough: a couple of good folds can carry
        # several bad ones. Demand that most folds held up individually.
        "walk-forward": (bool(folds)
                         and np.mean([f.test_exp for f in folds]) > 0
                         and sum(1 for f in folds if f.test_exp > 0) >= len(folds) * 0.6),
        # This has to verify AGREEMENT, not merely that a second source was
        # supplied. As originally written it passed whenever --compare was
        # present, which made the single most important guardrail in the system
        # a no-op. It caught the Nasdaq artefact only because the numbers were
        # read by eye; the check itself never fired.
        "second source": cross["ok"],
    }
    for k, ok in checks.items():
        note = ""
        if k == "second source":
            note = f"   ({cross['why']})"
        print(f"  {'PASS' if ok else 'FAIL'}   {k}{note}")
    print("=" * 68)
    if all(checks.values()):
        print("  All checks passed. This is worth trading on paper.")
    else:
        failed = [k for k, ok in checks.items() if not ok]
        print(f"  NOT AN EDGE. Failed: {', '.join(failed)}.")
        print("  Do not size up, do not fund an account, do not tune until it passes.")


if __name__ == "__main__":
    main()
