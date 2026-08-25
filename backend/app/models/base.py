from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

__all__ = ["Base", "TimestampMixin", "CreatedAtMixin"]


class CreatedAtMixin:
    """For append-only tables: classifications, extractions, audit_log. No updated_at —
    a row is never mutated after insert, so there is nothing to timestamp."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class TimestampMixin(CreatedAtMixin):
    """For mutable rows: sources, records, rules."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
