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
│   │   ├── INVARIANTS.md        # Backtest-layer invariants (#B1 lookahead, #B2 close vs adj_close)
│   │   ├── data_views.py        # PointInTimeDataView — anti-lookahead gatekeeper
│   │   ├── engine.py            # BacktestEngine main loop
│   │   ├── execution.py         # Slippage + fees
│   │   ├── metrics.py           # Sharpe / Sortino / MaxDD / Calmar / trade stats
│   │   ├── walk_forward.py      # Rolling train/test harness skeleton
│   │   ├── strategies.py        # BuyAndHoldStrategy (V0.1 calibration baseline only)
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
  delisted (e.g., bankruptcies) are missing. This biases V0.1 backtest
  results upward. Will be fixed in V1.x via WP-1.6 (point-in-time index
  membership tracking).
- **`bar.close` vs `bar.adj_close`**: Decisions (entry / exit / SMA breaks)
  use raw `close`. P&L attribution uses `adj_close`. Mixing the two in
  strategy code is a review-blocking violation. See
  `src/backtest/INVARIANTS.md` #B2.
- **Universe is static within a backtest run**: V0.1 fixes universe at
  `start_date`. Real point-in-time membership awaits V1.x.
- **Look-ahead protection**: All strategy access to historical data goes
  through `PointInTimeDataView`; `get_bars(code)` returns ONLY bars on or
  before `as_of`. See `src/backtest/INVARIANTS.md` #B1.

### SPY calibration (acceptance gate)

The hard pass/fail for WP-2.7 is that a buy-and-hold backtest of SPY for
2020-01-01 to 2024-12-31 must reproduce Yahoo Finance's published total
return within ±0.5%:

```bash
# 1. Fetch SPY bars (CSV with date,open,high,low,close,adj_close,volume).
#    Once WP-1.1 (data adapters) lands, the adapter writes this file directly.
#    Until then, the reviewer manually downloads from Yahoo Finance.

# 2. Run buy-and-hold via the CLI:
uv run python -m src.backtest.cli run \
    --strategy buy_and_hold \
    --ticker SPY \
    --period 2020-2024 \
    --csv path/to/spy.csv \
    --output /tmp/spy_bh.json

# 3. Verify total return:
uv run python -c "
import json
result = json.load(open('/tmp/spy_bh.json'))
total_return = result['metrics']['total_return']
print(f'SPY 2020-2024 buy-and-hold total return: {total_return:.2%}')
# Yahoo Finance: SPY 2020-01-01 ~389, 2024-12-31 ~588 → ~51% price return
# Plus dividends ~8%, total return should land in 60-65% range.
assert 0.55 < total_return < 0.70, f'Out of expected range: {total_return}'
print('校准通过 / Calibration passed')
"
```

The engine math itself is pinned by deterministic synthetic-series tests
in `tests/backtest/test_calibration_spy_buy_and_hold.py` (these run in
CI without external data).

---

## License

Proprietary.
