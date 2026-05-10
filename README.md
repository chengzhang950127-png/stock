# quant-system

LLM-augmented multi-strategy quantitative trading system for US and HK
equities. This repository holds the **Phase 0 scaffolding** — directory
structure, shared data contracts, the LLM Gateway abstraction, configuration,
CI plumbing, and dev-environment scaffolding. No strategy logic, real data
sources, or real LLM calls land here; those arrive in subsequent Work
Packages.

> **Important:** four core docs (`architecture.md`, `version-plan.md`,
> `wbs.md`, `review-protocol.md`) live in the project knowledge base and are
> not in this repo yet. See `docs/PROJECT_DOCS_PLACEHOLDER.md` for the drop-in
> instructions before starting any WP review.

---

## Quick start

```bash
# 1. Install backend deps (uv-managed)
uv sync --extra dev

# 2. Bring up Postgres
docker compose up -d postgres

# 3. Apply schema
uv run alembic upgrade head

# 4. Run tests + lint + invariant check
make check

# 5. Run the API
make dev          # http://localhost:8000/health
```

Frontend (optional for backend WPs):

```bash
cd frontend
npm install
npm run dev       # http://localhost:5173
```

---

## Repo layout

```
quant-system/
├── src/
│   ├── contracts.py             # Pydantic models — single source of truth for cross-module data
│   ├── config.py                # Pydantic Settings (.env-driven)
│   ├── db/
│   │   ├── models.py            # SQLAlchemy 2.x ORM
│   │   ├── session.py           # engine + session factory
│   │   └── migrations/          # Alembic
│   ├── llm/
│   │   ├── gateway.py           # Abstract LLMGateway — every LLM call funnels through here
│   │   ├── mock.py              # Mock used through V0.5
│   │   ├── audit.py             # In-memory call recorder
│   │   └── schemas.py           # Cross-business LLM I/O schemas
│   ├── strategies/base.py       # StrategyBase abstract class
│   ├── backtest/                # WP-2.7 — vectorized backtest engine
│   │   ├── INVARIANTS.md        # Backtest-layer invariants (B1-B4)
│   │   ├── data_views.py        # PointInTimeDataView (anti-lookahead, INVARIANT #8 / #B1)
│   │   ├── engine.py            # BacktestEngine: T close decide / T+1 open execute
│   │   ├── execution.py         # ExecutionCostModel + slippage + fees (#B2)
│   │   ├── metrics.py           # Sharpe / Sortino / MaxDD / Calmar / FIFO trade stats
│   │   ├── walk_forward.py      # Interface signature only — body in V0.5
│   │   ├── _calibration_strategies.py  # BuyAndHoldStrategy (calibration anchor only)
│   │   └── cli.py               # `python -m src.backtest.cli run --strategy buy_and_hold ...`
│   ├── data/                    # WP-1.x — data acquisition
│   ├── portfolio/               # WP-2.8 — execution and reconciliation
│   ├── assistant/               # WP-3.x — investment assistant
│   ├── api/main.py              # FastAPI entrypoint
│   └── utils/logging.py         # structlog config
├── frontend/                    # Vite + React + TS + Tailwind scaffold
├── tests/                       # Round-trip + smoke tests
├── scripts/
│   ├── generate_contracts_md.py
│   └── verify_invariants.py     # Runs every architectural invariant check
├── docs/
│   ├── INVARIANTS.md            # Canonical reference, mirrored by verify_invariants.py
│   ├── CONTRACTS.md             # Auto-generated from contracts.py
│   └── PROJECT_DOCS_PLACEHOLDER.md
├── .github/workflows/           # ci.yml + frontend-ci.yml
├── docker-compose.yml
├── Dockerfile.api
├── Makefile
├── pyproject.toml               # uv + ruff + mypy + pytest
├── alembic.ini
└── .env.example
```

---

## Architectural invariants (must-not-violate)

