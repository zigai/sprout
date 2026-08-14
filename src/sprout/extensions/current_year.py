from __future__ import annotations

import datetime as dt

from jinja2 import Environment
from jinja2.ext import Extension


class CurrentYearExtension(Extension):
    """Expose the current UTC year as a Jinja global named `current_year`."""

    def __init__(self, environment: Environment) -> None:
        super().__init__(environment)

        environment.globals["current_year"] = dt.datetime.now(tz=dt.UTC).year  # pyrefly: ignore[unsupported-operation]


__all__ = ["CurrentYearExtension"]
