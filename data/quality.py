"""Data quality checks, run before a dataset is allowed to produce conclusions.

The Nasdaq artefact was invisible to every statistical test we ran and obvious
in the bars themselves: it carried proportionally more wick than a real exchange
feed, and this strategy defines its entry as a wick through a level. The data
was manufacturing the pattern being hunted.

These checks run on ingest so bad data is caught before it becomes a belief.
"""
from dataclasses import dataclass, field
import numpy as np
import pandas as pd


@dataclass
class Issue:
    level: str        # "fail" | "warn" | "note"
    check: str
    detail: str


# Typical wick-to-range by asset class.
#
# RECALIBRATED 2026-08-23, and the original numbers were wrong in a way that
# matters. The equity and index limits of 0.46 were set from QQQ measured on
# Alpaca's free tier, which serves IEX only: a small slice of US volume. Fewer
# prints per bar means fewer extremes, so that feed reports 0.457 where the
# consolidated tape reports 0.526 on the same symbol over the same window.
#
# Measured on feeds known to be complete:
#     QQQ, consolidated tape (Yahoo)   0.526
#     NQ futures, real exchange        0.538
#     EURUSD, two independent vendors  0.511
#
# The old 0.46 limit would have flagged real exchange futures as manufactured.
# It also produced this project's headline finding, that NSXUSD at 0.536 was a
# synthetic feed. It sits within a hundredth of real NQ futures.
WICK_NORMS = {"equity": 0.58, "fx": 0.58, "crypto": 0.58, "index": 0.60}


def check(df, name="dataset", expect_session_hours=None, asset="equity"):
    """Run every check. Returns (issues, stats)."""
    issues, s = [], {}
    if df is None or df.empty:
        return [Issue("fail", "empty", "no rows at all")], s

    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    idx = df.index
    s["bars"] = len(df)
    s["from"] = f"{idx[0]:%Y-%m-%d}"
    s["to"] = f"{idx[-1]:%Y-%m-%d}"

    # ---- structural impossibilities ------------------------------------
    bad_hl = int((h < l).sum())
    if bad_hl:
        issues.append(Issue("fail", "high<low", f"{bad_hl:,} bars where high is below low"))
    outside = int(((o > h) | (o < l) | (c > h) | (c < l)).sum())
    if outside:
        issues.append(Issue("fail", "ohlc", f"{outside:,} bars where open or close sits outside the high-low range"))

    # ---- duplicates and ordering ---------------------------------------
    dupes = int(idx.duplicated().sum())
    if dupes:
        issues.append(Issue("fail", "duplicates", f"{dupes:,} duplicate timestamps"))
    if not idx.is_monotonic_increasing:
        issues.append(Issue("fail", "ordering", "timestamps are not in ascending order"))

    # ---- stale bars ------------------------------------------------------
    flat = (h == l)
    s["flat_bars_pct"] = round(float(flat.mean()) * 100, 2)
    if flat.mean() > 0.10:
        issues.append(Issue("warn", "stale",
                            f"{flat.mean()*100:.1f}% of bars have high == low, which usually means a filled-forward feed"))

    repeated = np.zeros(len(df), dtype=bool)
    repeated[1:] = (c[1:] == c[:-1]) & (h[1:] == h[:-1]) & (l[1:] == l[:-1])
    s["repeated_bars_pct"] = round(float(repeated.mean()) * 100, 2)
    if repeated.mean() > 0.05:
        issues.append(Issue("warn", "repeats",
                            f"{repeated.mean()*100:.1f}% of bars are identical to the one before"))

    # ---- gaps ------------------------------------------------------------
    deltas = pd.Series(idx).diff().dropna()
    if len(deltas):
        typical = deltas.mode()
        step = typical.iloc[0] if len(typical) else deltas.median()
        big = deltas[deltas > step * 12]
        s["typical_step"] = str(step)
        s["large_gaps"] = int(len(big))
        if len(big) > len(df) * 0.01:
            issues.append(Issue("warn", "gaps",
                                f"{len(big):,} gaps longer than 12 bars - check the feed is continuous"))

    # ---- the check that would have caught the artefact -------------------
    rng = (h - l)
    body = np.abs(c - o)
    wick = np.clip(rng - body, 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        ratio = np.where(rng > 0, wick / rng, np.nan)
    wr = float(np.nanmean(ratio))
    s["wick_to_range"] = round(wr, 3)
    s["mean_range_pct"] = round(float(np.nanmean(rng / c) * 100), 4)
    limit = WICK_NORMS.get(asset, 0.46)
    s["wick_limit"] = limit
    if wr > limit:
        issues.append(Issue("warn", "wickiness",
                            f"wick is {wr:.2f} of the bar range, above the {limit:.2f} "
                            f"normal for {asset}. Excess wick manufactures the exact "
                            f"liquidity sweeps this strategy hunts, so it inflates results"))

    # ---- session coverage -------------------------------------------------
    hours = sorted(set(idx.hour))
    s["hours_covered"] = len(hours)
    if expect_session_hours and len(hours) > expect_session_hours + 2:
        issues.append(Issue("note", "coverage",
                            f"quotes in {len(hours)} hours a day, expected about {expect_session_hours}. "
                            f"This is a round-the-clock feed, not an exchange session"))

    # ---- price sanity -----------------------------------------------------
    ret = np.diff(c) / c[:-1]
    jumps = int((np.abs(ret) > 0.10).sum())
    if jumps:
        issues.append(Issue("warn", "jumps", f"{jumps:,} single-bar moves over 10%"))
    s["max_move_pct"] = round(float(np.nanmax(np.abs(ret)) * 100), 2) if len(ret) else 0.0

    return issues, s


def report(df, name="dataset", expect_session_hours=None, verbose=True,
           asset="equity"):
    issues, s = check(df, name, expect_session_hours, asset)
    fails = [i for i in issues if i.level == "fail"]
    warns = [i for i in issues if i.level == "warn"]
    if verbose:
        print(f"  {name}")
        print(f"    {s.get('bars',0):,} bars  {s.get('from','?')} -> {s.get('to','?')}  "
              f"hours/day {s.get('hours_covered','?')}")
        print(f"    wick/range {s.get('wick_to_range','?')}   "
              f"mean range {s.get('mean_range_pct','?')}%   "
              f"flat {s.get('flat_bars_pct','?')}%   repeats {s.get('repeated_bars_pct','?')}%")
        if not issues:
            print("    no issues")
        for i in issues:
            tag = {"fail": "FAIL", "warn": "warn", "note": "note"}[i.level]
            print(f"    [{tag}] {i.check}: {i.detail}")
    return len(fails) == 0, issues, s


def compare(a, b, name_a="A", name_b="B"):
    """Two sources of the same market should look alike. Where they differ is
    where one of them is lying."""
    _, sa = check(a, name_a)
    _, sb = check(b, name_b)
    print(f"  {'metric':<20} {name_a:>14} {name_b:>14}")
    for k in ("bars", "hours_covered", "wick_to_range", "mean_range_pct",
              "flat_bars_pct", "repeated_bars_pct"):
        va, vb = sa.get(k, "-"), sb.get(k, "-")
        flag = ""
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)) and vb:
            d = abs(va - vb) / max(abs(vb), 1e-9)
            if d > 0.25:
                flag = "   <-- differ by " + f"{d*100:.0f}%"
        print(f"  {k:<20} {str(va):>14} {str(vb):>14}{flag}")
