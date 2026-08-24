from dataclasses import dataclass

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.llm.client import call_structured
from app.models import Extraction, Record
from app.pipeline.audit import write_audit_log
from app.prompts.extract_v1 import PROMPT_VERSION, build_extract_prompt
from app.schemas.extraction import BaseExtractionFields, completeness, missing_required_fields


@dataclass
class ExtractOutcome:
    extraction: Extraction
    missing_required_fields: list[str]


async def extract_record(record: Record, category: str, db: AsyncSession) -> ExtractOutcome:
    """Two-phase: called after classify_record, using its category to pick the prompt.
    Always inserts a new extractions row — never updates an existing one."""
    system, user_message = build_extract_prompt(category, record.raw_content)

    result = await call_structured(
        model=settings.extract_model,
        system=system,
        user_message=user_message,
        response_model=BaseExtractionFields,
    )

    extraction = Extraction(
        record_id=record.id,
        schema_version=PROMPT_VERSION,
        fields=result.parsed.model_dump(),
        confidence=completeness(result.parsed),
        model=settings.extract_model,
        raw_response=result.raw_response,
    )
    db.add(extraction)
    await db.flush()

    missing = missing_required_fields(category, result.parsed)

    await write_audit_log(
        db,
        record_id=record.id,
        actor="system",
        action="extracted",
        after={"fields": extraction.fields, "missing_required": missing},
    )
    return ExtractOutcome(extraction=extraction, missing_required_fields=missing)
