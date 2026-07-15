from __future__ import annotations

from pathlib import Path

MANIFEST_SOURCE = """from pathlib import Path

from jinja2 import Environment

from sprout import Question


def questions(_env: Environment, destination: Path) -> list[Question]:
    return [
        Question(
            key="project_name",
            prompt="Project name",
            default=destination.name,
        ),
    ]
"""

README_TEMPLATE = "# {{ project_name }}\n"


def create_template_scaffold(directory: str | Path = ".") -> tuple[Path, ...]:
    root = Path(directory).expanduser().resolve()
    if root.is_file():
        raise SystemExit(f"scaffold destination {root} is a file.")

    files = (
        (root / "sprout.py", MANIFEST_SOURCE),
        (root / "template" / "README.md.jinja", README_TEMPLATE),
    )
    existing = [path for path, _content in files if path.exists()]
    if existing:
        formatted = ", ".join(str(path) for path in existing)
        raise SystemExit(f"refusing to overwrite existing scaffold files: {formatted}")

    for path, content in files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")

    return tuple(path for path, _content in files)


__all__ = ["create_template_scaffold"]
