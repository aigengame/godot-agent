"""CLI-specific failure values and mappings."""

from gda_balancing.domain.publication_types import PublicationError


class UsageError(Exception):
    """An invocation violated a declared CLI usage contract."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def publication_usage_error(error: PublicationError) -> UsageError:
    """Map a Domain publication failure onto the declared CLI usage family."""
    code = {
        "unsafe_path": "argument_conflict",
        "output_unavailable": "unwritable_output",
        "invocation_key_conflict": "invocation_key_conflict",
        "invalid_configuration": "invalid_argument",
    }[error.reason]
    return UsageError(code, error.message)
