from app.models import Classification, Extraction

# Below this fraction of populated base fields, the extraction is "mostly empty".
EXTRACTION_COMPLETENESS_FLOOR = 0.5
LOW_COMPLETENESS_CONFIDENCE_CAP = 0.5


def compute_confidence(classification: Classification, extraction: Extraction) -> float:
    """Starts from the model's self-reported classification confidence. If the
    extraction came back mostly empty, cap confidence so the record is more likely to
    land in review — a category the model is confident about but couldn't back up with
    any actual fields is exactly the case a human should look at."""
    base = classification.confidence
    if extraction.confidence < EXTRACTION_COMPLETENESS_FLOOR:
        return min(base, LOW_COMPLETENESS_CONFIDENCE_CAP)
    return base
