import enum


class SourceType(str, enum.Enum):
    CSV = "csv"
    SHEET = "sheet"
    WEBHOOK = "webhook"


class RecordStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    AUTO_ROUTED = "auto_routed"
    NEEDS_REVIEW = "needs_review"
    RESOLVED = "resolved"
    FAILED = "failed"


class DecidedBy(str, enum.Enum):
    SYSTEM = "system"
    HUMAN = "human"


class EvalSource(str, enum.Enum):
    SEEDED = "seeded"
    HUMAN_CORRECTION = "human_correction"
