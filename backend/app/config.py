from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=REPO_ROOT / ".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://postgres:postgres@localhost:5432/triage"
    anthropic_api_key: str

    confidence_threshold: float = 0.85

    categories_path: Path = BACKEND_DIR / "config" / "categories.yaml"

    classify_prompt_version: str = "classify_v1"
    extract_prompt_version: str = "extract_v1"
    classify_model: str = "claude-sonnet-5"
    extract_model: str = "claude-sonnet-5"

    log_level: str = "INFO"


settings = Settings()
