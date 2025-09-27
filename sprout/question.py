from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any

from sprout.validators import ValidatorType


@dataclass
class Question:
    key: str
    prompt: str
    help: str = ""
    default: Any | Callable[[dict[str, Any]], Any] = None
    choices: Sequence[tuple[str, str]] | None = None
    multiselect: bool = False
    parser: Callable[[str, dict[str, Any]], Any] | None = None
    validators: Sequence[ValidatorType] = field(default_factory=list)

    def resolve_default(self, answers: dict[str, Any]) -> Any:
        if callable(self.default):
            return self.default(answers)
        return self.default


__all__ = ["Question"]
