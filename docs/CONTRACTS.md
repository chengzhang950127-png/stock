# Contracts (auto-generated)

Source of truth: `src/contracts.py`. Run `make contracts` after changing the Pydantic models to refresh this document.

## Enums

### `AccountType`

- `SHADOW` = `'SHADOW'`
- `LIVE` = `'LIVE'`

### `Currency`

- `USD` = `'USD'`
- `HKD` = `'HKD'`

### `ExitAction`

- `HOLD` = `'HOLD'`
- `REDUCE` = `'REDUCE'`
- `EXIT` = `'EXIT'`

### `Market`

- `US` = `'US'`
- `HK` = `'HK'`

### `RegimeLabel`

- `EARNINGS_DRIVEN` = `'EARNINGS_DRIVEN'`
- `LIQUIDITY_DRIVEN` = `'LIQUIDITY_DRIVEN'`
- `POLICY_DRIVEN` = `'POLICY_DRIVEN'`
- `RISK_OFF` = `'RISK_OFF'`
- `TRANSITIONING` = `'TRANSITIONING'`

### `SignalDirection`

- `BUY` = `'BUY'`
- `SELL` = `'SELL'`
- `HOLD` = `'HOLD'`

### `StrategyStatus`

- `ACTIVE` = `'ACTIVE'`
- `ARCHIVED` = `'ARCHIVED'`
- `DELETED` = `'DELETED'`

### `StrategyType`

- `BUILT_IN` = `'BUILT_IN'`
- `CUSTOM` = `'CUSTOM'`

## Models

### `Account`

- `id`: `str`
- `type`: `AccountType`
- `strategy_id`: `str`
- `currency`: `Currency`
- `cash`: `Decimal`
- `initial_capital`: `Decimal`
- `created_at`: `datetime`

### `AssetAllocation`

Three-tier asset allocation recommendation.

- `date`: `date`
- `total_equity_pct`: `float`
- `market_weights`: `dict`
- `strategy_weights`: `dict`

### `AssistantAdvice`

A single dated piece of advice from the investment assistant.

- `id`: `str`
- `date`: `date`
- `regime`: `Regime`
- `allocation`: `AssetAllocation`
- `narrative`: `str | None`
- `risk_alerts`: `list`
- `generated_at`: `datetime`
- `verified_at`: `datetime.datetime | None`
- `verification_score`: `float | None`

### `CustomBlendParameters`

Parameters for the user-defined four-factor blended strategy (V0.5+).

- `w_value`: `float`
- `w_momentum`: `float`
- `w_event`: `float`
- `w_index`: `float`

### `ExitDecision`

A strategy's verdict for an existing position on a given day.

- `action`: `ExitAction`
- `reason_code`: `str`
- `target_quantity`: `decimal.Decimal | None`

### `PerformanceArchive`

Final performance snapshot stored when a strategy is archived.

- `strategy_id`: `str`
- `strategy_name`: `str`
- `archive_date`: `date`
- `metrics`: `PerformanceMetrics`
- `full_history`: `list`

### `PerformanceMetrics`

Aggregate metrics computed over a window.

- `total_return`: `float`
- `annual_return`: `float`
- `sharpe`: `float`
- `sortino`: `float`
- `max_drawdown`: `float`
- `calmar`: `float`
- `win_rate`: `float`
- `avg_holding_days`: `float`

### `PerformanceSnapshot`

Daily snapshot of an account's performance state.

- `account_id`: `str`
- `date`: `date`
- `nav`: `Decimal`
- `cash`: `Decimal`
- `positions_value`: `Decimal`
- `daily_return`: `float`
- `cumulative_return`: `float`
- `drawdown`: `float`

### `Position`

An open holding. ``quantity`` is Decimal to allow fractional shares.

- `account_id`: `str`
- `stock_code`: `str`
- `market`: `Market`
- `currency`: `Currency`
- `quantity`: `Decimal`
- `avg_cost`: `Decimal`
- `opened_at`: `datetime`

### `PriceBar`

A single OHLCV bar (daily granularity by default).

- `code`: `str`
- `market`: `Market`
- `date`: `date`
- `open`: `Decimal`
- `high`: `Decimal`
- `low`: `Decimal`
- `close`: `Decimal`
- `adj_close`: `Decimal`
- `volume`: `int`

### `Regime`

The market regime classification for a given day.

- `date`: `date`
- `primary_label`: `RegimeLabel`
- `probabilities`: `dict`
- `confidence`: `float`
- `drivers`: `list`

### `Signal`

A strategy's intent to buy / sell on a given day.

- `id`: `str`
- `strategy_id`: `str`
- `stock_code`: `str`
- `market`: `Market`
- `direction`: `SignalDirection`
- `buy_range`: `tuple[decimal.Decimal, decimal.Decimal] | None`
- `stop_loss`: `decimal.Decimal | None`
- `take_profit`: `decimal.Decimal | None`
- `position_size_pct`: `float`
- `confidence`: `float`
- `reason_code`: `str`
- `reason_narrative`: `str | None`
- `generated_at`: `datetime`

### `Stock`

A tradeable instrument identifier + static descriptive fields.

- `code`: `str`
- `market`: `Market`
- `currency`: `Currency`
- `name`: `str`
- `industry`: `str | None`
- `market_cap`: `decimal.Decimal | None`
- `listed_date`: `datetime.date | None`

### `Strategy`

Strategy metadata persisted in the DB.

The ``parameters`` field is the typed container. At the ORM boundary it
is serialized to JSONB; business code should always pass and accept
``StrategyParameters`` (or subclasses), never raw dicts.

- `id`: `str`
- `name`: `str`
- `type`: `StrategyType`
- `status`: `StrategyStatus`
- `parameters`: `StrategyParameters`
- `description`: `str | None`
- `created_at`: `datetime`
- `updated_at`: `datetime`
- `archived_at`: `datetime.datetime | None`

### `StrategyParameters`

Container for strategy-specific parameters.

Concrete strategy classes can subclass this with strongly-typed fields.
The ``extra="allow"`` policy lets us round-trip unknown keys through JSONB
without losing data, which is useful when an older strategy version is
loaded by newer code (forward compatibility).


### `Trade`

An executed (or simulated) order fill.

- `id`: `str`
- `account_id`: `str`
- `stock_code`: `str`
- `market`: `Market`
- `currency`: `Currency`
- `direction`: `SignalDirection`
- `quantity`: `Decimal`
- `price`: `Decimal`
- `fee`: `Decimal`
- `executed_at`: `datetime`
- `signal_id`: `str | None`

