from __future__ import annotations

import re
from pathlib import Path


def shorten_home(text: str | Path) -> str:
    """Replace the home directory with `~` wherever it appears as a whole path prefix."""
    home = str(Path.home())
    if home in ("", "/"):
        return str(text)

    return re.sub(rf"(?<![\w./-]){re.escape(home)}(?![\w.-])", "~", str(text))


__all__ = ["shorten_home"]
