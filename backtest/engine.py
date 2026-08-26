"""Backtest the setups honestly.

Every assumption here is deliberately pessimistic, because the whole point of
this exercise is to find out whether the edge is real, not to produce a nice
equity curve:

  * a limit order only fills if price actually trades back to it
  * if one bar's range covers BOTH the stop and the target, we assume the STOP
    hit first (this is the single biggest source of fake backtest profits)
  * costs are charged on entry and exit
  * a trade that never fills is recorded, because "the setup never appeared" is
    a number that matters and nobody tracks it
"""
from dataclasses import dataclass, asdict
import numpy as np
import pandas as pd


@dataclass
class Costs:
    """Two cost models, because the two asset classes charge differently.

    PERCENTAGE (crypto, forex): the fee scales with notional, so expressing it
    as a percent of price is correct.

    PER CONTRACT (futures): commission is a fixed dollar amount per contract and
    slippage is a number of ticks. It does NOT scale with notional. Charging
    futures as a percentage understated the real cost fivefold, which the paper
    broker caught by disagreeing with the backtest.

    Both work out to a fraction of R, and R is size-independent, so the cost in
    R can be computed from the stop distance alone.
    """
    maker_pct: float = 0.02      # entry side, percentage model
    taker_pct: float = 0.04      # exit side, percentage model
    slip_pct: float = 0.02       # slippage, percentage model

    per_contract: bool = False   # switch to the futures model
    commission_rt: float = 1.50  # dollars per contract, round turn
    slip_ticks: float = 1.0      # ticks given up on the exit
    tick_size: float = 0.25
    tick_value: float = 0.50     # MNQ

    def cost_in_r(self, entry, stop):
        """What the round trip costs, as a fraction of the risk."""
        dist = abs(entry - stop)
        if dist <= 0:
            return 0.0
        if self.per_contract:
            risk_per_ct = dist / self.tick_size * self.tick_value
            cost_per_ct = self.commission_rt + self.slip_ticks * self.tick_value
            return cost_per_ct / risk_per_ct if risk_per_ct else 0.0
        return entry * (self.maker_pct + self.taker_pct + self.slip_pct) / 100 / dist


@dataclass
class Trade:
    entry_bar: int
    exit_bar: int
    entry_time: pd.Timestamp
    exit_time: pd.Timestamp
    side: str
    entry: float
    stop: float
    target: float
    exit_price: float
    outcome: str          # win | loss | timeout | unfilled
    r: float              # result in R multiples, after costs
    rr_planned: float
    bars_held: int
    cost_r: float          # what the round trip cost, in R. If this is not
                           # small, the strategy is paying the exchange to trade.


@dataclass
class Execution:
    """How pessimistic to be about getting filled.

    The default backtest fills a limit order the moment price touches the level.
    That is the single most optimistic assumption left in it. In a real book you
    join a queue, and if price touches your level and turns away, the traders
    ahead of you got filled and you did not. The trades you lose that way are
    disproportionately the good ones, because the ones that turn straight around
    are exactly the winners.

    A stop is worse still: it becomes a market order, and on a gap it fills
    wherever the market reopens, not at the stop price.
    """
    require_through: bool = True   # price must trade past the level, not touch it
    # How far past. Expressed as a fraction of the entry-to-stop distance so it
    # means the same thing on EURUSD at 1.08 and on Bitcoin at 60,000. A fixed
    # tick here was a bug: 0.01 is one cent on a share and a hundred pips on
    # EURUSD, which silently removed every fill.
    through_frac: float = 0.02
    tick: float = 0.0              # set non-zero to use an absolute pad instead
    through_ticks: float = 1.0
    gap_stops: bool = True         # a stop that gaps fills at the open
    queue_ahead: bool = True       # a touch-and-turn bar does not fill


