"""Failures from authenticated Standard Schema artifact retrieval."""


class PublishedArtifactIntegrityError(RuntimeError):
    """An authenticated publication named the target but failed verification."""
