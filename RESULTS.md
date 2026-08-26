# Where the system stands - 2026-08-22

## The strategy
ICT/SMC liquidity model from the two courses. Sweep a liquidity pool, wait for a
break of structure, enter on the fair value gap, stop beyond the sweep, target
the next draw on liquidity. New York window only (13:30-16:30 UTC).

Traded on EURUSD and Nasdaq (NSXUSD). 1,513 trades over 11.6 years.

## P&L at 1% risk per trade, compounded

| Start | Ends at | Worst dip |
|---|---|---|
| R20,000 | R116,000 | -R44,800 |
| R100,000 | R582,000 | -R224,000 |
| R400,000 | R2,327,000 | -R896,000 |

+16.4% a year. Nine winning years, two losing, one flat.

## THE PROBLEM: 38.5% max drawdown
Prop firms cap drawdown at 8-10%. Even at 0.25% risk per trade the strategy
breaches it. As it stands it fails every evaluation - not through bad trading,
but because the equity curve is too jagged for their rules.

## What fixes it, measured

### 4. TAKE PROFIT DISTANCE - the best lever by far
| max R:R | win% | CAGR | maxDD |
|---|---|---|---|
| **1.5** | **47.7%** | **+17.6%** | **27.1%** |
| 2.5 | 40.4% | +19.7% | 33.1% |
| 3.0 | 38.3% | +16.4% | 38.5% |
| 4.0 | 36.2% | +10.6% | 43.0% |

**Pulling the target in to 1.5R gives a HIGHER return AND a third less
drawdown**, and lifts the win rate from 38% to 48%. Bigger targets sounded
better and were worse: they miss more often, so losses cluster.

### 3. RISK SCALING - second best
after 2 losses -> 25% size:  +11.5% CAGR, 22.5% maxDD

### 2. MARKET SPLIT - modest but free
Monthly correlation between EURUSD and Nasdaq is **-0.03**, so the
diversification is genuine. Separate budgets: +7.9% CAGR, 22.4% maxDD.

### 1. MONTHLY STOP - the weakest
Stopping the month at -4%: +12.0% CAGR, 33.8% maxDD, 33 months sat out.
It cuts return without cutting drawdown much, because it fires after the damage.

### COMBINED
0.50% risk + monthly stop -3% + scale after 2 losses + market split:
**+3.3% CAGR, 8.1% maxDD** - the only combination under the prop limit, and the
return is poor.

## The honest conclusion
Two goals pull apart. Compounding your own capital wants 1.5R targets at 1% risk:
about +17%/yr with a 27% drawdown you must be able to sit through. Passing a prop
evaluation needs the drawdown under 10%, and everything that gets it there cuts
the return to roughly 3-4%.

## Caveat on every number here
Thresholds were chosen by looking at the same data they are measured on. Trust
the RANKING more than the exact figures. The cleanest evidence remains the
Nasdaq result, since that market was never touched during tuning.

## Next
- Re-run the year-by-year and the untouched-market validation at 1.5R
- Then paper trade it live to confirm the plumbing agrees with the backtest

---

# UPDATE - 1.5R targets, and dropping forex

## Portfolio comparison at 1.5R
| portfolio | CAGR @1% | maxDD | CAGR @0.5% | maxDD |
|---|---|---|---|---|
| EURUSD only | +7.3% | 27.1% | +3.7% | 14.4% |
| **NASDAQ only** | **+23.8%** | **10.3%** | **+11.5%** | **5.2%** |
| both | +17.6% | 27.1% | +8.7% | 14.4% |

**Forex was dragging the portfolio down.** Dropping it triples the return and
cuts drawdown from 27% to 10%.

At 0.5% risk, Nasdaq alone gives +11.5% a year with a 5.2% drawdown - inside
prop firm limits. That resolves the return-versus-evaluation tension.

## NASDAQ in money, 1% risk, over its 5 years
| start | ends | worst dip |
|---|---|---|
| R20,000 | R57,960 | -R5,943 |
| R100,000 | R289,799 | -R29,717 |
| R400,000 | R1,159,198 | -R118,869 |

## Is it real? Three checks, all passed
1. **Never tuned on.** Every setting was chosen on EURUSD. Nasdaq was untouched
   and performed BETTER: 52.8% win, +0.223R, 55.5% profitable days.
2. **Parameter sensitivity: 13/13 variations positive**, +0.177R to +0.252R.
   A fitted edge collapses when nudged. This one does not.
3. **Time stability: 9/10 six-month blocks positive**, worst -0.100R,
   5/5 calendar years positive.

## Remaining honest caveats
- Nasdaq has 5 years of data, EURUSD 11.6. The shorter sample may simply not
  have met its bad period yet, though 2022 was a bear market and it held.
- Nasdaq was CHOSEN after seeing it win, which is selection bias. The test that
  would settle it is whether the edge generalises to another index (SPXUSD).
  HistData's TLS certificate expired mid-session so that download is pending.
- All of this is backtest. Nothing has traded live.

---

# PAPER SYSTEM vs BACKTEST - the agreement check

Two separate code paths, identical data. If they disagree, one is wrong.

## Two real bugs this caught

**1. The drawdown gate was a silent permanent lockout.**
The risk gate hit its 10% drawdown cap, refused every subsequent trade, and
could never recover BECAUSE it was not trading. 733 silent refusals. It now
halts loudly and says so - which is the correct behaviour for a funded account,
but it must be visible rather than looking like a system that is still running.

**2. The backtest was understating futures costs fivefold.**
It charged costs as a PERCENTAGE OF NOTIONAL. Futures charge a fixed dollar
amount PER CONTRACT. The paper broker, which models it properly, disagreed by
0.13R a trade - and the paper broker was right. `Costs` now supports both
models, and futures use per-contract.

## Agreement after the fixes
| | trades | win% | expectancy |
|---|---|---|---|
| backtest | 494 | 52.8% | +0.215R |
| paper | 467 | 51.0% | +0.180R |

0.035R and 27 trades apart. The residual is expected: the paper system also
enforces a 5-trade daily cap and daily loss limits that the backtest does not.

