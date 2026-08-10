"""Typed failures from authenticated Model explanation retrieval."""


class ModelInspectAdmissionError(ValueError):
    """A supplied build receipt or its committed set failed admission."""

    def __init__(self, code: str, subject: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.subject = subject
        self.message = message
