from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Protocol


class TemplateFactory(Protocol):
    def __call__(
        self,
        manifest_source: str,
        files: Mapping[str, str] | None = None,
    ) -> Path: ...


__all__ = ["TemplateFactory"]