**Paper result: +47.4% over 5 years at 0.5% risk on a R100,000 account.**

## Live mode
`run_live.bat` polls the feed and paper-trades the validated model. Verified it
runs. The free feed is delayed 10-15 minutes, so live mode proves the PLUMBING,
not the edge - a delayed feed cannot execute a 5-minute entry honestly.

CME reopens Sunday 18:00 ET (Monday 00:00 SAST). The NY window we trade is
13:30-16:30 UTC = 15:30-18:30 SAST.

---

# CORRECTION - the Nasdaq result was a data artefact

The decisive test: same period, same market, two data sources.

| instrument | bars | trades | win% | expectancy |
|---|---|---|---|---|
| NSXUSD (HistData CFD) | 333,459 | 494 | 52.8% | **+0.223R** |
| QQQ (Alpaca ETF) | 110,639 | 380 | 43.9% | **-0.004R** |

Daily return correlation between the two series: **+0.976** over 1,254 common
days. They are the same market. One shows a strong edge, the other shows
nothing.

**The edge does not survive on a genuinely tradeable instrument.**

## What the bars reveal
NSXUSD carries 3x the bars: it quotes nearly 24 hours a day, while QQQ trades
only 13:30-20:00 UTC. So NSXUSD was never the "cash session" instrument I had
assumed - that earlier hypothesis rested on a false premise about what it is.

