from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import resolve_record_id
from app.models import Record, Source
from app.models.enums import RecordStatus, SourceType


async def test_resolve_record_id_accepts_numeric_primary_key(db: AsyncSession, make_record) -> None:
    record = await make_record(external_ref="msg-001")

    assert await resolve_record_id(db, str(record.id)) == record.id


async def test_resolve_record_id_accepts_external_ref(db: AsyncSession, make_record) -> None:
    record = await make_record(external_ref="msg-001")

    assert await resolve_record_id(db, "msg-001") == record.id


async def test_resolve_record_id_unknown_external_ref_raises(db: AsyncSession) -> None:
    with pytest.raises(ValueError, match="No record found"):
        await resolve_record_id(db, "does-not-exist")


async def test_resolve_record_id_ambiguous_external_ref_raises(
    db: AsyncSession, make_record
) -> None:
    # external_ref is only unique per source, so the same external_ref can appear
    # on records from two different sources.
    other_source = Source(type=SourceType.CSV.value, config={}, active=True)
    db.add(other_source)
    await db.flush()

    first = await make_record(external_ref="shared")
    second = Record(
        source_id=other_source.id,
        external_ref="shared",
        raw_content="a different message",
        received_at=datetime.now(UTC),
        status=RecordStatus.PENDING.value,
    )
    db.add(second)
    await db.flush()

    with pytest.raises(ValueError, match="matches multiple records"):
        await resolve_record_id(db, "shared")

    assert first.id != second.id
