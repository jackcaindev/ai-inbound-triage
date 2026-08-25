from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, CreatedAtMixin

if TYPE_CHECKING:
    from app.models.record import Record


class EvalExample(CreatedAtMixin, Base):
    __tablename__ = "eval_examples"

    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(
        ForeignKey("records.id", ondelete="CASCADE"), nullable=False
    )
    expected_category: Mapped[str] = mapped_column(String(64), nullable=False)
    expected_fields: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False)

    record: Mapped["Record"] = relationship("Record", back_populates="eval_examples")