def run(df, setups, costs=None, fill_window=60, max_hold=240, execution=None):
    """Walk each setup forward and see what actually happened."""
    costs = costs or Costs()
    h = df["high"].to_numpy(float)
    l = df["low"].to_numpy(float)
    idx = df.index
    n = len(df)

    ex = execution or Execution()
    def _pad(entry, stop):
        if not ex.require_through:
            return 0.0
        if ex.tick:
            return ex.through_ticks * ex.tick
        return abs(entry - stop) * ex.through_frac
    o_ = df["open"].to_numpy(float)
    trades, unfilled, missed_queue = [], 0, 0
    busy_until = -1                     # one position at a time

    for s in setups:
        if s.bar <= busy_until:
            continue

        # ---- wait for the limit to fill -------------------------------
        pad = _pad(s.entry, s.stop)
        fill = None
        for i in range(s.bar + 1, min(s.bar + 1 + fill_window, n)):
            # price must trade THROUGH the level, not merely touch it
            if s.side == "short" and h[i] >= s.entry + pad:
                fill = i; break
            if s.side == "long" and l[i] <= s.entry - pad:
                fill = i; break
            if ex.require_through:
                touched = (h[i] >= s.entry) if s.side == "short" else (l[i] <= s.entry)
                if touched:
                    missed_queue += 1
            # invalidated before it ever filled
            if s.side == "short" and h[i] > s.stop:
                break
            if s.side == "long" and l[i] < s.stop:
                break
        if fill is None:
            unfilled += 1
            continue

        risk = abs(s.entry - s.stop)
        cost_r = costs.cost_in_r(s.entry, s.stop)

        # ---- manage the position --------------------------------------
        out, exit_bar, exit_px = "timeout", min(fill + max_hold, n - 1), None
        for i in range(fill, min(fill + max_hold, n)):
            hit_stop = (h[i] >= s.stop) if s.side == "short" else (l[i] <= s.stop)
            hit_tgt = (l[i] <= s.target) if s.side == "short" else (h[i] >= s.target)
            if hit_stop:
                px = s.stop
                if ex.gap_stops and i > fill:
                    # a stop is a market order. If the bar opened beyond it,
                    # that gap is where you actually get out.
                    if s.side == "long" and o_[i] < s.stop:
                        px = o_[i]
                    elif s.side == "short" and o_[i] > s.stop:
                        px = o_[i]
                # both inside one bar: assume the stop. Pessimistic on purpose.
                out, exit_bar, exit_px = "loss", i, px
                break
            if hit_tgt:
                out, exit_bar, exit_px = "win", i, s.target
                break
        if exit_px is None:
            exit_px = float(df["close"].iloc[exit_bar])

        raw = (s.entry - exit_px) if s.side == "short" else (exit_px - s.entry)
        r = raw / risk - cost_r

        trades.append(Trade(
            entry_bar=fill, exit_bar=exit_bar,
            entry_time=idx[fill], exit_time=idx[exit_bar],
            side=s.side, entry=s.entry, stop=s.stop, target=s.target,
            exit_price=float(exit_px), outcome=out, r=float(r),
            rr_planned=float(s.rr), bars_held=int(exit_bar - fill),
            cost_r=float(cost_r),
        ))
        busy_until = exit_bar

    if missed_queue:
        run.last_missed_queue = missed_queue
    return trades, unfilled


def stats(trades, unfilled=0):
    """The numbers that actually decide whether this is worth running."""
    if not trades:
        return {"trades": 0, "note": "no trades"}
    r = np.array([t.r for t in trades])
    wins = r[r > 0]
    losses = r[r <= 0]

    # longest losing streak
    streak = worst = 0
    for x in r:
        streak = streak + 1 if x <= 0 else 0
        worst = max(worst, streak)

    eq = np.cumsum(r)
    peak = np.maximum.accumulate(eq)
    dd = float((peak - eq).max()) if len(eq) else 0.0

    # daily aggregation, since Chris cares about profitable DAYS
    dfm = pd.DataFrame({"t": [t.exit_time for t in trades], "r": r})
    daily = dfm.groupby(dfm["t"].dt.date)["r"].sum()

    return {
        "trades": len(trades),
        "cost_drag_R": round(float(np.mean([t.cost_r for t in trades])), 3),
        "unfilled_setups": unfilled,
        "win_rate": round(float((r > 0).mean()) * 100, 1),
        "avg_win_R": round(float(wins.mean()), 2) if len(wins) else 0.0,
        "avg_loss_R": round(float(losses.mean()), 2) if len(losses) else 0.0,
        "expectancy_R": round(float(r.mean()), 3),
        "total_R": round(float(r.sum()), 1),
        "profit_factor": round(float(wins.sum() / abs(losses.sum())), 2) if len(losses) and losses.sum() != 0 else None,
        "max_drawdown_R": round(dd, 1),
        "worst_losing_streak": int(worst),
        "trading_days": int(len(daily)),
        "profitable_days_pct": round(float((daily > 0).mean()) * 100, 1),
        "avg_bars_held": int(np.mean([t.bars_held for t in trades])),
    }


def to_frame(trades):
    return pd.DataFrame([asdict(t) for t in trades])