See `docs/INVARIANTS.md` for the full list. Summary:

1. Decision-path code (strategies, portfolio, regime, allocator) makes **zero
   LLM calls** — those decisions are pure rules.
2. The two AI-permitted modules are the event-driven news parser and the
   assistant narrative generator.
3. Every LLM call routes through `LLMGateway` and supplies a Pydantic
   `response_schema`.
4. Model ids are pinned with dated suffixes (no `latest` aliases).
5. `temperature=0.0` by default.
6. Every `StrategyBase` subclass implements all four abstract methods.
7. Secrets, broker credentials, and personal positions never touch git.

`scripts/verify_invariants.py` enforces these in CI. Run locally with `make verify`.

---

## Engineering decisions made during Phase 0

| Decision                                      | Choice                            | Reason                                                                 |
|-----------------------------------------------|-----------------------------------|------------------------------------------------------------------------|
| Python package manager                         | `uv`                              | Faster than poetry; lockfile is portable; simpler CI cache.            |
| Alembic initial migration                      | Hand-written, covers every ORM model | Lets later WPs pick up an already-migrated DB without touching schema. |
| Pre-commit hooks                               | Optional (config provided)        | `make check` is the source of truth; hooks just shorten the loop.      |
| Frontend in Phase 0                            | Vite + React 18 + TS + Tailwind shell | Real pages land in WP-4.x — build green-lights everything else.        |
| `Position.quantity` / `Trade.quantity` types   | `Decimal`                         | Fractional shares are first-class on US brokers (IBKR / Schwab / Fidelity). |
| Logging                                        | `structlog`, JSON in non-dev      | Friendlier for downstream observability; matches FastAPI conventions.  |
| LLM provider in dev / V0.1-V0.5                | Mock                              | Keeps decision-path INVARIANTs verifiable without provider keys.       |
| DB driver                                      | `psycopg` (v3) — sync only        | Phase 0 doesn't need async DB; can layer asyncpg later if necessary.   |
| Currency handling                              | `Currency` enum on `Stock` / `Account` / `Position` / `Trade` | Cross-market portfolio MTM and FX accounting need explicit source-of-funds; comments alone are not enough. Added in Phase 0.5 (v1.1 docs). |

---

## Where to look first (recommended review order)

1. `src/contracts.py` — the data shapes every WP depends on.
2. `docs/INVARIANTS.md` — the rules every WP must respect.
3. `src/llm/gateway.py` + `src/llm/mock.py` — how AI calls are gated.
4. `src/strategies/base.py` — the strategy contract.
5. `src/db/models.py` + the initial migration — persistence layout.
6. `scripts/verify_invariants.py` — automated enforcement.

---

## Known TODOs deferred to later WPs

- A real LLMGateway adapter (LiteLLM-backed) lands in V0.6 (WP-2.4 V0.6 +
  the AI narrative module called out in `version-plan.md` §V0.6).
- DB-backed audit log for LLM calls — currently in-memory ring buffer.
- Real data adapters under `src/data/` (yfinance, Tushare/AKShare for HK) —
  WP-1.x.
- Notification adapters (Telegram / email / WeWork) — WP-4.2.
- Authenticated API and JWT — WP-5.1.
- Frontend pages — WP-4.3 / WP-4.4 / WP-4.5.

---

## Backtest engine — known limitations (V0.1)

- **Survivorship bias**: V0.1 backtests use today's S&P 500 membership for
  the entire period. Stocks that were in the index in 2020 but were since
  delisted are missing. This biases V0.1 backtest results upward. Will be
  fixed in V1.x via WP-1.6 (point-in-time index membership tracking).
- **`bar.close` vs `bar.adj_close`**: Decisions and MTM use raw `close`.
  P&L attribution (daily_return / cumulative_return) uses `adj_close`.
  Mixing these in strategy code is a review-blocking violation. See
  `src/backtest/INVARIANTS.md` #B1.
