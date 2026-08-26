# What the data says so far

Updated 2026-08-22. Every number here is out-of-sample unless it says otherwise.

## Headline

The method as taught **loses money on crypto** and **looks promising on futures**,
but the futures sample is far too small to trust. The blocker is data, not code.

## Crypto - BTC 5m, 2022-01 to 2026-08, 681 trades

| | train (426) | test (255) |
|---|---|---|
| win rate | 29.6% | 28.6% |
| expectancy | -0.380R | -0.414R |

Negative at every confluence threshold, on both halves. Three things were tested
and failed:

1. **Confluence stacking did not replicate.** On a 3-month sample it looked
   monotonic and turned positive at 3+. Over 4.6 years the gradient is noise.
   This is exactly why small samples must not be acted on.
2. **No time-of-day effect.** Correlation between train and test hourly
   expectancy was **+0.06**. The best hours on train were among the worst on
   test. Crypto has no sessions, and the method is built on session liquidity.
3. **Cost drag is fatal.** Crypto round-trip fees ran 0.4R+ per trade at tight
   stops. Phase 8's "3-10 pip" stop works on EURUSD because spreads there are a
   fraction of a pip.

### Which individual confluences carry weight (train, 426 trades)

| confluence | edge |
|---|---|
| real gap (a meaty imbalance) | +0.122R |
| engulfing candle at the break | +0.115R |
| higher timeframe agrees | +0.078R |
| 3+ touch pool | +0.009R |
| deep premium / discount | -0.055R |
| complex pullback | **-0.185R** |

The complex pullback rule is actively harmful here, which contradicts the course.

## Futures - NQ and ES 5m, 70 days, in-sample only

| | trades | win rate | expectancy | cost drag |
|---|---|---|---|---|
| NQ, min stop 0.05% | 58 | 37.9% | +0.189R | 0.06R |
| NQ, min stop 0.10% | 37 | 51.4% | +0.517R | 0.04R |
| ES, min stop 0.10% | 23 | 43.5% | +0.295R | 0.04R |

Positive, and cost drag is **ten times lower** than crypto. That is the single
biggest structural difference and it matches the theory: the method was designed
for this market.

**But 58 trades over 70 days proves nothing.** There is no out-of-sample split
because there is not enough data to make one.

## Why we cannot settle it yet

Free futures intraday data caps at **60 days of 5-minute bars**. The 2-year
hourly series produces only 2-16 setups per split - the method needs intraday
frequency - and shows the overfit signature: train positive, test negative.

## What would settle it

1. **Real-time and historical futures data, ~$10-15/month via Interactive
   Brokers.** This is now the gate on knowing whether the method works at all.
2. **Or free but slow:** collect Yahoo's rolling 60-day window daily and build
   history forward. Three months of collecting gives five months of data.

## Engineering notes

- `swings_known_at` originally copied the full swing prefix on every bar, making
  the backtest O(bars x swings). Bounded tails made it **43x faster** with
  identical output.
- The efficiency-of-the-pullback rule is redundant as coded: every setup scores
  0.93+ because requiring a sweep already implies the pullback reached the zone.
- Cost model: entry is a resting limit (maker), exit is taken (taker + slippage).
