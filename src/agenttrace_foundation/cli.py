"""Development entry points; no email execution or public ingestion endpoints."""

from __future__ import annotations

import argparse
import json
import os
import signal
import threading
from pathlib import Path
from uuid import NAMESPACE_URL, uuid4, uuid5

import uvicorn
from agenttrace_contracts import DetectionJob

from .api import create_app
from .database import Database, StorageUnavailable
from .database_access import configure_local_roles
from .queue import DevelopmentQueue
from .service import process_one
from .settings import Settings
from .store import DecisionStore


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("migrate")
    server = sub.add_parser("api")
    server.add_argument(
        "--container", action="store_true", help="Bind inside a loopback-published container"
    )
    worker = sub.add_parser("worker")
    worker.add_argument("--role", choices=["attribution", "content"], required=True)
    worker.add_argument("--repository", type=Path, default=Path.cwd())
    health = sub.add_parser("health")
    health.add_argument("--role", choices=["attribution", "content"], required=True)
    smoke = sub.add_parser("enqueue-example")
    smoke.add_argument("--key", default=None)
    arguments = parser.parse_args()
    try:
        database = Database(Settings.from_environment())
        if arguments.command == "migrate":
            database.migrate()
            role_directory = os.environ.get("AGENTTRACE_DATABASE_ROLE_SECRET_DIRECTORY")
            if role_directory:
                configure_local_roles(database, Path(role_directory))
            print(json.dumps({"status": "migrated", "schema_version": 1}))
        elif arguments.command == "api":
            uvicorn.run(
                create_app(database),
                host="0.0.0.0" if arguments.container else "127.0.0.1",
                port=8080,
                access_log=False,
            )
        elif arguments.command == "health":
            return 0 if DecisionStore(database).role_healthy(arguments.role) else 1
        elif arguments.command == "enqueue-example":
            key = arguments.key or str(uuid4())
            job_id = DevelopmentQueue(database, "agent-evidence").enqueue(
                DetectionJob(
                    fixture_ref="authored_contract_example", message_ref="synthetic-example"
                ),
                key,
            )
            print(
                json.dumps(
                    {
                        "job_id": str(job_id),
                        "decision_id": str(
                            uuid5(NAMESPACE_URL, "agenttrace-local-job:" + str(job_id))
                        ),
                    }
                )
            )
        else:
            stopping = threading.Event()
            signal.signal(signal.SIGTERM, lambda *_: stopping.set())
            signal.signal(signal.SIGINT, lambda *_: stopping.set())
            store = DecisionStore(database)
            print(
                json.dumps(
                    {
                        "status": "worker_started",
                        "role": arguments.role,
                        "content_model": "not_installed",
                    }
                ),
                flush=True,
            )
            while not stopping.is_set():
                store.heartbeat(arguments.role)
                if arguments.role == "attribution":
                    process_one(database, arguments.repository)
                # The content process does not consume/acknowledge work without a configured scorer.
                stopping.wait(1)
        return 0
    except (StorageUnavailable, OSError, ValueError):
        print(json.dumps({"status": "failed", "reason": "local_foundation_operation_failed"}))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