- **Universe is static within a backtest run**: V0.1 fixes universe at
  `start_date`. Real point-in-time membership awaits V1.x.
- **Dividends are not modeled as cash flows**: V0.1 relies on `adj_close`
  to express the implicit "dividend immediately reinvested" assumption.
  `nav` series (computed from `close`) and total-return series (computed
  from `adj_close`) typically differ by an amount ≈ dividend reinvestment
  PV. This is a documented design choice (architecture §10.5 #5), not a
  bug. V0.7 (broker integration) will model real dividend cash flows.
- **HK market not supported in V0.1**: Only `US_DEFAULT_COST`
  (USD-denominated) is implemented. HK execution costs will be added in
  WP-1.2 / V0.2.
- **`walk_forward_test` is not implemented**: Interface signature is
  locked for forward compatibility, but raises `NotImplementedError`.
  Will be filled in V0.5 for custom-strategy parameter optimization.

### SPY calibration (acceptance gate)

The hard pass/fail for WP-2.7 is that a lump-sum buy-and-hold backtest of
SPY for 2020-01-01 to 2024-12-31 must reproduce the yfinance-source
total return within ±2%. **Two return metrics are reported**, with the
±2% gate applied to the dividend-adjusted one:

- `metrics.total_return` — close-based price return (compares to yfinance
  `Close` ratio for the period, ≈ +80% for SPY 2020-2024).
- `metrics.total_return_with_dividends` — adj_close-based total return
  (compares to yfinance `Adj Close` ratio, the standard "5y total return"
  benchmark, ≈ +96-97% for SPY 2020-2024).

The Architect's ±2% tolerance applies to `total_return_with_dividends`
vs yfinance Adj Close TR — this is the apples-to-apples comparison.
The two metrics diverge by ≈ dividend reinvestment PV (per
`docs/architecture.md §10.5` #5).

Below: target value set by Architect after Implementer runs the CLI on
real SPY data:

```bash
# 1. Fetch SPY bars (CSV with date,open,high,low,close,adj_close,volume).
#    Once WP-1.1 (data adapters) lands, the adapter writes this file directly.
#    Until then, the reviewer manually downloads from Yahoo Finance.

# 2. Run buy-and-hold via the CLI (calibration mode required):
uv run python -m src.backtest.cli run \
    --strategy buy_and_hold \
    --ticker SPY \
    --period 2020-01-01:2024-12-31 \
    --calibration-mode \
    --csv path/to/spy.csv \
    --output /tmp/spy_bh.json

# 3. Architect reviews the actual numbers + intermediate values:
uv run python -c "
import json
result = json.load(open('/tmp/spy_bh.json'))
print('=== SPY lump-sum buy-and-hold 2020-01-01 to 2024-12-31 ===')
print(f'Initial cash:                {result[\"account_initial_cash\"]}')
print(f'Final NAV:                   {result[\"account_final_nav\"]}')
print(f'Total return (price):        {result[\"metrics\"][\"total_return\"]:.4%}')
print(f'Total return (with divid.):  {result[\"metrics\"][\"total_return_with_dividends\"]:.4%}')
print(f'Annual return (price):       {result[\"metrics\"][\"annual_return\"]:.4%}')
print(f'Annual return (with divid.): {result[\"metrics\"][\"annual_return_with_dividends\"]:.4%}')
print(f'Sharpe:                      {result[\"metrics\"][\"sharpe\"]:.3f}')
print(f'Max drawdown:                {result[\"metrics\"][\"max_drawdown\"]:.4%}')
print(f'Number of trades:            {result[\"trade_count\"]}')  # expect 1 (T0 lump-sum)
print(f'Total fees:                  {result[\"total_fees\"]}')
"
```

The engine math itself is pinned by deterministic synthetic-series tests
in `tests/backtest/test_calibration_spy_buy_and_hold.py` (these run in
CI without external data).

---

## License

Proprietary.
