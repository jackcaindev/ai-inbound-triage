from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AuditLog


async def write_audit_log(
    db: AsyncSession,
    *,
    record_id: int,
    actor: str,
    action: str,
    before: dict[str, Any] | None = None,
    after: dict[str, Any] | None = None,
) -> AuditLog:
    """audit_log is append-only — this is the only place in the codebase that writes
    to it, and it only ever inserts. Nothing updates or deletes a row here."""
    entry = AuditLog(record_id=record_id, actor=actor, action=action, before=before, after=after)
    db.add(entry)
    await db.flush()
    return entry
