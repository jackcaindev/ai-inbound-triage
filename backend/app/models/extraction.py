from typing import TYPE_CHECKING, Any

from sqlalchemy import Float, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from app.models.record import Record


class Extraction(CreatedAtMixin, Base):
    """Append-only, same rationale as Classification — never updated in place."""

    __tablename__ = "extractions"
    __table_args__ = (Index("ix_extractions_record_id", "record_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), nullable=False
    )
    schema_version: Mapped[str] = mapped_column(String(64), nullable=False)
    fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    raw_response: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    record: Mapped["Record"] = relationship("Record", back_populates="extractions")
