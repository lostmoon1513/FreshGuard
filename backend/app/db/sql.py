"""SQLAlchemy store (PostgreSQL in production, SQLite for local runs).

One table. The full request and result are stored as JSON; a few plain columns exist only for
filtering and ordering. Blocking SQLAlchemy calls run in a worker thread so the event loop is
never blocked. Tables are created at startup (`create_all`); Alembic migrations are deferred
(docs/DECISIONS.md D33).
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
from typing import Any, TypeVar

from sqlalchemy import JSON, BigInteger, String, and_, create_engine, or_, select, update
from sqlalchemy.engine import Engine
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from app.db.store import VerificationRecord, epoch_us
from app.schemas.labels import Label, VerificationStatus
from app.schemas.verification import VerificationRequest, VerificationResult

T = TypeVar("T")
_OPEN = (VerificationStatus.PENDING.value, VerificationStatus.RUNNING.value)


class Base(DeclarativeBase):
    pass


class VerificationRow(Base):
    __tablename__ = "verifications"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    created_us: Mapped[int] = mapped_column(BigInteger, index=True)
    status: Mapped[str] = mapped_column(String(16), index=True)
    label: Mapped[str | None] = mapped_column(String(24), index=True, nullable=True)
    request: Mapped[dict[str, Any]] = mapped_column(JSON)
    result: Mapped[dict[str, Any]] = mapped_column(JSON)


def normalize_database_url(url: str) -> str:
    """Accept the usual `postgres://` / `postgresql://` forms and pick the psycopg 3 driver."""
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix) :]
    return url


def make_engine(url: str) -> Engine:
    url = normalize_database_url(url)
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def _row(record: VerificationRecord) -> VerificationRow:
    result = record.result
    return VerificationRow(
        id=result.id,
        created_us=epoch_us(result.created_at),
        status=result.status.value,
        label=result.label.value if result.label else None,
        request=record.request.model_dump(mode="json"),
        result=result.model_dump(mode="json"),
    )


def _record(row: VerificationRow) -> VerificationRecord:
    return VerificationRecord(
        request=VerificationRequest.model_validate(row.request),
        result=VerificationResult.model_validate(row.result),
    )


class SqlStore:
    def __init__(self, engine: Engine) -> None:
        self._engine = engine
        self._sessions = sessionmaker(engine, expire_on_commit=False)

    def create_tables(self) -> None:
        Base.metadata.create_all(self._engine)

    def dispose(self) -> None:
        self._engine.dispose()

    async def _run(self, fn: Callable[[Session], T]) -> T:
        def work() -> T:
            with self._sessions() as session:
                return fn(session)

        return await asyncio.to_thread(work)

    async def create(self, record: VerificationRecord) -> None:
        def op(session: Session) -> None:
            session.add(_row(record))
            try:
                session.commit()
            except IntegrityError as exc:
                session.rollback()
                raise ValueError("duplicate id") from exc

        await self._run(op)

    async def save_result(self, result: VerificationResult) -> bool:
        def op(session: Session) -> bool:
            outcome = session.execute(
                update(VerificationRow)
                .where(VerificationRow.id == result.id)
                .values(
                    status=result.status.value,
                    label=result.label.value if result.label else None,
                    result=result.model_dump(mode="json"),
                )
            )
            session.commit()
            return (outcome.rowcount or 0) > 0

        return await self._run(op)

    async def get(self, result_id: str) -> VerificationRecord | None:
        def op(session: Session) -> VerificationRecord | None:
            row = session.get(VerificationRow, result_id)
            return _record(row) if row else None

        return await self._run(op)

    async def list(
        self, *, limit: int, label: Label | None = None, before: str | None = None
    ) -> list[VerificationRecord]:
        def op(session: Session) -> list[VerificationRecord]:
            query = select(VerificationRow)
            if before is not None:
                anchor = session.get(VerificationRow, before)
                if anchor is None:
                    return []
                query = query.where(
                    or_(
                        VerificationRow.created_us < anchor.created_us,
                        and_(
                            VerificationRow.created_us == anchor.created_us,
                            VerificationRow.id < anchor.id,
                        ),
                    )
                )
            if label is not None:
                query = query.where(VerificationRow.label == label.value)
            query = query.order_by(VerificationRow.created_us.desc(), VerificationRow.id.desc())
            rows = session.scalars(query.limit(limit)).all()
            return [_record(r) for r in rows]

        return await self._run(op)

    async def fail_incomplete(self, error: str, finished_at: datetime) -> int:
        def op(session: Session) -> int:
            rows = session.scalars(
                select(VerificationRow).where(VerificationRow.status.in_(_OPEN))
            ).all()
            for row in rows:
                failed = VerificationResult.model_validate(row.result).model_copy(
                    update={
                        "status": VerificationStatus.FAILED,
                        "error": error,
                        "label": None,
                        "confidence": None,
                        "finished_at": finished_at,
                    }
                )
                row.status = VerificationStatus.FAILED.value
                row.label = None
                row.result = failed.model_dump(mode="json")
            session.commit()
            return len(rows)

        return await self._run(op)