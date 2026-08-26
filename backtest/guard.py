"""Statistical guardrails, so the tooling catches what I had to catch by hand.

Every mistake in this project would have been prevented by this file:

  * a "+0.464R" result that was 16 trades
  * a data artefact that passed thirteen robustness checks
  * twelve strategies tested with no adjustment to the bar for significance

The rule enforced here: a number is not an edge until it clears its own
confidence interval, AND the bar rises with every additional hypothesis tested.
Anything below the bar prints as "not distinguishable from zero" rather than as
a tempting figure.
"""
import json, math, os
from dataclasses import dataclass, asdict
import numpy as np

LEDGER = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "results", "hypothesis_ledger.json")


# --------------------------------------------------------------------------
# hypothesis counting
# --------------------------------------------------------------------------
class Ledger:
    """Counts how many things have been tested against a dataset.

    Testing twenty strategies and reporting the best is not the same as testing
    one and reporting it, but the number on the screen looks identical. This
    keeps score so the bar can be raised honestly.
    """

    def __init__(self, path=LEDGER):
        self.path = path
        self.data = {}
        if os.path.exists(path):
            try:
                self.data = json.load(open(path, encoding="utf-8"))
            except Exception:
                self.data = {}

    def record(self, dataset, label):
        d = self.data.setdefault(dataset, [])
        if label not in d:
            d.append(label)
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            json.dump(self.data, open(self.path, "w", encoding="utf-8"), indent=1)
        return len(d)

    def count(self, dataset):
        return max(1, len(self.data.get(dataset, [])))

    def reset(self, dataset=None):
        if dataset:
            self.data.pop(dataset, None)
        else:
            self.data = {}
        json.dump(self.data, open(self.path, "w", encoding="utf-8"), indent=1)


# --------------------------------------------------------------------------
# the verdict
# --------------------------------------------------------------------------
@dataclass
class Verdict:
    n: int
    mean_r: float
    sd_r: float
    stderr: float
    ci_low: float
    ci_high: float
    t_stat: float
    hypotheses: int
    bar: float                 # what the mean must clear, after adjustment
    is_edge: bool
    headline: str
    detail: str

    def __str__(self):
        return f"{self.headline}\n    {self.detail}"


def _z_for(alpha):
    """Two-sided normal critical value without scipy."""
    # Acklam's inverse normal CDF, good to ~1e-9 which is far more than needed
    p = 1 - alpha / 2
    a = [-39.69683028665376, 220.9460984245205, -275.9285104469687,
         138.3577518672690, -30.66479806614716, 2.506628277459239]
    b = [-54.47609879822406, 161.5858368580409, -155.6989798598866,
         66.80131188771972, -13.28068155288572]
    c = [-0.007784894002430293, -0.3223964580411365, -2.400758277161838,
         -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [0.007784695709041462, 0.3224671290700398, 2.445134137142996,
         3.754408661907416]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p > ph:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
                ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    q = p - 0.5
    r = q * q
    return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / \
           (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)


def assess(returns_r, dataset="unknown", label=None, alpha=0.05,
           ledger=None, min_trades=100):
    """Judge a set of trade results honestly.

    `returns_r` is the per-trade result in R multiples.
    `dataset` and `label` feed the hypothesis ledger so the bar rises as more
    ideas are tested against the same data.
    """
    r = np.asarray([x for x in returns_r], dtype=float)
    n = len(r)
    led = ledger if ledger is not None else Ledger()
    k = led.record(dataset, label) if label else led.count(dataset)

    if n == 0:
        return Verdict(0, 0, 0, 0, 0, 0, 0, k, 0, False,
                       "NO TRADES", "nothing to judge")

    mean = float(r.mean())
    sd = float(r.std(ddof=1)) if n > 1 else 0.0
    se = sd / math.sqrt(n) if n > 1 else float("inf")

    # Sidak correction: with k independent tests, the per-test alpha must
    # tighten to keep the overall false-positive rate at `alpha`.
    alpha_adj = 1 - (1 - alpha) ** (1 / k)
    z = abs(_z_for(alpha_adj))
    bar = z * se
    lo, hi = mean - z * se, mean + z * se
    t = mean / se if se and math.isfinite(se) else 0.0

    too_few = n < min_trades
    is_edge = (lo > 0) and not too_few

    if too_few:
        head = f"NOT ENOUGH TRADES ({n}, want {min_trades}+)"
        det = (f"mean {mean:+.3f}R but the 95% range is {lo:+.3f} to {hi:+.3f}R. "
               f"At this sample size that range is too wide to mean anything.")
    elif is_edge:
        head = f"EDGE: {mean:+.3f}R per trade"
        det = (f"n={n}, 95% range {lo:+.3f} to {hi:+.3f}R, entirely above zero. "
               f"Bar was {bar:+.3f}R after {k} hypothesis(es) tested.")
    else:
        head = "NOT DISTINGUISHABLE FROM ZERO"
        det = (f"mean {mean:+.3f}R, n={n}, 95% range {lo:+.3f} to {hi:+.3f}R. "
               f"Needed to clear {bar:+.3f}R after {k} hypothesis(es) tested. "
               f"Do not treat this as an edge.")

    return Verdict(n, round(mean, 4), round(sd, 3), round(se, 4),
                   round(lo, 4), round(hi, 4), round(t, 2), k, round(bar, 4),
                   is_edge, head, det)


def expected_best_by_luck(k, sd, n):
    """What the best of k worthless strategies scores by chance alone.

    If a real result is smaller than this, it is indistinguishable from having
    run the search at all.
    """
    if k < 2:
        return 0.0
    se = sd / math.sqrt(n)
    return _z_for(2 * (1 / (k + 1))) * se


if __name__ == "__main__":
    rng = np.random.default_rng(0)
    print("Worthless strategy, 500 trades:")
    print(" ", assess(rng.normal(0, 1.1, 500), "demo", "coinflip"))
    print()
    print("Real edge, 500 trades:")
    print(" ", assess(rng.normal(0.15, 1.1, 500), "demo", "realedge"))
    print()
    print("Real edge but only 16 trades - the QQQ trap:")
    print(" ", assess(rng.normal(0.45, 1.1, 16), "demo", "tinysample"))
