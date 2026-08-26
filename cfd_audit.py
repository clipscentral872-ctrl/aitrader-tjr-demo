"""Audit a CFD feed against real exchange data before trusting it.

This is the check that would have saved a week. The strongest result of the
project, +0.223R on the Nasdaq, came from NSXUSD: a synthetic index CFD that
quoted around the clock and carried a wick-to-range ratio of 0.536 against
QQQ's 0.416 over the same period, with the two correlated at +0.976. The extra
wick manufactured the exact liquidity sweeps the strategy hunts. It passed
thirteen robustness tests before a second data source caught it.

Free NQ and ES history in usable depth exists only as a Dukascopy index CFD,
which is the same instrument class. Yahoo carries sixty days of real exchange
futures — too short to trade on, but exactly long enough to audit against.

What matters is not whether the prices track each other. NSXUSD tracked QQQ at
+0.976 and was still useless. What matters is whether the BAR SHAPE matches,
because bar shape is what the strategy reads.

    python cfd_audit.py
"""
import os, sys, time
import functools
print = functools.partial(print, flush=True)
import datetime as dt
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from data.dukascopy_pull import fetch_hour, to_bars
from data.fetch import yahoo
from data.quality import check as quality_check


def cfd_sample(sym, days, hours, pause=0.8):
    """Fetch specific hours directly, rather than a bulk pull.

    Bulk downloading forty-five days takes an hour and competes with whatever
    else is running. A scattered sample of the same feed answers the shape
    question just as well and takes two minutes.
    """
    frames = []
    for d in days:
        for h in hours:
            try:
                t = fetch_hour(sym, d, h)
                if t is not None and len(t):
                    frames.append(t)
            except Exception:
                pass
            time.sleep(pause)
    if not frames:
        return pd.DataFrame()
    ticks = pd.concat(frames).sort_index()
    ticks = ticks[~ticks.index.duplicated(keep="first")]
    return to_bars(ticks, "5min")


def shape(df, label):
    o, h, l, c = (df[x].to_numpy(float) for x in ("open", "high", "low", "close"))
    rng = h - l
    body = np.abs(c - o)
    wick = np.clip(rng - body, 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        wr = np.where(rng > 0, wick / rng, np.nan)
    ret = np.zeros(len(c))
    ret[1:] = np.diff(c) / c[:-1]
    return {
        "label": label,
        "bars": len(df),
        "wick": float(np.nanmean(wr)),
        "range_pct": float(np.nanmean(rng / c) * 100),
        "flat_pct": float((rng == 0).mean() * 100),
        "body_pct": float(np.nanmean(body / c) * 100),
        "autocorr": float(np.corrcoef(ret[1:-1], ret[2:])[0, 1]) if len(ret) > 50 else np.nan,
    }


def main():
    print("=" * 78)
    print("  CFD AUDIT   Dukascopy Nasdaq index against real NQ futures")
    print("=" * 78)

    print("\n  fetching real exchange futures from Yahoo ...")
    real = yahoo("NQ=F", "5m", "60d")
    if real is None or real.empty:
        print("  could not get NQ=F")
        return
    print(f"  NQ=F: {len(real):,} bars  {real.index[0]:%Y-%m-%d} -> "
          f"{real.index[-1]:%Y-%m-%d}")

    # sample the CFD across the SAME window, during US cash hours so the two
    # are quoting the same market rather than different parts of the day
    lo, hi = real.index[0].date(), real.index[-1].date()
    days, d = [], lo
    while d <= hi:
        if d.weekday() < 5:
            days.append(d)
        d += dt.timedelta(days=1)
    # The Nasdaq CFD carries about 30,000 ticks an hour against EURUSD's 3,400,
    # so each file is nine times larger and a wide sample times out. Six
    # sessions of two hours is 24,000 bars of comparison, which is plenty to
    # measure bar shape.
    days = days[::7][:6]
    hours = [15, 16]                       # mid US session

    print(f"\n  sampling the CFD across {len(days)} sessions ...")
    cfd = cfd_sample("USATECHIDXUSD", days, hours)
    if cfd.empty:
        print("  CFD returned nothing (throttled, or the symbol is wrong)")
        return
    print(f"  CFD: {len(cfd):,} bars")

    # restrict the real series to the same hours so the comparison is like for like
    r_utc = real.tz_convert("UTC") if real.index.tz else real.tz_localize("UTC")
    r_seg = r_utc[np.isin(r_utc.index.hour, hours)]
    r_seg = r_seg[np.isin(r_seg.index.date, np.array(days))]
    if len(r_seg) < 200:
        r_seg = r_utc[np.isin(r_utc.index.hour, hours)]

    a = shape(r_seg, "NQ=F real")
    b = shape(cfd, "Dukascopy CFD")

    print("\n" + "-" * 78)
    print("  BAR SHAPE, which is what the strategy actually reads\n")
    print(f"  {'metric':<22} {'NQ=F real':>14} {'CFD':>14} {'difference':>13}")
    verdict_flags = []
    for key, name, tol in (("wick", "wick / range", 0.06),
                           ("range_pct", "mean range %", 0.35),
                           ("body_pct", "mean body %", 0.35),
                           ("flat_pct", "flat bars %", 3.0)):
        va, vb = a[key], b[key]
        if key in ("range_pct", "body_pct"):
            diff = abs(vb - va) / max(va, 1e-9)
            flag = diff > tol
            print(f"  {name:<22} {va:>14.4f} {vb:>14.4f} {diff*100:>12.0f}%")
        else:
            diff = abs(vb - va)
            flag = diff > tol
            print(f"  {name:<22} {va:>14.3f} {vb:>14.3f} {diff:>13.3f}")
        verdict_flags.append((name, flag))

    print(f"  {'bars sampled':<22} {a['bars']:>14,} {b['bars']:>14,}")

    print("\n" + "-" * 78)
    print("  THE CHECK THAT CAUGHT THE ARTEFACT\n")
    print(f"    NSXUSD, the feed that fooled us : 0.536 wick / range")
    print(f"    QQQ, real exchange data         : 0.416")
    print(f"    NQ=F here, real                 : {a['wick']:.3f}")
    print(f"    this CFD                        : {b['wick']:.3f}")
    gap = b["wick"] - a["wick"]
    print(f"\n    the CFD carries {gap:+.3f} more wick per bar than the real thing")

    print("\n" + "=" * 78)
    bad = [n for n, f in verdict_flags if f]
    if not bad:
        print("  The CFD matches the real contract on every shape measure.")
        print("  Safe to use for depth, with results still cross-checked")
        print("  against the sixty days of real data.")
    elif gap > 0.05:
        print(f"  REJECT. The CFD carries materially more wick ({b['wick']:.3f} against")
        print(f"  {a['wick']:.3f}), which is the NSXUSD signature exactly. Excess wick")
        print("  manufactures the sweeps this strategy trades, so any result on")
        print("  this feed would be inflated in the specific way that already")
        print("  cost this project a week.")
    else:
        print(f"  MIXED. Differs on: {', '.join(bad)}.")
        print("  Usable only with every result confirmed on the real sixty days.")
    print("=" * 78)


if __name__ == "__main__":
    main()