Its bars are also quieter (mean range 0.096% vs QQQ's 0.122%) yet carry
proportionally MORE wick (wick/range 0.49 vs 0.40). A liquidity sweep in this
strategy is precisely a wick through a level that closes back. A synthetic
round-the-clock CFD feed with proportionally fatter wicks manufactures exactly
the pattern the strategy is looking for.

## What this costs us
The +23.8% CAGR / 10.3% drawdown headline is **not real and not tradeable**.
Every robustness check it passed - 13/13 parameter variations, 9/10 six-month
blocks, 5/5 years - was measuring a consistent artefact rather than a
consistent edge. Robustness testing confirms consistency; it cannot detect
that the underlying data is unrepresentative. Only a second independent source
can, which is what finally caught it.

## What survives
| test | trades | out-of-sample expectancy |
|---|---|---|
| QQQ 6.1 years | 380 | -0.004R |
| SPY 6.1 years | 202 | +0.122R (train was -0.092R, so inconsistent) |
| EURUSD NY window | 405 | +0.128R |

EURUSD is the only surviving positive, and it comes from the SAME VENDOR whose
index data just proved unrepresentative. It needs verifying against an
independent forex source before it is believed.

## The lesson worth keeping
A backtest can only ever be as honest as its data. Every statistical check we
ran was sound and every one of them passed on data that could not be traded.
The cheapest insurance against this is a second, independent data source, early.

---

# Six strategies tested on real exchange data

QQQ and SPY, 6.1 years of Alpaca data, train/test split, identical engine and
costs throughout. Only the entry logic differs.

## Out-of-sample expectancy
| strategy | QQQ test | SPY test |
|---|---|---|
| ICT (ours) | -0.027R | +0.122R |
| **opening range breakout** | **+0.043R** | **+0.050R** |
| mean reversion | -0.222R | -0.176R |
| VWAP reversion | -0.299R | -0.222R |
| moving-average pullback | -0.151R | -0.127R |
| previous-day fade | -0.207R | -0.163R |

## Is the best one real? No.
12 tests were run. With ~350 trades and an R standard deviation near 1.2, the
standard error is 0.064R, so a result must clear roughly **+0.126R** to be
distinguishable from zero.

The best observed is **+0.050R, which is 0.78 standard errors.**

Worse, the expected best-by-luck across 12 independent worthless strategies is
**+0.091R**. The best real result is SMALLER than what pure chance produces at
this sample size. There is nothing here.

## What IS a genuine finding
Every mean-reversion style approach - fading stretch, fading VWAP, fading the
previous day's extremes - loses money **consistently, on both instruments, on
both halves**, between -0.13R and -0.30R a trade. That consistency is far more
statistically solid than any of the positive results. On 5-minute index data
during New York hours, after costs, fading moves does not work.

## Two bugs found in the new code
1. No minimum stop distance, so a bar with a tiny range gave a tiny risk and
   dividing by it produced R multiples in the MILLIONS (-7,091,291R at one
   point). That is a divide-by-almost-zero, not a strategy result.
2. The opening range breakout initially produced ZERO setups: its stop sat
   1.25x the range away while its target was only 1x, so every single setup
   failed the minimum reward test silently.

---

## 2026-08-23  Execution realism, and a scale bug it exposed

Added queue-position and gap-stop modelling to the backtester. Both were
optimistic before: a limit order filled whenever price merely touched the
level, and a stop always filled at exactly the stop price.

QQQ, 447 trades, same setups throughout:

| execution assumption | trades | mean R |
|---|---|---|
| touch fills, stop fills at the stop (old) | 447 | -0.001R |
| price must trade through the level | 443 | -0.013R |
| plus stops that gap fill at the open | 443 | -0.060R |

Realistic execution costs **0.059R per trade**, and most of that is gapped
stops. This matters more than it looks: several earlier results sat between
0.00R and +0.05R, which is entirely inside this correction. Anything that
looked marginally positive under the old assumptions is negative under the
new ones.

The realistic model is now the default, so this cannot be forgotten.

### The bug it exposed

The first version expressed "trade through the level" as a fixed 0.01 tick.
That is one cent on a share and a hundred pips on EURUSD, so it removed every
single EURUSD fill and the evaluation reported zero trades rather than an
error. Now expressed as a fraction of the entry-to-stop distance, which means
the same thing at 1.08 and at 60,000.

Worth noting how it presented: not as a crash, but as a clean run reporting
"NO TRADES". A silent wrong answer is the failure mode to watch for.

## 2026-08-23  Wickiness threshold was wrong for FX

The data-quality check flagged EURUSD at 0.51 wick-to-range against a 0.46
threshold, implying the artefact pattern. It is not. Two independent vendors,
HistData and Dukascopy, both measured 0.51 on the same period. Spot FX is
quoted round the clock across venues, and thin hours leave long tails on
five-minute bars.

Thresholds are now per asset class: equity 0.46, index 0.46, crypto 0.52,
FX 0.56. The Nasdaq artefact still trips its own threshold, which was the
point of the check.

This is the second-source method working in the other direction: it was used
to convict NSXUSD, and here it acquits EURUSD.

## 2026-08-23  Regime breakdown on QQQ

Sliced 447 QQQ trades by volatility, trend, hour and day. The most tempting
slice was hour 15 UTC: +0.158R on 120 trades at a 50% win rate. It does not
survive being charged for the twenty-odd slices tested to find it, and neither
does anything else.

This is the expected result. Cutting a zero into pieces produces positive
pieces, and they are noise.

---

## 2026-08-23  EURUSD resolved: the closest thing to a signal, and still not one

Full evaluation, 11.6 years of HistData (821,013 bars, 2015 to 2026),
realistic execution, cross-checked against Dukascopy.

```
1. data quality    PASS   wick 0.511, normal for FX once the threshold was corrected
2. sample size     PASS   1,021 trades
3. significance    FAIL   +0.043R, 95% range -0.032 to +0.117R
4. walk-forward    PASS   5/6 folds positive out of sample, decay only +0.019R
5. second source   PASS   both vendors agree the recent period is negative
```

**Verdict: not an edge.** It fails on the check that matters most.

### Why walk-forward passing does not rescue it

Five of six folds positive with almost no train-to-test decay is a genuinely
good sign, and it is why this took a full day to resolve rather than an hour.
But walk-forward re-tunes on each fold, and choosing the best of six parameter
combinations per fold is itself a selection process. It answers "do the
settings generalise" and not "is the mean above zero". The mean is not.

### Year by year, which settles it

| year | trades | mean R |
|---|---|---|
| 2015 | 105 | +0.183 |
| 2016 | 99 | -0.176 |
| 2017 | 93 | -0.083 |
| 2018 | 95 | +0.126 |
| 2019 | 70 | +0.118 |
| 2020 | 94 | -0.014 |
| 2021 | 106 | -0.046 |
| 2022 | 93 | +0.253 |
| 2023 | 64 | +0.245 |
| 2024 | 85 | **-0.336** |
| 2025 | 104 | +0.201 |
| 2026 | 13 | +0.312 |

2024 and 2025 are adjacent years with opposite signs at large magnitude. A real
edge of +0.04R does not produce a -0.34R year in ninety trades; a coin flip
does. With roughly 90 trades a year the standard error on each of these is
about 0.11R, and the spread is what that predicts.

Six positive years and six weak or negative ones is a description of noise.

### What the second source added

Over the 2024-2025 overlap, HistData gives -0.040R and Dukascopy -0.149R. They
disagree by 0.109R, which is more than the whole claimed effect. Both are
negative. Whatever was there in 2022-2023 is not there now, on either feed.

### The standing position after this

Every market tested has now returned the same answer:

| tested | trades | result |
|---|---|---|
| Crypto | 681 | no edge |
| Nasdaq index | 494 | data artefact |
| QQQ / SPY | 447+ | no edge, and negative under realistic fills |
| Six alternative strategies | 12 tests | all below the luck threshold |
| EURUSD | 1,021 | no edge, though it came closest |

Five markets, eleven years, several thousand trades, and one consistent
answer. That answer is worth more than a number that would have felt better.

---

## 2026-08-23  The course confluences, tested properly

Chris asked for every combination of the course confluences tried, TJR's
material used intensely, and the highest-probability trades found. Four of his
videos were re-watched for this, including him trading live in front of a
student, which is better evidence than the teaching segments because it shows
what he reaches for under pressure.

### What was added to the engine

Three concepts from the videos that were missing entirely:

| added | source |
|---|---|
| SMT divergence (QQQ against SPY) | his signature confluence, 20+ mentions |
| Inverse fair value gap | the single most-used term across the videos, 51 mentions |
| London session highs and lows | he names them constantly; only Asia existed |

And one bug fixed: the higher-timeframe bias was reading the hourly candle
still in progress, whose high and low contain five-minute bars that have not
happened yet. Small, but that is the exact mechanism behind the Nasdaq result.

### The replication table, which is the whole point

Everything was tested on QQQ and then on EURUSD, a market it was not found on.

| confluence | QQQ | EURUSD | holds up |
|---|---|---|---|
| higher timeframe agrees | +0.189R | +0.181R | **yes** |
| complex pullback | +0.099R | +0.114R | **yes** |
| deep premium/discount | +0.288R | -0.188R | no, flips |
| engulfing entry candle | -0.150R | +0.269R | no, flips |
| pool touched 3+ times | -0.030R | +0.217R | no, flips |
| session levels used | -0.169R | +0.096R | no, flips |
| inverse fair value gap | -0.273R | +0.041R | no, flips |

Two of seven survive. The rest describe the market they were measured on.

### The confluence stack does not stack

On QQQ, requiring more confluences looked excellent: win rate climbed 39, 42,
45, 51 percent as the requirement rose from three to six. A smooth climb, not
one lucky bucket.

On EURUSD the same test is flat and then falls: 45.7, 45.6, 46.0, 46.2, 41.6,
42.4. The climb was a QQQ fact, not a market fact.

### Every combination, as asked

335 combinations of filters and required confluences, searched on the first 60%
of QQQ history with the last 40% held back untouched.

```
best on the search data      +0.174R over 100 trades
same rules, held-out data    -0.131R over  61 trades
same rules, EURUSD           -0.040R over 331 trades
```

Every one of the 335 was already below the +0.424R that luck produces across a
search that size. The best one then lost 0.305R when applied to data it had not
been fitted to. That is what a large search does to noise.

### Two more of his specifics

**1:3 reward to risk.** He states it on the winning trade. Tested: 1.5:1 gives
-0.005R at a 44% win rate, 3:1 gives -0.053R at 33%. The wider target loses
more than it gains here.

**His session times.** "1800 to 3 is Asia. 3 to 8:30 London. 8:30 back to 1800
is New York." The engine only ever traded 09:30 to 12:30. His New York open
window is worth +0.157R over the engine's on QQQ. On EURUSD the engine's window
is better. Another one that does not replicate, though London on EURUSD gives
+0.073R over 1,341 trades and is at least well-populated.

### What he says himself

Worth recording, because it is the most relevant sentence in six hours of video:

> "if we wanted to just make some sort of trading bot that automated our
> strategy ... and if that strategy actually gave us like 100% profitable
> results over a long period of time, then awesome. Everybody would be able to
> get rich."

And on why he refuses to give a step-by-step: he wants room for discretion
built on years of screen time. The engine is a faithful implementation of the
sequence he describes. The part he says makes it work is the part that cannot
be written down.

### Standing position, unchanged

Two confluences replicate: higher-timeframe agreement and the complex pullback.
Both are worth keeping. Neither is large enough, alone or together, to turn a
negative expectancy positive. Nothing has cleared evaluate.py.

---

## 2026-08-23  The risk question, which turns out to be the whole answer

Chris asked what happens if we use more risk, looking for the highest
probability route to extra income. This is the most useful analysis in the
project, because it answers the actual goal directly rather than another
variant of "is this strategy any good".

### Why this study is safe when the strategy searches were not

Searching for a better strategy tests many hypotheses, and each one raises the
bar a result must clear. That is why 335 combinations produced nothing.

Risk sizing is not a search. It does not change expectancy at all. A strategy
worth +0.14R per trade is worth +0.14R at any risk level. What risk changes is
the shape: how wide the range gets and how deep the drawdowns go. There is a
definite answer, and it does not depend on testing more ideas.

### EURUSD at the best settings found (1:3 minimum, +0.141R, 375 trades)

| risk per trade | median return | median drawdown | chance of blowing a 10% limit |
|---|---|---|---|
| 0.10% | +5.7% | 2.6% | 0.0% |
| 0.25% | +14.4% | 6.5% | 11.9% |
| 0.50% | +29.7% | 12.6% | **77.0%** |
| 1.00% | +62.1% | 24.1% | **100%** |
| 2.00% | +126.8% | 43.8% | **100%** |

The largest risk that keeps 95% of paths inside a 10% drawdown is **0.208%**.

### What that is worth

At 0.208% risk, 32 trades a year, +0.141R per trade:

| account | per year, IF the edge is real |
|---|---|
| $25,000 | $237 |
| $50,000 | $473 |
| $100,000 | $947 |

That is the honest number. Roughly $950 a year on a hundred thousand dollars,
conditional on an edge that has not passed its own significance test.

### Why raising risk cannot fix it

Return and drawdown rise together in a fixed ratio. Doubling risk doubles the
expected return and doubles the drawdown. It never improves the odds of
finishing up: 92.0% at 0.1% risk, 86.1% at 2%, 71.4% at 5%. Higher risk makes
the outcome worse, not better, because ruin is absorbing and gains are not.

The deeper reason this strategy cannot carry size: at a 27% win rate with 3:1
targets, the median worst losing streak is 15 trades and the 95th percentile is
23. Surviving a 23-trade losing run inside a 10% limit forces risk down to
roughly 0.2%, and 0.2% of anything is not income.

### QQQ, for comparison

Negative expectancy, so the table only shows how much faster the account dies.
Chance of finishing up: 15.3% at 0.1% risk, falling from there. 80.8% chance of
blowing a 10% limit at 0.5% risk.

### The conclusion this forces

There is no risk setting that turns this into income. The constraint is not
courage or position sizing. It is that the edge, if it exists at all, is far too
small relative to its losing streaks to carry meaningful size.

## 2026-08-23  The 1:3 minimum, evaluated properly

Chris's idea, and the best one anyone has had here. It genuinely improves the
EURUSD result: +0.063R at 1.5:1 (44.7% win against 44.4% needed, a coin flip)
becomes +0.141R at 3:1 (27.5% win against 20.0% needed, real margin).

It still fails.

```
1. data quality    PASS
2. sample size     PASS   375 trades
3. significance    FAIL   +0.141R, 95% range -0.064 to +0.346R, needs +0.205R
4. walk-forward    FAIL   2 of 6 folds positive out of sample
5. second source   PASS   both vendors negative over the recent overlap
```

The folds swing from -0.279R to +0.473R. Train mean +0.154R decays to +0.023R
out of sample. That spread is noise.

A bug worth recording: the first run of this reported walk-forward as failed
when the tuning grid was offering reward targets of 1.5 and 2.0 while the config
demanded a 3.0 minimum. Every fold produced zero setups, and "nothing was
tested" printed identically to "everything failed". Fixed so the grid respects
the configured minimum.

---

## 2026-08-23  Slower timeframes: the mechanism was right, the cure is not

The BTC fee discovery suggested slowing down, because costs are a fixed share of
notional while risk is the stop distance. Wider stops mean less drag. Tested on
7.6 years of BTC (803,166 five-minute bars from Binance), 11.6 years of EURUSD,
and 6.1 years of QQQ.

### The cost burden is wildly different per market

At the same 0.05% stop:

| market | cost per trade |
|---|---|
| EURUSD | 0.032R |
| QQQ | 0.200R |
| BTC | 1.200R |

So the idea could only ever have helped BTC. On EURUSD, moving from five-minute
to four-hour saved 0.005R. There was nothing there to recover.

### On BTC the mechanism is confirmed almost exactly

| timeframe | trades | mean R | cost saved vs 5min | unexplained |
|---|---|---|---|---|
| 5min | 3,979 | -0.453 | | |
| 15min | 1,231 | -0.331 | +0.127 | **-0.005** |
| 30min | 519 | -0.061 | +0.204 | +0.188 |
| 1h | 232 | -0.283 | +0.244 | -0.075 |
| 2h | 104 | -0.284 | +0.208 | -0.040 |
| 4h | 42 | -0.273 | +0.257 | -0.530 |

The five-to-fifteen-minute step is the clean one: expectancy improved +0.122R
and the cost saving was +0.127R. The improvement is the cost saving, to within
five thousandths of an R. That is as direct a confirmation of a mechanism as
this project has produced.

### And it does not save the strategy

Removing the entire cost burden moves BTC from -0.453R to -0.061R at its best.
It never reaches positive. Past thirty minutes the improvement reverses and the
sample falls apart.

The BTC result is now the most statistically solid finding in the project, and
it is a negative one:

```
5min   n=3,979   95% range -0.550 to -0.355R   entirely below zero
15min  n=1,231   95% range -0.507 to -0.155R   entirely below zero
```

Most results here have been "not distinguishable from zero". This one is
distinguishable, and it is distinguishably bad.

### Slowing down costs sample faster than it saves money

| market | timeframe | mean R | trades | 95% range |
|---|---|---|---|---|
| EURUSD | 4h | +0.133R | 69 | -0.560 to +0.825R |
| QQQ | 2h | +0.455R | 34 | far wider still |

Both look excellent and mean nothing. There is a practical problem too: 69
trades over 11.6 years is five a year. At the 0.2% risk that survives a
drawdown limit, five trades a year is not income, and it is not day trading.

### What this closes

Costs were a genuine bug and worth finding. Fixing them does not produce an
edge; it just stops one particular way of manufacturing a loss. The strategy is
negative on BTC with high confidence, indistinguishable from zero on EURUSD and
QQQ, and slowing down does not change any of that.

---

## 2026-08-23  Entry placement, equilibrium, and a filter that does nothing

Chris pushed on where stops and targets go, and on watching the video rather
than inventing placements. Both were right, and both changed what got built.

### The efficiency filter has never filtered anything

`min_efficiency = 0.80` is described in the code as a non-negotiable. Varying it
on EURUSD:

| requirement | trades | mean R |
|---|---|---|
| none | 221 | +0.170R |
| 50% | 221 | +0.170R |
| 62% | 221 | +0.170R |
| 70% | 221 | +0.170R |
| 80% | 221 | +0.170R |
| 90% | 220 | +0.156R |

Identical to five decimal places until 90%, where it removes a single trade.
The pullback in these setups always retraces past 80% anyway, so the filter has
never excluded anything. The scored tag told the same story earlier and was not
followed up: `full_efficiency` fires on 99.5% of setups.

A setting can look like a rule, be documented as a rule, and be a no-op.

### Stop and target placement was already right

Sixteen combinations of structural stop and target, same entries throughout:

| stop at | target at | trades | mean R | win % |
|---|---|---|---|---|
| swept extreme | draw on liquidity | 421 | **+0.117** | 36.8 |
| swept extreme | opposite swing | 165 | +0.078 | 53.3 |
| session level | opposite swing | 181 | +0.098 | 53.6 |
| internal swing | stacked liquidity | 368 | -0.384 | 13.9 |

The engine's existing choice wins. Held out it gives +0.021R, under the +0.202R
luck line for sixteen tries, so there is nothing to claim, but there is also
nothing to improve.

The first version of this study tested two times risk, three times risk, and an
ATR multiple. Chris pointed out that neither course teaches distances, they
teach locations. He was right and the study was rebuilt around real highs and
lows.

### The inverse gap is an ENTRY, not a filter

This was the biggest misreading. It was tested as "does an inverted gap agree
with this trade", which fired on 100% of setups and meant nothing. What TJR
actually does:

> "This makes my stop loss literally two times the size and now makes me have a
> risk-to-reward that's not even 1:0.5 ... versus if I take this trade up here,
> if I'm risking $1,000, I'll be able to make $1,300."

> "I use this confluence almost every single day, almost more than break of
> structure, because more often than not it happens before break of structure."

He enters at the inverted gap instead of waiting for the break of structure.
Same idea, same target, earlier entry, smaller stop.

Built as `entry_mode`, and the mechanism is real on both markets:

| market | entry at | stop % | trades | mean R | total R |
|---|---|---|---|---|---|
| EURUSD | break of structure | 0.1186 | 695 | +0.077 | +53.8 |
| EURUSD | inverse gap | **0.1066** | 1,832 | +0.051 | **+94.2** |
| EURUSD | equilibrium | 0.1103 | 806 | +0.031 | +25.1 |
| QQQ | break of structure | 0.2339 | 204 | -0.100 | -20.4 |
| QQQ | inverse gap | **0.2201** | 619 | -0.132 | -82.0 |
| QQQ | equilibrium | 0.1998 | 274 | -0.195 | -53.5 |

The stop shrinks on both, by 10 to 15%. Not the halving he describes, but real
and in the right direction.

It does not become an edge. On EURUSD the earlier entry trades 2.6x more often
for a lower per-trade result, which nets more total R. On QQQ every alternative
entry is worse than the original. Another non-replication.

An earlier tightening step mattered: the first version allowed any inversion in
the last 40 bars and produced 9,651 setups at -0.189R. Requiring the inversion
to have happened on the previous bar cut that to 3,465 setups at +0.051R. He
watches one specific gap, not any gap in the neighbourhood.

### Equilibrium, his other continuation confluence

Implemented from his definition, including how he insists it is drawn: "the
most recent low to the most recent high". He separates his confluences into
confirmation (break of structure, inverse gap) and continuation (fair value
gap, equilibrium). The engine only ever implemented the fair value gap side, so
equilibrium was a genuine gap in coverage rather than another variant.

As an entry it is the weakest of the four on both markets.

### Mean reversion, retested fairly

Every parameter combination negative. Best held out at -0.187R over 2,537
trades, 95% range -0.244 to -0.131R, entirely below zero. EURUSD confirmation
-0.054R over 6,449 trades.

A prediction of mine was wrong and worth recording. The old mean-reversion test
demanded a 1R minimum reward, and mean reversion targets the mean, which is
usually nearer than that. I expected the floor to be rejecting most setups and
crippling the result. It was not: dropping the floor from 1.0 to 0.3 moved the
trade count from 29,590 to 29,619. Twenty-nine trades out of thirty thousand.
The old result was right and my explanation for it was invented.

---

## 2026-08-23  The efficiency filter, fixed

It was a no-op. Now it works, and the reason it was broken is instructive.

### What was wrong

```python
seg_h = high[since_bar:bar + 1]
reached = seg_h.max()
```

`since_bar` sits thirty bars BEFORE the sweep. So the highest high in that
window was the sweep spike itself, and a sweep exceeds its level by definition.
The ratio was therefore always at or above 1.0, and every threshold from 50% to
80% passed everything. Identical trade counts, identical expectancy, to five
decimal places.

The filter is described in the code as one of "the course's non-negotiables".
It had never once refused a setup.

### What it should measure

The pullback is the retrace AFTER the impulse, not the whole window:

```
sweep      price spikes through the level
impulse    price drops away from it
pullback   price climbs back toward the sweep  <- this is what to measure
```

Efficiency is now (pullback reach - impulse extreme) over (sweep extreme -
impulse extreme). A 50% retrace reads 0.5, a 90% retrace reads 0.9.

### It filters now

EURUSD trade counts by threshold: 697, 569, 218, 113, 80, 66, 55 as the
requirement climbs from none to 90%. It binds.

| market | no requirement | at 50% |
|---|---|---|
| EURUSD | +0.074R | +0.198R |
| QQQ | -0.100R | -0.024R |

Both markets improve at 50% and both degrade above 70%, in the same direction,
which is what replication looks like. And 50% is equilibrium, the number TJR
emphasises, which is a satisfying convergence.

### It still does not survive

| market | training | held out |
|---|---|---|
| EURUSD at 50% | +0.307R | -0.066R |
| QQQ at 50% | +0.296R | -0.408R |

Strongly positive in training, negative out of sample, on both markets. The
classic shape.

Worth noting the baseline does the same thing: EURUSD with no requirement goes
+0.108R to -0.014R, QQQ +0.071R to -0.298R. The later 40% of history is worse
for this strategy across the board, which matches the earlier finding that
2024-25 was negative on both EURUSD vendors. The filter is not the problem; the
strategy stopped working.

### The default

`require_efficiency` is now False. Leaving it True at 0.80 would silently
remove about 90% of setups the moment the maths was corrected, which is a large
behavioural change nobody validated. No threshold survived a train/test split,
so switching it on would be choosing a number because it flattered the past.

A broken filter is now a working one, and it is off. That is the honest state.

---

## 2026-08-23  What changed around 2023: nothing. And the reason why.

I claimed the strategy "stopped working somewhere around 2023". That claim was
wrong, and testing it properly produced the most important finding in the
project.

### There was no break

EURUSD, year by year, expectancy: +0.014, -0.190, -0.026, +0.447, +0.227,
+0.187, -0.017, +0.254, +0.168, -0.199, -0.033.

Six positive years, five negative, no trend. The year-to-year spread is
**0.199R**. The gap between the two halves that started this whole question is
**0.034R**.

The ordinary yearly swing is six times larger than the "break". It was noise
with a convenient split point, and I read a story into it.

### The data did not change either

EURUSD wick-to-range by year: 0.509, 0.509, 0.513, 0.511, 0.515, 0.510, 0.503,
0.515, 0.510, 0.508, 0.516. Dukascopy over the same recent years: 0.507, 0.509.
Two vendors, eleven years, flat.

### Correlated markets disagree with each other

QQQ and SPY track overlapping baskets of the same US large caps. If a regime had
shifted, they would shift together.

| year | QQQ | SPY |
|---|---|---|
| 2022 | +0.022R | -0.429R |
| 2023 | +0.042R | +0.055R |
| 2024 | -0.372R | -0.371R |
| 2025 | -0.279R | **+0.593R** |

SPY's best year is QQQ's second worst. That is not a market regime. That is two
draws from the same noisy distribution.

### The finding underneath everything

Strip the strategy away entirely and ask the only question that matters: after
price sweeps a swing high, does it reverse?

EURUSD, roughly 9,500 sweeps a year:

```
2015  51.3%    2019  51.3%    2023  51.2%
2016  51.5%    2020  51.1%    2024  50.9%
2017  51.9%    2021  51.7%    2025  51.2%
2018  51.4%    2022  50.8%
```

**51%.** Eleven years, about 100,000 sweeps, and the number does not move by
more than one percentage point.

The entire system is built on an event that beats a coin flip by one point in a
hundred. Costs are larger than that on every market tested. No arrangement of
confluences can amplify a 51/49 edge into something tradeable, which is why
none of them did, and why the failures were so consistent across markets,
timeframes, parameters and rule combinations.

Everything else was decoration on a coin flip.

### BTC is the one place with a genuine fade

| year | sweeps reversed |
|---|---|
| 2019 | 55.7% |
| 2020 | 55.5% |
| 2021 | 53.1% |
| 2022 | 53.7% |
| 2023 | 53.5% |
| 2024 | 52.3% |
| 2025 | 51.5% |

That is a real decay, from 55.7% to 51.5%, converging on the same 51% as spot
FX. Crypto in 2019 did carry a small structural inefficiency after sweeps, and
it has been arbitraged away as the market matured. Even at its best, 55.7% was
not enough to cover a 1.2R cost burden, which is why the BTC result was
negative throughout.

### What this closes

The question was never which confluence, which market, which timeframe or which
risk setting. The premise is that a liquidity sweep predicts reversal. Measured
directly, without a strategy in the way, it predicts reversal 51% of the time.

That is the answer, and it took stripping the strategy off to see it.

---

## 2026-08-23  A genuinely different idea, and the first partial success

Everything before this was one idea in different clothes: a liquidity sweep
predicts reversal, measured at 51%. These were chosen for having a documented
mechanism rather than a shape, and for being SLOW, since the cost burden that
destroyed the five-minute results becomes a rounding error over weeks.

### The benchmark correction that mattered

The first run measured these against zero. That is wrong for a long-only rule
in a rising market: SPY returned 17% a year over the sample, so almost anything
long-only looks good. Every figure below is measured against buy and hold.

### What failed

**Overnight drift.** The documented effect is that equity returns accrue
between the close and the next open. Measured on SPY: overnight +8.70% at 9.67%
volatility, intraday +8.40% at 14.24%. Overnight does carry the better ratio,
but its Sharpe of 0.90 is BELOW buy and hold's 1.02. It only beat holding in the
recent half, which is a period effect rather than an edge.

**Turn of month.** Sharpe 0.37 against 0.90 for the rest of the month. The
opposite of the claim.

**Day of week.** Included as a control, expected to fail, and it produced
exactly the trap it was there to catch: Monday showed a Sharpe of 1.42 on 283
observations. A spurious result that would have looked wonderful in isolation.

**An artefact worth recording.** Bitcoin's "overnight" return showed a Sharpe of
1.20 out of sample. Its volatility is 0.0090% against 3.2250% intraday, because
crypto never closes and the daily open equals the previous close. It was a
resampling ghost, not a result.

### What partially worked

Trend following. Long when the trailing return is positive, else flat.

| market | best excess Sharpe over holding |
|---|---|
| SPY | +0.01 |
| QQQ | +0.13 |
| EURUSD | +0.05 |
| **Bitcoin** | **+0.51** |

On the equal-weighted basket, a 40-day lookback chosen on the first 60% of
history and applied once to the last 40%:

```
HELD OUT   trend Sharpe +0.84   hold Sharpe +0.63   excess +0.21
           trend drawdown 18.5%   hold drawdown 36.5%
```

That is the first result in this project to beat its own benchmark on data it
was not chosen on.

### And the check that cut it down

Trend following's actual claim is diversification: uncorrelated trends across
many markets add up to something smoother than any one of them. Tested by
removing a single market:

| basket | trend | hold | excess |
|---|---|---|---|
| all four | +0.84 | +0.63 | **+0.21** |
| without Bitcoin | +0.64 | +0.83 | **-0.19** |
| Bitcoin alone | +0.82 | +0.43 | **+0.38** |

Remove one market and the result inverts. The diversification claim is false
here. It was a single-market Bitcoin result wearing a basket costume, and the
basket framing made it look more robust than it was.

### Where that leaves it

Bitcoin trend following is the most promising thing found in the project. It
has decades of literature behind it, it held out of sample, and it roughly
halves the drawdown (66.7% down to 42.9%) which is the part of trend following
that replicates most reliably in the published work.

But it is ONE market. Seven and a half years of one asset is a handful of
independent trends, not thousands of independent trades, and six lookbacks were
tested to find it. A proper test of the diversification claim needs twenty or
more markets across asset classes, which is more data than this project holds.

It is not an edge yet. It is the first thing that has earned a proper
evaluation rather than a dismissal.

---

## 2026-08-23  THE FIRST VALIDATED RESULT

After a week of negatives, one configuration clears every check.

```
EURUSD, 5-minute, London + New York sessions
sweep -> break of structure -> entry at the fair value gap
0.5R target, htf bias on, real draw required, premium required

  +0.147R per trade over 788 trades
  74% win rate, worst losing streak 4 (6 at the 95th percentile)
  0.98% risk keeps 95% of paths inside a 10% drawdown
```

| check | result |
|---|---|
| data quality | PASS  wick 0.511, normal for spot FX |
| sample size | PASS  788 trades |
| significance | PASS  95% range +0.104 to +0.190R, entirely above zero |
| walk-forward | PASS  6 of 6 folds positive out of sample |
| second source | PASS  +0.104R and +0.058R, agreeing within 0.046R over 5 years |

### It survives the harshest correction available

The run charged one hypothesis because the ledger was reset. The project
actually tested 516 configurations: 335 confluence combinations, 57 confluence
studies, 48 mean-reversion parameters, 21 timeframe tests, 17 structure widths,
16 placements, and the rest.

Charged for all 516, the expected-best-by-luck bar is **+0.068R**. The result is
**+0.147R**, more than double it.

### Why it took three bug fixes to trust

The first time this configuration reported "all five checks passed", the pass
was worthless, and finding out why was the most valuable hour of the project.

**The walk-forward tested a different strategy.** Its parameter grid offered
targets of 1.5R to 5R while the config demanded 0.5R, so every fold silently
validated something else and passed on that. Fixed: the grid is now centred on
the configured target.

**The second-source check was a no-op.** It passed whenever `--compare` was
supplied and never compared anything. This is the check that caught the Nasdaq
artefact, and it caught it only because the numbers were read by eye. It had
never once fired. Fixed: it now requires agreement.

**Then the fix over-corrected.** It treated opposite signs as contradiction,
when on 77 trades the gap was 0.90 standard errors, which is not disagreement
but low power. Fixed: it now reports three states, and low power is a distinct
verdict from a contradiction.

Three bugs, each of which would have let a false positive through, all found by
refusing to accept good news.

### What resolved the fifth check

Not a code change. More data. Extending Dukascopy from 2 years to 5 took the
comparison from 77 overlapping trades to 183, and the verdict from
"underpowered" to "sources agree". The check was right to withhold judgement.

### What it is worth

At 0.98% risk, roughly **$500 a month on $50,000**, about 10-12% a year.

That is a real edge. It is also not $1,500 a day, and the distance between those
two numbers was never something more testing could close.

### Standing caveats

Backtested, not live. The paper account has traded nothing yet. Fills assume
price must trade through a level and stops gap to the open, which is
pessimistic, but real execution will still differ. One market. And a 74% win
rate with a 0.5R target means the losses are twice the size of the wins, so it
will feel worse to trade than the numbers suggest.

---

## 2026-08-23  THE ARTEFACT WAS MY DATA, NOT THEIRS

The headline finding of this project was wrong. It is worth writing up carefully
because the error is more instructive than the original claim.

### What was claimed

NSXUSD produced +0.223R and 23.8% a year. It was declared a data artefact
because it carried wick-to-range of 0.536 against QQQ's 0.416 over the same
period, and the strategy enters on wicks through levels. The conclusion:
a synthetic CFD manufacturing the exact pattern being hunted.

### What is actually true

| feed | wick / range |
|---|---|
| QQQ, Alpaca free tier (IEX only) | 0.457 |
| QQQ, Yahoo (consolidated tape) | 0.526 |
| NQ futures, real exchange | 0.538 |
| NSXUSD, the "artefact" | 0.536 |
| Dukascopy Nasdaq CFD | 0.571 |

NSXUSD sits within two thousandths of real exchange-traded NQ futures. It was
never manufactured. **The anomalous feed was QQQ**, because Alpaca's free tier
serves IEX only, a small slice of US volume, and fewer prints per bar means
fewer extremes.

### The measurement that settles it

Same symbol, same sixty days, same strategy, two feeds:

```
QQQ from Yahoo, consolidated tape    35 trades   +0.005R   71.4% win
QQQ from Alpaca free, IEX only       44 trades   -0.206R   56.8% win
```

**0.211R and fifteen points of win rate, from the data source alone.** A feed
that under-reports extremes systematically misreports the sweeps this strategy
trades. It is the same failure mode as the original diagnosis, pointed the
other way.

### What this invalidates

Every US equity result in this project was measured on the IEX feed:
QQQ -0.190R, SPY -0.139R, IWM -0.170R, DIA -0.263R, and the multi-market study
that concluded "only EURUSD works". All suspect.

The wick thresholds in `data/quality.py` were also calibrated on it. A limit of
0.46 for equities and indices would flag real NQ futures as manufactured.
Recalibrated to 0.58 and 0.60 against complete feeds.

### What survives

The EURUSD validated result. HistData and Dukascopy are both full FX feeds and
were cross-checked against each other. Unaffected.

### The lesson, which is not the one I drew the first time

The original write-up said: robustness testing confirms consistency but cannot
detect unrepresentative data, so use a second source. That is right, and it is
incomplete. A second source only helps if you ask **which** of the two is wrong.
I had two feeds disagreeing, assumed the cheap free one was the truth, and
condemned the other. The correct question was never "do they differ" but "which
one matches reality", and answering it needed a third reference: real exchange
futures.

Both times the strategy read the feed correctly. Both times I read the feed
comparison wrong.

---

## 2026-08-24  The 1-minute rebuild, and TJR's windows measured

Chris supplied a live trading video and the course guide and asked for the
method implemented as written. Reading it properly found four gaps between the
guide and the engine, three of which were real defects.

### The gaps

**The engine only ever used one timeframe.** The guide uses three: 4-hour for
bias, 5-minute for the confirmation close, 1-minute for the entry. Running
everything on five minutes collapses the last two and loses the reason the
third exists, which is the stop. The same structure on a 1-minute chart is a
fifth the size, so an identical trade carries far less risk.

Measured: stop falls from 0.206% to 0.054% on the same setups. And the engine
found NO setup on a day a 1-minute read found two, one of which was a trade
Chris took himself for +$1,383.

Built as `engine/multiframe.py`.

**Step 3 accepted a fair value gap only.** The guide gives the gap OR
equilibrium as alternatives. Roughly half the valid entries were invisible.
Added as `entry_mode="tjr"`.

**No manipulation window, no cutoff.** The guide says watch 09:30-09:50 and
stop by 10:30. Neither existed.

**The higher timeframe was one hour, not four.** Tested rather than assumed.

### Trade count was the whole story

| timeframe | trades/yr | expectancy | $/month on $50k |
|---|---|---|---|
| 5-minute | 175 | +0.167R | $1,823 |
| 1-minute | 1,324 | +0.086R | $2,932 |

Eight times the trades at half the edge is worth 60% more. The edge per trade
went DOWN and the income went UP, which is the same lever as the session work
and points the same way: frequency was the term with headroom.

### His windows, measured on 1-minute, held out

| window | trades/yr | expectancy | $/month |
|---|---|---|---|
| PM session 13:00-16:00 | 563 | **+0.100R** | $1,904 |
| London 03:00-08:30 | 847 | +0.085R | $1,693 |
| NY open 09:30-10:30 | 209 | +0.084R | $583 |
| his entry window 09:50-10:30 | 121 | +0.050R | $172 |
| NY premarket 08:30-09:30 | 169 | +0.043R | $191 |
| Asia 18:00-03:00 | 840 | +0.007R | $49 |

**His signature window is second from bottom.** The 09:50-10:30 slot the whole
four-step sequence builds toward returns +0.050R. The PM session he explicitly
says he does not trade is the best window in the day.

**The manipulation rule costs money.** Trading 09:30-10:30 gives +0.084R;
excluding the first twenty minutes as instructed drops it to +0.050R. Confirmed
on both timeframes.

The fair reading is that he trades one window because he is a person in a
timezone with a stream to run. The structure works across all of them; his
window selection optimises his day, not the return.

### Combinations

| combination | trades/yr | expectancy | $/month |
|---|---|---|---|
| London + full NY | 2,175 | +0.085R | **$4,232** |
| his windows minus Asia | 1,816 | +0.081R | $3,269 |
| London + PM only | 1,410 | +0.091R | $3,130 |
| every window incl. Asia | 2,676 | +0.058R | $2,512 |

Expectancy across the top three is +0.081 to +0.091, which is the same number.
What separates them is trade count. The one large consistent effect is that
**Asia dilutes**: removing it alone is worth 30%.

### Reward target, settled twice

| target | win rate | expectancy | $/month |
|---|---|---|---|
| 0.5R | 77.4% | +0.086R | **$2,932** |
| 1.0R | 58.6% | +0.093R | $1,478 |
| 1.5R | 45.2% | +0.035R | $209 |
| 2.0R | 38.1% | +0.001R | $3 |

Wide targets decay to nothing on 1-minute exactly as they did on 5-minute. Two
independent timeframes, same answer.

Note the 1.0R row: highest expectancy, half the income, because a 58.6% win
rate produces longer losing streaks and halves the survivable risk.

### The caveat that governs all of it

Every figure above is measured on NSXUSD, the Nasdaq CASH INDEX. Not the
futures contract, not even a CFD on it. Three different things were being
called "Nasdaq" in this project:

    NSXUSD   cash index, untradeable, where every 1-minute result lives
    QQQ      an ETF, 6.5 hours, per-notional costs
    NQ=F     the actual contract, 23 hours, per-contract costs, ten weeks held

The second-source check on NSXUSD has not run. Until it does, none of this is
established.
