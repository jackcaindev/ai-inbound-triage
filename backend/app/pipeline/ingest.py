import csv
import json
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


async def _insert_row_if_new(
    source: Source,
    external_ref: str,
    raw_content: str,
    received_at: datetime,
    db: AsyncSession,
) -> bool:
    """Insert one record if (source_id, external_ref) isn't already present. Uses
    INSERT ... ON CONFLICT DO NOTHING rather than check-then-insert so it stays
    correct under concurrent syncs, not just sequential re-runs. Returns True if a
    new row was created, False if it already existed."""
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
    return result.first() is not None


async def ingest_csv(source: Source, csv_path: str | Path, db: AsyncSession) -> IngestResult:
    """Idempotent on (source_id, external_ref) — re-running against the same CSV never
    duplicates records."""
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
            if await _insert_row_if_new(source, external_ref, raw_content, received_at, db):
                created += 1
            else:
                skipped += 1

    source.last_synced_at = datetime.now(UTC)
    await db.flush()
    return IngestResult(created=created, skipped=skipped)


async def ingest_json_samples(source: Source, json_path: str | Path, db: AsyncSession) -> IngestResult:
    """Load a seed samples file shaped like seeds/inbound_samples.json: a top-level
    `records` array of {external_ref, raw_content, received_at}, plus any number of
    underscore-prefixed metadata keys (_note, _likely_category, _distribution_target,
    _extraction_fields, ...) which are documentation for whoever is authoring the
    samples and are ignored here. Idempotent on (source_id, external_ref), same as
    ingest_csv."""
    data = json.loads(Path(json_path).read_text(encoding="utf-8"))

    created = 0
    skipped = 0
    for row in data["records"]:
        received_at = datetime.fromisoformat(row["received_at"])
        if await _insert_row_if_new(
            source, row["external_ref"], row["raw_content"], received_at, db
        ):
            created += 1
        else:
            skipped += 1

    source.last_synced_at = datetime.now(UTC)
    await db.flush()
    return IngestResult(created=created, skipped=skipped)
