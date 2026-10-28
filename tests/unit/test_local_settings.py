from pathlib import Path

import pytest

from agenttrace_foundation.settings import Settings


def test_foundation_cannot_connect_to_a_remote_database():
    with pytest.raises(ValueError, match="must_be_local"):
        Settings("production.example.invalid", 5432, Path("unused"))


def test_foundation_refuses_a_production_runtime(monkeypatch):
    monkeypatch.setenv("AGENTTRACE_ENVIRONMENT", "production")
    with pytest.raises(ValueError, match="local_synthetic"):
        Settings.from_environment()
