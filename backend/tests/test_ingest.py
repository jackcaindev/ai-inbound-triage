import csv
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record, Source
from app.pipeline.ingest import ingest_csv

ROWS = [
    {"external_ref": "a", "raw_content": "hello there", "received_at": "2026-01-01T00:00:00"},
    {"external_ref": "b", "raw_content": "world, how are you", "received_at": "2026-01-01T00:00:00"},
]


def _write_csv(path: Path, rows: list[dict[str, str]]) -> Path:
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["external_ref", "raw_content", "received_at"])
        writer.writeheader()
        writer.writerows(rows)
    return path


async def test_ingest_is_idempotent_on_source_and_external_ref(
    db: AsyncSession, source: Source, tmp_path: Path
) -> None:
    csv_path = _write_csv(tmp_path / "messages.csv", ROWS)

    first = await ingest_csv(source, csv_path, db)
    assert first.created == 2
    assert first.skipped == 0

    # Re-running against the exact same file — as a real re-sync would — must not
    # duplicate anything.
    second = await ingest_csv(source, csv_path, db)
    assert second.created == 0
    assert second.skipped == 2

    result = await db.execute(select(Record).where(Record.source_id == source.id))
    records = result.scalars().all()
    assert len(records) == 2
    assert {r.external_ref for r in records} == {"a", "b"}


async def test_ingest_only_adds_new_rows_on_partial_overlap(
    db: AsyncSession, source: Source, tmp_path: Path
) -> None:
    first_path = _write_csv(tmp_path / "batch1.csv", ROWS)
    await ingest_csv(source, first_path, db)

    second_batch = ROWS + [
        {"external_ref": "c", "raw_content": "a new message", "received_at": "2026-01-02T00:00:00"}
    ]
    second_path = _write_csv(tmp_path / "batch2.csv", second_batch)
    result = await ingest_csv(source, second_path, db)

    assert result.created == 1
    assert result.skipped == 2

    all_records = (
        await db.execute(select(Record).where(Record.source_id == source.id))
    ).scalars().all()
    assert len(all_records) == 3
