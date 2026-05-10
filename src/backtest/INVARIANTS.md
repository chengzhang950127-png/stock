# Backtest-layer invariants

Two rules scoped to the backtest engine and the strategies it drives.
Project-level invariants live in `docs/INVARIANTS.md` (#1-#7); these are
narrower in scope but equally non-negotiable for code under `src/backtest/`
and any strategy module the engine imports.

---

## #B1 — Look-ahead bias protection

Strategy code MUST access historical data only through
`src.backtest.data_views.PointInTimeDataView`. The engine constructs a
fresh view per simulation step with `as_of = current_date`; the view
returns ONLY bars with `bar.date <= as_of`.

Direct access to `historical_data` (the full dict) from strategy code is a
review-blocking violation. The engine never exposes that dict to strategies.

**Why this is a separate invariant**: a single line that returns
`all_bars[code]` instead of `[b for b in all_bars[code] if b.date <= as_of]`
silently produces backtest results that look plausible but use tomorrow's
prices to make today's decisions. Detecting this after the fact is hard;
making the engine the gatekeeper makes it impossible.

**Programmatic check**: integration test
`tests/backtest/test_no_lookahead.py` runs a strategy that records every
`bar.date` it sees and asserts none exceed the step's `as_of`.

---

## #B2 — `close` vs `adj_close` usage boundary

Two distinct uses of price data, two distinct fields:

| Use case                                                       | Field        |
|----------------------------------------------------------------|--------------|
| Trade entry / exit decisions, SMA / breakout / signal triggers | `bar.close`  |
| Daily-return / cumulative-return / NAV computation             | `bar.adj_close` |

Reasons:

- `close` reflects the actual quote a trader could have transacted at on
  that day. Using `adj_close` for decisions retroactively rewrites past
  prices for splits / dividends — prices the trader never saw.
- `adj_close` is split- and dividend-adjusted, so a return series built
  from it is free of mechanical jumps and reflects total return.

`Trade.price` records the original `close` (what got executed); NAV /
return series in `PerformanceSnapshot` are computed from `adj_close`.

Mixing the two inside strategy code (e.g. SMA on `adj_close`, breakout on
`close`) is a review-blocking violation unless the PR explicitly justifies
it.
