import os
import subprocess
import sys

import pytest
from pydantic import ValidationError

from app.config import BACKEND_DIR, REPO_ROOT, Settings


def _env_without_key() -> dict[str, str]:
    env = dict(os.environ)
    env.pop("ANTHROPIC_API_KEY", None)
    return env


def _load_key_with_cwd(cwd: str) -> str:
    """Runs a fresh interpreter with the given cwd so we exercise the same
    module-import path the real app takes, rather than the already-imported
    settings singleton in this test process."""
    result = subprocess.run(
        [sys.executable, "-c", "from app.config import settings; print(settings.anthropic_api_key)"],
        cwd=cwd,
        env={**_env_without_key(), "PYTHONPATH": str(BACKEND_DIR)},
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout.strip()


def test_loads_api_key_when_run_from_repo_root() -> None:
    assert _load_key_with_cwd(str(REPO_ROOT)) != ""


def test_loads_api_key_when_run_from_backend_dir() -> None:
    assert _load_key_with_cwd(str(BACKEND_DIR)) != ""


def test_missing_api_key_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)

    with pytest.raises(ValidationError, match="anthropic_api_key"):
        Settings(_env_file=None)
