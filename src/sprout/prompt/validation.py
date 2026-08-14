from __future__ import annotations

from collections.abc import Callable, Mapping

type ValidationResult = tuple[bool, str | None]
type ValidatorAnswers = Mapping[str, object]
type ValidatorFn = Callable[[str], ValidationResult]
type ContextValidatorFn = Callable[[str, ValidatorAnswers], ValidationResult]
type ValidatorType = ValidatorFn | ContextValidatorFn

__all__ = [
    "ContextValidatorFn",
    "ValidationResult",
    "ValidatorAnswers",
    "ValidatorFn",
    "ValidatorType",
]
