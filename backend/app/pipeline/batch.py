from collections.abc import Callable
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Classification, Record
from app.models.enums import RecordStatus
from app.pipeline.process import process_record

TERMINAL_STATUSES = (
    RecordStatus.AUTO_ROUTED.value,
    RecordStatus.NEEDS_REVIEW.value,
    RecordStatus.FAILED.value,
)


@dataclass
class RecordOutcome:
    record_id: int
    external_ref: str
    category: str | None
    confidence: float | None
    status: str


@dataclass
class BatchSummary:
    outcomes: list[RecordOutcome] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.outcomes)

    @property
    def auto_routed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == RecordStatus.AUTO_ROUTED.value)

    @property
    def needs_review(self) -> int:
        return sum(1 for o in self.outcomes if o.status == RecordStatus.NEEDS_REVIEW.value)

    @property
    def failed(self) -> int:
        return sum(1 for o in self.outcomes if o.status == RecordStatus.FAILED.value)

    @property
    def auto_route_pct(self) -> float:
        return (self.auto_routed / self.total * 100) if self.total else 0.0


async def run_batch(
    db: AsyncSession,
    *,
    record_id: int | None = None,
    limit: int | None = None,
    on_record: Callable[[RecordOutcome], None] | None = None,
    on_error: Callable[[Record, Exception], None] | None = None,
) -> BatchSummary:
    """Runs pending records through the full pipeline (classify, extract, score,
    route). Selects oldest-received first so a run processes the inbox in the order
    messages actually arrived. Commits after each record so one failure doesn't roll
    back the records already done, and so `on_record` sees committed state as it's
    called. `on_record`, if given, fires immediately after each record finishes —
    that's what lets the CLI print a line per record as the batch runs rather than
    only at the end. `on_error`, if given, fires with the record and the exception
    process_record raised before the batch moves on — that's what lets the CLI show
    the full traceback for a failed record instead of just its terminal status.
    """
    query = (
        select(Record)
        .where(Record.status == RecordStatus.PENDING.value)
        .order_by(Record.received_at, Record.id)
    )
    if record_id is not None:
        query = query.where(Record.id == record_id)
    elif limit is not None:
        query = query.limit(limit)

    records = (await db.execute(query)).scalars().all()

    if record_id is not None and not records:
        existing = await db.get(Record, record_id)
        if existing is None:
            raise ValueError(f"Record {record_id} not found")
        raise ValueError(f"Record {record_id} is not pending (status={existing.status})")

    summary = BatchSummary()
    for record in records:
        try:
            # process_record already marks the record 'failed' and writes an
            # audit_log entry with the error before re-raising — the catch here
            # only keeps one bad record from stopping the rest of the batch.
            await process_record(record.id, db)
        except Exception as exc:
            if on_error is not None:
                on_error(record, exc)
        await db.commit()

        classification = (
            await db.execute(
                select(Classification)
                .where(Classification.record_id == record.id)
                .order_by(Classification.id.desc())
                .limit(1)
            )
        ).scalars().first()

        outcome = RecordOutcome(
            record_id=record.id,
            external_ref=record.external_ref,
            category=classification.category if classification else None,
            confidence=classification.confidence if classification else None,
            status=record.status,
        )
        summary.outcomes.append(outcome)
        if on_record is not None:
            on_record(outcome)

    return summary


async def compute_stats(db: AsyncSession) -> dict[str, int | float]:
    """Aggregate counts by status from current DB state — no processing. Mirrors the
    numbers a `process` run prints, so `stats` can be checked before or after a batch
    without re-running anything."""
    result = await db.execute(select(Record.status, func.count()).group_by(Record.status))
    counts = dict(result.all())

    auto_routed = counts.get(RecordStatus.AUTO_ROUTED.value, 0)
    needs_review = counts.get(RecordStatus.NEEDS_REVIEW.value, 0)
    failed = counts.get(RecordStatus.FAILED.value, 0)
    total = auto_routed + needs_review + failed

    return {
        "total": total,
        "auto_routed": auto_routed,
        "needs_review": needs_review,
        "failed": failed,
        "auto_route_pct": (auto_routed / total * 100) if total else 0.0,
    }
