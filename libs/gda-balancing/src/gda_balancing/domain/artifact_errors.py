"""Failures from authenticated Standard Schema artifact retrieval."""


class PublishedArtifactIntegrityError(RuntimeError):
    """An authenticated publication named the target but failed verification."""

    def __init__(self, message: str, *, logical_name: str | None = None) -> None:
        super().__init__(message)
        self.logical_name = logical_name


class PublishedArtifactUnavailable(LookupError):
    """No authenticated publication contains one requested exact member."""

    def __init__(self, logical_name: str, artifact_kind: str) -> None:
        super().__init__(logical_name)
        self.logical_name = logical_name
        self.artifact_kind = artifact_kind
