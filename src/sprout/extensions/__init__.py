from __future__ import annotations

from sprout.extensions.current_year import CurrentYearExtension
from sprout.extensions.environment import DEFAULT_EXTENSIONS, build_environment
from sprout.extensions.git_defaults import GitDefaultsExtension

__all__ = [
    "DEFAULT_EXTENSIONS",
    "CurrentYearExtension",
    "GitDefaultsExtension",
    "build_environment",
]
