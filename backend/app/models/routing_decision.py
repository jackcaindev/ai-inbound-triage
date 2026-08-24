from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from app.models.record import Record
    from app.models.rule import Rule


class RoutingDecision(CreatedAtMixin, Base):
    __tablename__ = "routing_decisions"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), nullable=False
    )
    rule_id: Mapped[int | None] = mapped_column(
        ForeignKey("rules.id", ondelete="SET NULL"), nullable=True
    )
    destination: Mapped[str] = mapped_column(String(128), nullable=False)
    decided_by: Mapped[str] = mapped_column(String(16), nullable=False)
    reviewer_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    record: Mapped["Record"] = relationship("Record", back_populates="routing_decisions")
    rule: Mapped["Rule | None"] = relationship("Rule", back_populates="routing_decisions")
