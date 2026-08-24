from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.audit_log import AuditLog
    from app.models.classification import Classification
    from app.models.eval_example import EvalExample
    from app.models.extraction import Extraction
    from app.models.routing_decision import RoutingDecision
    from app.models.source import Source


class Record(TimestampMixin, Base):
    __tablename__ = "records"
    __table_args__ = (
        UniqueConstraint("source_id", "external_ref", name="uq_records_source_id_external_ref"),
        Index("ix_records_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    source_id: Mapped[int] = mapped_column(
        ForeignKey("sources.id", ondelete="RESTRICT"), nullable=False
    )
    external_ref: Mapped[str] = mapped_column(String(255), nullable=False)
    raw_content: Mapped[str] = mapped_column(Text, nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)

    source: Mapped["Source"] = relationship("Source", back_populates="records")
    classifications: Mapped[list["Classification"]] = relationship(
        "Classification", back_populates="record", cascade="all, delete-orphan"
    )
    extractions: Mapped[list["Extraction"]] = relationship(
        "Extraction", back_populates="record", cascade="all, delete-orphan"
    )
    routing_decisions: Mapped[list["RoutingDecision"]] = relationship(
        "RoutingDecision", back_populates="record", cascade="all, delete-orphan"
    )
    audit_log: Mapped[list["AuditLog"]] = relationship(
        "AuditLog", back_populates="record", cascade="all, delete-orphan"
    )
    eval_examples: Mapped[list["EvalExample"]] = relationship(
        "EvalExample", back_populates="record", cascade="all, delete-orphan"
    )
