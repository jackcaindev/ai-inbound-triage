from app.models import Classification


def classification_below_threshold(classification: Classification, threshold: float) -> bool:
    """Gates on the model's self-reported classification confidence alone.

    Extraction confidence measures field completeness, not correctness of the
    category call — categories like spam are legitimately sparse, so blending
    extraction confidence in here previously dragged a confident, correct
    classification into review (and, worse, skipped rule evaluation on the way).
    Sparse extractions are handled separately, by the required-fields check.
    """
    return classification.confidence < threshold
