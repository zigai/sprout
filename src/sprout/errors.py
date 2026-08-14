from __future__ import annotations


class SproutError(Exception):
    """Base class for expected Sprout operational failures."""

    message: str

    def __init__(self, message: str) -> None:
        self.message = message
        super().__init__(message)


class SproutGenerationError(SproutError):
    """Raised when project generation cannot complete."""


class SproutManifestError(SproutError):
    """Raised when a template manifest is missing or invalid."""


class SproutPromptError(SproutError):
    """Raised when noninteractive answer collection fails."""


class SproutRegistryError(SproutError):
    """Raised when the trusted-template registry cannot be read or updated."""


class SproutScaffoldError(SproutError):
    """Raised when a template scaffold cannot be created."""


class SproutTemplateSourceError(SproutError):
    """Raised when a local or remote template source cannot be resolved."""


__all__ = [
    "SproutError",
    "SproutGenerationError",
    "SproutManifestError",
    "SproutPromptError",
    "SproutRegistryError",
    "SproutScaffoldError",
    "SproutTemplateSourceError",
]
