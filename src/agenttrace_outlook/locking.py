"""An OS lock held before SQLite opens; a crash releases it without a TTL delay."""

import os
import sys
from pathlib import Path

if sys.platform == "win32":
    import msvcrt
else:
    import fcntl

from .errors import OutlookError


class ProcessLock:
    def __init__(self, path: Path):
        self.fd: int | None = None
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
            if os.fstat(self.fd).st_size == 0:
                os.write(self.fd, b"\0")
            os.lseek(self.fd, 0, os.SEEK_SET)
            if sys.platform == "win32":
                msvcrt.locking(self.fd, msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            if self.fd is not None:
                os.close(self.fd)
                self.fd = None
            raise OutlookError("runtime_already_running_or_lock_unavailable") from None

    def close(self) -> None:
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None
