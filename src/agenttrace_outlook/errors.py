"""Stable safe error codes; never include source content or credentials."""


class OutlookError(RuntimeError):
    def __init__(self, code: str):
        self.code = code


class SourceError(OutlookError):
    def __init__(self, code: str, *, retryable: bool = False, retry_after: int = 0):
        super().__init__(code)
        self.retryable, self.retry_after = retryable, retry_after
        super().__init__(code)
