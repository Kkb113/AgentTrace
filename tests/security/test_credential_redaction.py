import traceback
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import psycopg
import pytest

from agenttrace_foundation.database import Database, StorageUnavailable
from agenttrace_foundation.settings import Settings


def test_driver_exception_cannot_print_a_connection_secret():
    sentinel = uuid4().hex
    settings = Settings("127.0.0.1", 55432, Path("unused"))
    database = Database(settings)
    with patch.object(Settings, "password", return_value=sentinel):
        with patch("psycopg.connect", side_effect=psycopg.OperationalError(sentinel)):
            with pytest.raises(StorageUnavailable) as failure:
                with database.connect():
                    pass
    rendered = "".join(traceback.format_exception(failure.value))
    assert sentinel not in rendered
    assert "OperationalError" not in rendered
