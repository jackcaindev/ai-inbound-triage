from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.client import call_structured
from app.models import Classification, Record
from app.pipeline.audit import write_audit_log
from app.prompts.classify_v1 import PROMPT_VERSION, build_classify_prompt
from app.schemas.classification import ClassificationResult


async def classify_record(
    record: Record, categories: list[dict[str, Any]], db: AsyncSession
) -> Classification:
    """Always inserts a new classifications row — never updates an existing one. A
    re-run with a new prompt_version creates another row, which is what makes
    prompt-version comparison possible."""
    system, user_message = build_classify_prompt(categories, record.raw_content)

    result = await call_structured(
        model=settings.classify_model,
        system=system,
        user_message=user_message,
        response_model=ClassificationResult,
    )

    classification = Classification(
        record_id=record.id,
        category=result.parsed.category,
        confidence=result.parsed.confidence,
        model=settings.classify_model,
        prompt_version=PROMPT_VERSION,
        raw_response=result.raw_response,
        latency_ms=result.latency_ms,
    )
    db.add(classification)
    await db.flush()

    await write_audit_log(
        db,
        record_id=record.id,
        actor="system",
        action="classified",
        after={"category": classification.category, "confidence": classification.confidence},
    )
    return classification
