"""Typed failures shared by use cases and invocation adapters."""


class UnreadableInputError(Exception):
    """The named input could not be read before domain admission."""


class UsageError(Exception):
    """An invocation violated a declared use-case contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
