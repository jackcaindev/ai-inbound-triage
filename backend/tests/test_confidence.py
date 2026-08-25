from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Classification, Record
from app.models.enums import RecordStatus
from app.pipeline.confidence import classification_below_threshold
from app.pipeline.process import process_record
from tests.conftest import FakeLLMController


def test_classification_below_threshold_is_true_below_cutoff() -> None:
    classification = Classification(
        record_id=1,
        category="new_inquiry",
        confidence=0.5,
        model="test",
        prompt_version="v1",
        raw_response={},
        latency_ms=1,
    )

    assert classification_below_threshold(classification, threshold=0.85) is True


def test_classification_below_threshold_ignores_extraction_confidence() -> None:
    """Extraction completeness never factors into this gate, however sparse it is."""
    classification = Classification(
        record_id=1,
        category="new_inquiry",
        confidence=0.97,
        model="test",
        prompt_version="v1",
        raw_response={},
        latency_ms=1,
    )

    assert classification_below_threshold(classification, threshold=0.85) is False


async def test_low_confidence_record_lands_in_needs_review(
    db: AsyncSession, make_record, fake_llm: FakeLLMController
) -> None:
    record: Record = await make_record(raw_content="Not sure what this is about, kind of vague.")
    fake_llm.set_classification(category="new_inquiry", confidence=0.4)
    fake_llm.set_extraction(
        contact_name=None,
        company=None,
        requested_action=None,
        urgency=None,
        dates_mentioned=[],
        dollar_amounts_mentioned=[],
    )

    result = await process_record(record.id, db)

    assert result.status == RecordStatus.NEEDS_REVIEW.value
