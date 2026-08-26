"""Resample the trade sequence to find the RANGE of outcomes, not one path.

A backtest shows a single ordering of trades. That ordering is one draw from a
much wider distribution, and the drawdown it happens to show is not the drawdown
you should plan for. Reshuffling the same trades thousands of times answers a
better question: not "what did it do" but "what could it plausibly do".

The useful output is never "27% drawdown". It is "a 5% chance of worse than 40%",
because that is the number that decides whether you can actually sit through it.
"""
from dataclasses import dataclass
import numpy as np


@dataclass
class BootResult:
    runs: int
    risk_pct: float
    median_return: float
    p05_return: float
    p95_return: float
    median_dd: float
    p95_dd: float
    worst_dd: float
    prob_profit: float
    prob_dd_over_10: float
    prob_dd_over_20: float
    prob_ruin: float
    median_worst_streak: int
    p95_worst_streak: int

    def report(self):
        print(f"  {self.runs:,} resamples at {self.risk_pct:.2f}% risk per trade")
        print(f"    return   median {self.median_return:+7.1f}%   "
              f"5th pct {self.p05_return:+7.1f}%   95th pct {self.p95_return:+7.1f}%")
        print(f"    drawdown median {self.median_dd:7.1f}%   "
              f"95th pct {self.p95_dd:7.1f}%   worst seen {self.worst_dd:7.1f}%")
        print(f"    chance of finishing up          {self.prob_profit*100:5.1f}%")
        print(f"    chance of a drawdown over 10%   {self.prob_dd_over_10*100:5.1f}%")
        print(f"    chance of a drawdown over 20%   {self.prob_dd_over_20*100:5.1f}%")
        if self.prob_ruin > 0:
            print(f"    chance of losing half the account {self.prob_ruin*100:5.1f}%")
        print(f"    worst losing streak: median {self.median_worst_streak}, "
              f"95th pct {self.p95_worst_streak}")


def run(returns_r, risk_pct=1.0, runs=5000, seed=0, block=0):
    """Resample the trade results and compound each path.

    `block` > 1 uses block resampling, which keeps short runs of trades together.
    That matters because losses in trading tend to cluster: independent shuffling
    quietly assumes they do not, and so understates the drawdown.
    """
    r = np.asarray(list(returns_r), dtype=float)
    n = len(r)
    if n < 10:
        return None
    rng = np.random.default_rng(seed)
    risk = risk_pct / 100.0

    finals, dds, streaks = np.empty(runs), np.empty(runs), np.empty(runs, dtype=int)
    for i in range(runs):
        if block and block > 1:
            nb = int(np.ceil(n / block))
            starts = rng.integers(0, max(1, n - block), nb)
            path = np.concatenate([r[s:s + block] for s in starts])[:n]
        else:
            path = r[rng.integers(0, n, n)]

        eq = np.cumprod(1 + risk * path)
        peak = np.maximum.accumulate(eq)
        dd = (peak - eq) / peak
        finals[i] = (eq[-1] - 1) * 100
        dds[i] = dd.max() * 100

        st = worst = 0
        for x in path:
            st = st + 1 if x <= 0 else 0
            if st > worst:
                worst = st
        streaks[i] = worst

    return BootResult(
        runs=runs, risk_pct=risk_pct,
        median_return=float(np.median(finals)),
        p05_return=float(np.percentile(finals, 5)),
        p95_return=float(np.percentile(finals, 95)),
        median_dd=float(np.median(dds)),
        p95_dd=float(np.percentile(dds, 95)),
        worst_dd=float(dds.max()),
        prob_profit=float((finals > 0).mean()),
        prob_dd_over_10=float((dds > 10).mean()),
        prob_dd_over_20=float((dds > 20).mean()),
        prob_ruin=float((finals < -50).mean()),
        median_worst_streak=int(np.median(streaks)),
        p95_worst_streak=int(np.percentile(streaks, 95)),
    )


def risk_for_drawdown(returns_r, max_dd_pct=10.0, confidence=0.95,
                      runs=2000, seed=0, block=5):
    """Largest risk per trade that keeps drawdown under a limit, at a given
    confidence. This is the question a prop firm actually asks."""
    lo, hi, best = 0.05, 3.0, 0.0
    for _ in range(12):
        mid = (lo + hi) / 2
        res = run(returns_r, risk_pct=mid, runs=runs, seed=seed, block=block)
        if res is None:
            return 0.0
        ok = res.p95_dd <= max_dd_pct if confidence >= 0.95 else res.median_dd <= max_dd_pct
        if ok:
            best, lo = mid, mid
        else:
            hi = mid
    return round(best, 3)


if __name__ == "__main__":
    rng = np.random.default_rng(1)
    # a modest but real edge: 45% win rate at 1.5R, losers at -1R
    wins = rng.random(600) < 0.45
    demo = np.where(wins, 1.5, -1.0) + rng.normal(0, 0.1, 600)
    print("A real but modest edge, 600 trades:")
    for risk in (0.5, 1.0, 2.0):
        res = run(demo, risk_pct=risk, runs=3000, block=5)
        res.report()
        print()
    print(f"largest risk keeping 95% of paths under a 10% drawdown: "
          f"{risk_for_drawdown(demo, 10.0)}%")
