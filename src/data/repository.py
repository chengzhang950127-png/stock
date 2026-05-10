"""
Repositories for ``Stock`` and ``PriceBar``.

These are the only place outside ``src/db/`` allowed to know about the ORM
models. Callers pass / receive Pydantic contracts; internally we translate
to ``StockORM`` / ``PriceBarORM`` and back.

Phase 0's choice of sync DB driver (psycopg v3 sync) is deliberate — see
the README. WP-2.x backtests are wall-clock dominated by data fetch and
strategy compute; an async DB layer here would be premature complexity.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

from sqlalchemy import Executable, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session

from src.contracts import Currency, Market, PriceBar, Stock
from src.db.models import PriceBarORM, StockORM


def _upsert_dialect(session: Session) -> str:
    """Return ``"postgresql"`` or ``"sqlite"`` (the two we ever target)."""
    return session.bind.dialect.name if session.bind is not None else "sqlite"


def _build_upsert(
    session: Session,
    table: Any,
    rows: list[dict[str, Any]],
    key_cols: Sequence[str],
    update_cols: Sequence[str],
) -> Executable:
    """Construct an ON CONFLICT DO UPDATE statement for either dialect.

    We split the dialect-specific imports here so the calling code stays a
    single statement. Mypy treats the two return types as the same Executable.
    """
    insert_fn = pg_insert if _upsert_dialect(session) == "postgresql" else sqlite_insert
    stmt = insert_fn(table).values(rows)
    update_set = {col: stmt.excluded[col] for col in update_cols}
    return stmt.on_conflict_do_update(index_elements=list(key_cols), set_=update_set)


class StockRepository:
    """CRUD for ``stocks``. ``upsert`` is keyed on ``(code, market)``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert(self, stock: Stock) -> None:
        """Insert or update one ``Stock`` row."""
        self._upsert_many([stock])

    def upsert_many(self, stocks: Iterable[Stock]) -> None:
        self._upsert_many(list(stocks))

    def _upsert_many(self, stocks: list[Stock]) -> None:
        if not stocks:
            return
        rows = [
            {
                "code": s.code,
                "market": s.market,
                "currency": s.currency.value,
                "name": s.name,
                "industry": s.industry,
                "market_cap": s.market_cap,
                "listed_date": s.listed_date,
            }
            for s in stocks
        ]
        update_keys = ("currency", "name", "industry", "market_cap", "listed_date")
        self._session.execute(
            _build_upsert(self._session, StockORM, rows, ("code", "market"), update_keys)
        )
        self._session.commit()

    def get(self, code: str, market: Market = Market.US) -> Stock | None:
        row = self._session.execute(
            select(StockORM).where(StockORM.code == code, StockORM.market == market)
        ).scalar_one_or_none()
        return _stock_from_orm(row) if row is not None else None

    def list_by_market(self, market: Market) -> list[Stock]:
        rows = (
            self._session.execute(
                select(StockORM).where(StockORM.market == market).order_by(StockORM.code)
            )
            .scalars()
            .all()
        )
        return [_stock_from_orm(r) for r in rows]


class PriceBarRepository:
    """CRUD for ``price_bars``. Upserts are keyed on ``(code, market, date)``."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def upsert_many(self, bars: Iterable[PriceBar]) -> None:
        bar_list = list(bars)
        if not bar_list:
            return
        rows = [
            {
                "code": b.code,
                "market": b.market,
                "date": b.date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "adj_close": b.adj_close,
                "volume": b.volume,
            }
            for b in bar_list
        ]
        update_keys = ("open", "high", "low", "close", "adj_close", "volume")
        self._session.execute(
            _build_upsert(
                self._session, PriceBarORM, rows, ("code", "market", "date"), update_keys
            )
        )
        self._session.commit()

    def get_range(
        self, code: str, start: date, end: date, market: Market = Market.US
    ) -> list[PriceBar]:
        rows = (
            self._session.execute(
                select(PriceBarORM)
                .where(
                    PriceBarORM.code == code,
                    PriceBarORM.market == market,
                    PriceBarORM.date >= start,
                    PriceBarORM.date <= end,
                )
                .order_by(PriceBarORM.date)
            )
            .scalars()
            .all()
        )
        return [_price_bar_from_orm(r) for r in rows]

    def count(self, market: Market | None = None) -> int:
        from sqlalchemy import func

        stmt = select(func.count()).select_from(PriceBarORM)
        if market is not None:
            stmt = stmt.where(PriceBarORM.market == market)
        return int(self._session.execute(stmt).scalar_one())


# ---- Translators (kept module-level so they're easy to test) ----


def _stock_from_orm(row: StockORM) -> Stock:
    return Stock(
        code=row.code,
        market=row.market,
        currency=Currency(row.currency),
        name=row.name,
        industry=row.industry,
        market_cap=row.market_cap,
        listed_date=row.listed_date,
    )


def _price_bar_from_orm(row: PriceBarORM) -> PriceBar:
    return PriceBar(
        code=row.code,
        market=row.market,
        date=row.date,
        open=row.open,
        high=row.high,
        low=row.low,
        close=row.close,
        adj_close=row.adj_close,
        volume=row.volume,
    )


__all__ = ["PriceBarRepository", "StockRepository"]
