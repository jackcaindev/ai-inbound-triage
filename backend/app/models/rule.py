from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, TimestampMixin

if TYPE_CHECKING:
    from app.models.routing_decision import RoutingDecision


class Rule(TimestampMixin, Base):
    """Mutable config, unlike the inference tables — a rule can be edited or
    deactivated in place. First-match-wins evaluation order is by priority ascending."""

    __tablename__ = "rules"
    __table_args__ = (Index("ix_rules_active_priority", "active", "priority"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    priority: Mapped[int] = mapped_column(Integer, nullable=False)
    conditions: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False)
    destination: Mapped[str] = mapped_column(String(128), nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    routing_decisions: Mapped[list["RoutingDecision"]] = relationship(
        "RoutingDecision", back_populates="rule"
    )
