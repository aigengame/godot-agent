"""Typed input failures shared by use cases and invocation adapters."""


class UnreadableInputError(Exception):
    """The named input could not be read before domain admission."""
