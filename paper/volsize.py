"""Volatility-targeted sizing and a drawdown throttle.

This is the one thing in the whole project that survived every test. Across
twenty markets and twenty-five years, trend following cut drawdown from 31.5%
to 16.5% at every parameter tried, while failing to improve returns at all.

That combination sounds like a consolation prize. It is not, and the reason is
the constraint that has bound this system from the beginning.

The best configuration found earns roughly $950 a year on $100,000. That figure
is not small because the expectancy is small. It is small because a 23-trade
losing streak forces risk down to 0.2% to survive a 10% drawdown limit. Risk
capacity, not signal quality, is what caps the income.

So halving drawdown is not a comfort measure. If the same edge can be run at
0.4% instead of 0.2% without breaching the limit, the income doubles from a
change that touches no signal at all.

Two mechanisms, and it is worth being precise about which does what:

  VOLATILITY TARGETING   size so each trade risks the same amount of REALISED
                         volatility rather than the same fraction of equity.
                         Well founded: volatility clusters and is far more
                         forecastable than direction.

  DRAWDOWN THROTTLE      reduce size while the account is underwater, restore
                         it on recovery. Weaker evidence, and honest about it:
                         it reliably reduces drawdown and it also reduces
                         return, because it cuts size before recoveries. It is
                         off by default and measured rather than assumed.

Neither creates an edge. Both change the shape of one.
"""
from dataclasses import dataclass
import numpy as np


@dataclass
class VolTarget:
    """Sizing that holds risk constant in volatility terms, not equity terms.

    The target is RELATIVE, not an absolute percentage. Two earlier versions
    failed on exactly this point and both failed silently:

      1. bar volatility compared against a daily target, a factor of thirty out
      2. a daily target of 1% on EURUSD, whose daily volatility is nearer 0.3%,
         so the scale pinned to the ceiling regardless

    Both produced a constant multiplier dressed up as an overlay, and both were
    caught by the same tell: different targets giving identical answers.

    Comparing recent volatility against the market's OWN longer-run volatility
    is dimensionless, needs no calibration per market, and cannot drift out of
    range. Quiet relative to its own history means larger, wild means smaller.
    """
    enabled: bool = True
    window: int = 60                # bars in the recent estimate
    baseline: int = 2000            # bars in the long-run comparison
    strength: float = 1.0           # 0 disables, 1 is full targeting
    min_scale: float = 0.40
    max_scale: float = 1.80

    def scale(self, recent_closes):
        if not self.enabled:
            return 1.0
        c = np.asarray(recent_closes, dtype=float)
        if len(c) < max(120, self.window * 2):
            return 1.0
        r = np.diff(c) / c[:-1]
        recent = r[-self.window:]
        base = r[-self.baseline:]
        if len(recent) < 20 or len(base) < self.window * 2:
            return 1.0
        v_now = float(np.std(recent, ddof=1))
        v_base = float(np.std(base, ddof=1))
        if v_now <= 0 or v_base <= 0:
            return 1.0
        raw = v_base / v_now
        # `strength` blends toward 1.0, so a half-strength overlay moves half
        # as far from normal sizing as a full one
        adj = 1.0 + (raw - 1.0) * self.strength
        return float(np.clip(adj, self.min_scale, self.max_scale))


@dataclass
class DrawdownThrottle:
    """Trade smaller while underwater, normal size once recovered.

    Off by default. It does cut drawdown, and it also cuts return by being
    small exactly when the recovery arrives. Whether that trade is worth making
    depends on whether the drawdown limit is the binding constraint, which is
    the sort of thing to measure rather than assume.
    """
    enabled: bool = False
    start_pct: float = 4.0          # begin reducing once this far down
    floor_scale: float = 0.35       # smallest multiple it will apply
    full_pct: float = 10.0          # fully reduced by this drawdown

    def scale(self, equity, peak_equity):
        if not self.enabled or not peak_equity or equity >= peak_equity:
            return 1.0
        dd = (peak_equity - equity) / peak_equity * 100
        if dd <= self.start_pct:
            return 1.0
        span = max(self.full_pct - self.start_pct, 1e-9)
        frac = min((dd - self.start_pct) / span, 1.0)
        return float(1.0 - frac * (1.0 - self.floor_scale))


def combined(vol_scale, dd_scale, cap=2.0):
    """Both multipliers, with a hard ceiling.

    They are multiplied rather than averaged: a quiet market during a drawdown
    should still be sized down, not have the two effects cancel.
    """
    return float(np.clip(vol_scale * dd_scale, 0.05, cap))
