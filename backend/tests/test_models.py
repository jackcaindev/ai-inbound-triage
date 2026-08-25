from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record, Source
from app.models.enums import RecordStatus


async def test_duplicate_source_id_external_ref_violates_unique_constraint(
    db: AsyncSession, source: Source
) -> None:
    db.add(
        Record(
            source_id=source.id,
            external_ref="dup-1",
            raw_content="a",
            received_at=datetime.now(UTC),
            status=RecordStatus.PENDING.value,
        )
    )
    await db.flush()

    db.add(
        Record(
            source_id=source.id,
            external_ref="dup-1",
            raw_content="b",
            received_at=datetime.now(UTC),
            status=RecordStatus.PENDING.value,
        )
    )
    with pytest.raises(IntegrityError):
        await db.flush()


async def test_same_external_ref_allowed_across_different_sources(
    db: AsyncSession, source: Source
) -> None:
    other_source = Source(type="csv", config={}, active=True)
    db.add(other_source)
    await db.flush()

    db.add(
        Record(
            source_id=source.id,
            external_ref="shared-ref",
            raw_content="a",
            received_at=datetime.now(UTC),
            status=RecordStatus.PENDING.value,
        )
    )
    db.add(
        Record(
            source_id=other_source.id,
            external_ref="shared-ref",
            raw_content="b",
            received_at=datetime.now(UTC),
            status=RecordStatus.PENDING.value,
        )
    )
    await db.flush()  # no error — the unique constraint is scoped per source
