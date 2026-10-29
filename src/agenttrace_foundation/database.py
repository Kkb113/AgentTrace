"""PostgreSQL persistence; connection strings and bodies are never logged."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from typing import Any

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from .settings import Settings


class StorageUnavailable(RuntimeError):
    """Safe storage error: driver frames can contain connection credentials."""


class Database:
    def __init__(self, settings: Settings, *, schema: str = "public"):
        if schema != "public" and not (
            schema.startswith("test_") and len(schema) == 37 and schema[5:].isalnum()
        ):
            raise ValueError("invalid_local_schema")
        self.settings = settings
        self.schema = schema

    @contextmanager
    def connect(self) -> Iterator[psycopg.Connection[dict[str, Any]]]:
        try:
            with psycopg.connect(
                host=self.settings.database_host,
                port=self.settings.database_port,
                dbname="agenttrace",
                user=self.settings.database_user,
                password=self.settings.password(),
                connect_timeout=5,
                row_factory=dict_row,
            ) as connection:
                connection.execute(
                    sql.SQL("SET search_path TO {}").format(sql.Identifier(self.schema))
                )
                yield connection
        except psycopg.Error:
            raise StorageUnavailable("local_database_operation_failed") from None

    def migrate(self) -> None:
        with self.connect() as connection:
            for name in ("schema.sql", "ingestion.sql", "ledger.sql"):
                source = files("agenttrace_foundation").joinpath("migrations/" + name).read_text()
                connection.execute(source, prepare=False)

    def healthy(self) -> bool:
        try:
            with self.connect() as connection:
                row = connection.execute("SELECT version FROM foundation_schema").fetchone()
                return row is not None and row["version"] == 1
        except (StorageUnavailable, OSError, ValueError):
            return False
