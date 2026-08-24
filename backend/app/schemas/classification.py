from pydantic import BaseModel, Field


class ClassificationResult(BaseModel):
    """Structured output the LLM must return for the classify stage."""

    category: str
    confidence: float = Field(ge=0.0, le=1.0)
    reasoning: str | None = None
