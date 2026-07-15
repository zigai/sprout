from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

CONFIG_VERSION = 1
type JsonScalar = None | bool | int | float | str
type JsonValue = JsonScalar | list[JsonValue] | dict[str, JsonValue]


@dataclass(frozen=True)
class TrustedTemplate:
    name: str
    source: str

    def __post_init__(self) -> None:
        if not self.name or self.name != self.name.strip():
            raise ValueError("template name must be a non-empty trimmed string")
        if not self.source or self.source != self.source.strip():
            raise ValueError("template source must be a non-empty trimmed string")


class TemplateRegistry:
    """Persist and resolve user-trusted template aliases."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_registry_path()

    def entries(self) -> tuple[TrustedTemplate, ...]:
        return tuple(sorted(self._load(), key=lambda entry: entry.name.casefold()))

    def find(self, name: str) -> TrustedTemplate | None:
        return next((entry for entry in self._load() if entry.name == name), None)

    def save(self, entry: TrustedTemplate) -> None:
        entries_by_name = {item.name: item for item in self._load()}
        entries_by_name[entry.name] = entry
        entries = sorted(entries_by_name.values(), key=lambda item: item.name.casefold())
        self._write(entries)

    def _load(self) -> list[TrustedTemplate]:
        if not self.path.exists():
            return []

        try:
            raw_config: JsonValue = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
            raise SystemExit(f"failed to read template registry {self.path}: {e}") from e

        return _parse_config(raw_config, self.path)

    def _write(self, entries: list[TrustedTemplate]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        config = {
            "version": CONFIG_VERSION,
            "templates": [{"name": entry.name, "source": entry.source} for entry in entries],
        }
        temp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                delete=False,
            ) as file:
                json.dump(config, file, indent=2)
                file.write("\n")
                temp_path = Path(file.name)

            temp_path.replace(self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)


def default_registry_path() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME", "").strip()
    root = Path(config_home).expanduser() if config_home else Path.home() / ".config"

    return root / "sprout" / "templates.json"


def normalize_template_name(name: str) -> str:
    normalized = name.strip()
    if not normalized:
        raise SystemExit("template name must not be empty.")

    return normalized


def normalize_template_source(source: str) -> str:
    normalized = source.strip()
    if not normalized:
        raise SystemExit("template source must not be empty.")

    candidate = Path(normalized).expanduser()
    if candidate.exists() or _is_explicit_local_path(normalized):
        return str(candidate.resolve())

    return normalized


def derive_template_name(source: str) -> str:
    cleaned = source.strip().rstrip("/\\")
    if cleaned.startswith("git@") and ":" in cleaned:
        cleaned = cleaned.rsplit(":", maxsplit=1)[1]
    elif "://" in cleaned:
        cleaned = cleaned.split("?", maxsplit=1)[0].split("#", maxsplit=1)[0]

    source_path = PureWindowsPath(cleaned) if "\\" in cleaned else Path(cleaned)
    name = source_path.name.removesuffix(".git").strip()
    if not name:
        raise SystemExit("could not derive a template name; provide --name.")

    return name


def _is_explicit_local_path(source: str) -> bool:
    return Path(source).is_absolute() or source.startswith(("./", "../", "~/"))


def _parse_config(raw_config: JsonValue, path: Path) -> list[TrustedTemplate]:
    if not isinstance(raw_config, dict):
        raise SystemExit(f"template registry {path} must contain a JSON object.")

    version = raw_config.get("version")
    if version != CONFIG_VERSION:
        raise SystemExit(
            f"template registry {path} uses unsupported version {version!r}; "
            f"expected {CONFIG_VERSION}."
        )

    raw_entries = raw_config.get("templates")
    if not isinstance(raw_entries, list):
        raise SystemExit(f"template registry {path} must contain a templates list.")

    entries: list[TrustedTemplate] = []
    names: set[str] = set()

    for index, raw_entry in enumerate(raw_entries):
        if not isinstance(raw_entry, dict):
            raise SystemExit(f"template registry entry {index} in {path} must be an object.")

        name = raw_entry.get("name")
        source = raw_entry.get("source")
        if not isinstance(name, str) or not isinstance(source, str):
            raise SystemExit(
                f"template registry entry {index} in {path} must contain string name and source fields."
            )

        try:
            entry = TrustedTemplate(name=name, source=source)
        except ValueError as e:
            raise SystemExit(f"invalid template registry entry {index} in {path}: {e}") from e

        if entry.name in names:
            raise SystemExit(f"template registry {path} contains duplicate name {entry.name!r}.")

        names.add(entry.name)
        entries.append(entry)

    return entries


__all__ = [
    "TemplateRegistry",
    "TrustedTemplate",
    "default_registry_path",
    "derive_template_name",
    "normalize_template_name",
    "normalize_template_source",
]
