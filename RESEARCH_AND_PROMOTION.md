# Gold Terminal — research, audit and promotion rules

## Experiment design

Two production-candidate windows are 08:00–18:00 and 13:00–18:00 UTC
(Accra). Two extra exploratory comparisons are 08:00–13:00 and 10:00–18:00.
We test logistic regression on gold-only features and a second version including
last-completed hourly silver, WTI, copper, dollar index, Treasury yield and S&P
500 features. Macro here means market proxies, not economic-release surprises.
Both models for a given window use exactly the same dates; each rolling model
uses earlier completed outcomes only. Final 20% is a chronological test with
daily refits; prior test outcomes enter later refits only after they are known.
Samples differ between windows because feeds and sessions can be missing. Data
is Yahoo GC=F continuous futures, not broker spot. Do not interpret a comparison
across unequal samples as causal evidence about the best session.

Research is exploratory: window selection and feature ideas have now been
inspected on this period, so it is no longer an untouched final test. Market
returns and prices may be revised, and Yahoo continuous futures roll and
corporate/provider adjustments are not modeled. Availability is assumed one hour
after the timestamp of an hourly bar; archived actual receipt times are not
available. Feeds older than 72 hours are dropped, but age varies; for equity and
yields, early UTC observations may come from the prior US session.

`research_audit.py` stores the last 7 days of completed GC hourly OHLC and
compares them to the next retrieval in `quote_audit.json`. It logs retrieval time,
changes and source metadata. It cannot establish when historical quotes became
available and does not audit all macro series, broker prices, missing data or
all past vintages. No changes detected is not proof of no revisions. More runs
and a timestamped live capture are needed. Do not overwrite the log on upload.

## Simulated transaction costs

For each forecast, the exploratory study assumes one unit long if P(up) >= 50%,
otherwise one unit short, on the *bar open*, exits at the ending bar open, and
subtracts hypothetical $1/$3/$5 per ounce round trip. This is an optimistic
research stress test, not realistic execution or investment returns: the open is
already in the past by the time the data arrives and the forecast is issued.
The amounts are examples, not broker quotes. No commission schedule, financing,
slippage distribution, margin, stop, position sizing or intrabar execution is
included. Actual XAUUSD spreads, commissions, contract size and broker fills
must be collected before relying on P&L.

## Candidate promotion policy (proposed, no automatic promotion)

1. Freeze the candidate features, horizon, target, hyperparameters, missing-data
   rules, execution rules and reference model before collecting fresh data.
2. Run it in shadow on at least 100 independently logged forecast days *per
   window* after the freeze. Record provider quote, receipt and issue times,
   broker bid/ask and all failures. Never backfill missed forecasts. 100 is a
   minimum, not a guarantee of statistical power.
3. Candidate must beat the existing gold-only model and an always-up/always-down
   reference chosen using training data, on matched fresh forecast days. Require
   at least a five percentage-point accuracy improvement versus the frozen gold
   model, and a pre-specified one-sided 95% block-bootstrap lower confidence bound
   for the paired improvement above zero. Report sample size and uncertainty.
4. Also require lower Brier score and positive average simulated P&L net of
   actual documented bid/ask, commission, expected slippage and financing, with
   a positive 95% block-bootstrap lower bound. Compare a no-trade baseline. Decide
   block length, fill rules and execution latency before observing this test.
5. Investigate stability by month and both UTC windows, stale/missing data and
   revision rates. Any leakage, unsafe fill assumption, unlogged forecast or
   unacceptable drawdown pauses promotion. Predefine acceptable drawdown and
   exposure with the user before a trading implementation.
6. Manually review and approve. Preserve frozen versions and all logs; shadow the
   new model alongside the previous model. No automated promotion is enabled.

These are research gates, not a promise that the model will be useful or profitable.
