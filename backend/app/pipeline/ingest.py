import csv
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Record, Source
from app.models.enums import RecordStatus

DEFAULT_COLUMNS = {
    "external_ref": "external_ref",
    "raw_content": "raw_content",
    "received_at": "received_at",
}


@dataclass
class IngestResult:
    created: int
    skipped: int


async def ingest_csv(source: Source, csv_path: str | Path, db: AsyncSession) -> IngestResult:
    """Idempotent on (source_id, external_ref) — re-running against the same CSV never
    duplicates records. Uses INSERT ... ON CONFLICT DO NOTHING rather than check-then-insert
    so it stays correct under concurrent syncs, not just sequential re-runs."""
    columns = {**DEFAULT_COLUMNS, **source.config.get("column_map", {})}

    created = 0
    skipped = 0
    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            external_ref = row[columns["external_ref"]]
            raw_content = row[columns["raw_content"]]
            received_at_raw = row.get(columns["received_at"]) or None
            received_at = (
                datetime.fromisoformat(received_at_raw) if received_at_raw else datetime.now(UTC)
            )

            stmt = (
                pg_insert(Record)
                .values(
                    source_id=source.id,
                    external_ref=external_ref,
                    raw_content=raw_content,
                    received_at=received_at,
                    status=RecordStatus.PENDING.value,
                )
                .on_conflict_do_nothing(index_elements=["source_id", "external_ref"])
                .returning(Record.id)
            )
            result = await db.execute(stmt)
            if result.first() is not None:
                created += 1
            else:
                skipped += 1

    source.last_synced_at = datetime.now(UTC)
    await db.flush()
    return IngestResult(created=created, skipped=skipped)
