# Where this stands, and what to do next

Rewritten 2026-08-23, after EURUSD resolved and the build finished.

---

## The honest position

The system is finished and it works. It has caught its own bugs four times,
refused trades the account could not carry, detected a data artefact that had
passed thirteen robustness checks, and now measures its own execution
assumptions rather than assuming them.

It has not found an edge, on any market tested.

| tested | trades | result |
|---|---|---|
| Crypto | 681 | no edge |
| Nasdaq index (NSXUSD) | 494 | data artefact, caught by the second-source check |
| QQQ and SPY, real exchange data | 447+ | no edge, negative under realistic fills |
| Six alternative strategies | 12 tests | all below the expected-best-by-luck bar |
| EURUSD, 11.6 years, two vendors | 1,021 | no edge, came closest, fails significance |

That is a real finding, arrived at cheaply, on paper, with nobody's money at
risk. It is what the project was for.

---

## What was built (all done)

| piece | what it does |
|---|---|
| `evaluate.py` | six guardrails, refuses to call anything an edge unless all pass |
| `backtest/guard.py` | confidence intervals, Sidak correction, hypothesis ledger |
| `data/quality.py` | catches manufactured feeds; thresholds per asset class |
| `backtest/bootstrap.py` | drawdown range and the largest survivable risk |
| `backtest/walkforward.py` | tune on one window, trade the next, repeat |
| `backtest/engine.py` | realistic fills: must trade through, stops gap |
| `regimes.py` | results by volatility, trend, hour, day, all charged to the ledger |
| `paper/alpaca_broker.py` | the real Alpaca paper account |
| `paper/live_broker.py` | same interface as the simulation, real orders behind it |
| `data/freshness.py` | measures feed delay and blocks live trading when stale |
| `report.py` | daily plain-English report, live and replay kept apart |
| `notify.py` | Telegram alerts, quiet hours enforced, urgent bypasses |
| `status.py` | one command: is this working and should I believe it |

---

## The three honest options from here

### 1. Stop, and keep what was learned
The research is the deliverable. Five markets say the same thing. There is no
shame in a well-run experiment returning a negative result, and continuing to
tune against it is how people talk themselves into funding something.

### 2. Change what is being tested, not how
Everything so far tests one idea: liquidity sweep, break of structure, entry on
the retrace. If that idea does not work, no amount of better statistics will
make it work. A different family of ideas would need its own research cycle,
and the tooling now makes that cycle fast and honest.

### 3. Run it live on paper anyway, for the plumbing
Worth doing regardless of the edge question, because it tests things a backtest
cannot: rejected orders, partial fills, feed outages, positions out of sync. It
just must not be read as evidence about profitability. The report says so on
every page, on purpose.

**Recommendation: option 3 alongside option 1.** Let the paper account run to
prove the machinery, and do not fund anything until something clears
`evaluate.py`. Nothing has.

---

## Still open

| # | task | note |
|---|---|---|
| A1 | Dukascopy 2021-2024 backfill | still downloading; would extend the cross-check |
| A4 | S&P index cross-check | blocked, HistData TLS cert expired 2026-08-22 |
| C5 | Real-time consolidated feed | the free tier is IEX only; costs money to fix |

None of these change the conclusion. A1 and A4 would add confidence to a
negative result. C5 only matters once there is something worth trading.

---

## The rule that should outlive this project

A result is not real until it has cleared its own confidence interval, survived
being charged for every hypothesis tested to find it, held up on data it was
not chosen on, and reproduced on a feed from a different vendor.

The Nasdaq result passed thirteen tests and failed that one. It would have cost
real money.
