"""Local settings with file-based credentials and safe representations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_host: str
    database_port: int
    password_file: Path

    def __post_init__(self) -> None:
        if self.database_host not in {"127.0.0.1", "localhost", "postgres"}:
            raise ValueError("foundation_database_must_be_local")
        if self.database_port not in {5432, 55432}:
            raise ValueError("unexpected_local_database_port")

    @classmethod
    def from_environment(cls) -> Settings:
        if os.environ.get("AGENTTRACE_ENVIRONMENT", "local_synthetic") != "local_synthetic":
            raise ValueError("foundation_supports_local_synthetic_environment_only")
        return cls(
            os.environ.get("AGENTTRACE_DATABASE_HOST", "127.0.0.1"),
            int(os.environ.get("AGENTTRACE_DATABASE_PORT", "55432")),
            Path(
                os.environ.get("AGENTTRACE_DATABASE_PASSWORD_FILE", "work/local/postgres-password")
            ),
        )

    def password(self) -> str:
        value = self.password_file.read_text().strip()
        if not 24 <= len(value) <= 128:
            raise ValueError("invalid_local_database_secret")
        return value
