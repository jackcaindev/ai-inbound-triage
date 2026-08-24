import os
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from typing import Any

# Must be set before app.config is imported anywhere (it's read once, at import time,
# into a module-level Settings() singleton) — this is what points every test at the
# test database instead of the dev one.
os.environ.setdefault(
    "DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/triage_test"
)

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.db import Base
from app.llm.client import LLMCallResult
from app.models import Record, Source
from app.models.enums import RecordStatus
from app.schemas.classification import ClassificationResult
from app.schemas.extraction import BaseExtractionFields

TEST_DATABASE_URL = os.environ["DATABASE_URL"]


@pytest.fixture
async def db() -> AsyncIterator[AsyncSession]:
    """A fresh schema and a fresh session per test — simplest way to get full
    isolation without juggling nested-transaction/savepoint rollback semantics
    across pipeline code that only flushes (commit is the caller's job)."""
    engine = create_async_engine(TEST_DATABASE_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)

    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session

    await engine.dispose()


@pytest.fixture
async def source(db: AsyncSession) -> Source:
    src = Source(type="csv", config={}, active=True)
    db.add(src)
    await db.flush()
    return src


@pytest.fixture
def make_record(
    db: AsyncSession, source: Source
) -> Callable[..., Any]:
    async def _make(
        external_ref: str = "rec-1",
        raw_content: str = "Test message",
        received_at: datetime | None = None,
    ) -> Record:
        record = Record(
            source_id=source.id,
            external_ref=external_ref,
            raw_content=raw_content,
            received_at=received_at or datetime.now(UTC),
            status=RecordStatus.PENDING.value,
        )
        db.add(record)
        await db.flush()
        return record

    return _make


class FakeLLMController:
    """Controls what app.pipeline.classify/extract get back from call_structured,
    without ever hitting the real Anthropic API. Either set fixed responses with
    set_classification()/set_extraction(), or set_responder() for a callback that
    inspects the call kwargs (useful when a test processes several different
    messages and needs a different answer per message)."""

    def __init__(self, state: dict[str, Any]) -> None:
        self._state = state

    def set_classification(
        self, category: str, confidence: float, reasoning: str | None = None
    ) -> None:
        self._state["classification"] = ClassificationResult(
            category=category, confidence=confidence, reasoning=reasoning
        )

    def set_extraction(self, **fields: Any) -> None:
        self._state["extraction"] = BaseExtractionFields(**fields)

    def set_responder(self, fn: Callable[[dict[str, Any]], Any]) -> None:
        self._state["responder"] = fn


@pytest.fixture
def fake_llm(monkeypatch: pytest.MonkeyPatch) -> FakeLLMController:
    state: dict[str, Any] = {"classification": None, "extraction": None, "responder": None}

    async def fake_call_structured(**kwargs: Any) -> LLMCallResult:
        if state["responder"] is not None:
            parsed = state["responder"](kwargs)
        elif kwargs["response_model"] is ClassificationResult:
            parsed = state["classification"]
        else:
            parsed = state["extraction"]
        return LLMCallResult(parsed=parsed, raw_response={"fake": True}, latency_ms=10)

    monkeypatch.setattr("app.pipeline.classify.call_structured", fake_call_structured)
    monkeypatch.setattr("app.pipeline.extract.call_structured", fake_call_structured)

    return FakeLLMController(state)
