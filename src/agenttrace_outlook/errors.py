"""Stable safe error codes; never include source content or credentials."""


class OutlookError(RuntimeError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(code)
