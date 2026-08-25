from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from app.models.record import Record


class Classification(CreatedAtMixin, Base):
    """Append-only: a re-run with a new prompt_version inserts a new row, it never
    updates an existing one. This is what makes prompt-version comparison possible."""

    __tablename__ = "classifications"
    __table_args__ = (Index("ix_classifications_record_id", "record_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), nullable=False
    )
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(64), nullable=False)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    latency_ms: Mapped[int] = mapped_column(Integer, nullable=False)

    record: Mapped["Record"] = relationship("Record", back_populates="classifications")
