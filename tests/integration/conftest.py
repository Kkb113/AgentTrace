import os
from uuid import uuid4

import pytest
from psycopg import sql

from agenttrace_foundation.database import Database
from agenttrace_foundation.settings import Settings


@pytest.fixture
def database():
    if os.environ.get("AGENTTRACE_INTEGRATION") != "1":
        pytest.skip("Run the explicit integration command with the local PostgreSQL stack")
    base = Database(Settings.from_environment())
    schema = "test_" + uuid4().hex
    with base.connect() as connection:
        connection.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    isolated = Database(base.settings, schema=schema)
    isolated.migrate()
    try:
        yield isolated
    finally:
        # Only this test-created schema in the local synthetic database is disposable.
        with base.connect() as connection:
            connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
