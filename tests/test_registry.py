from __future__ import annotations

import json
from pathlib import Path

import pytest

from sprout.registry import (
    TemplateRegistry,
    TrustedTemplate,
    default_registry_path,
    derive_template_name,
    normalize_template_source,
)


def test_default_registry_path_honors_xdg_config_home(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))

    assert default_registry_path() == tmp_path / "sprout" / "templates.json"


def test_registry_round_trips_entries_in_name_order(tmp_path: Path) -> None:
    path = tmp_path / "config" / "templates.json"
    registry = TemplateRegistry(path)

    registry.save(TrustedTemplate(name="zulu", source="owner/zulu"))
    registry.save(TrustedTemplate(name="Alpha", source="owner/alpha"))

    assert registry.entries() == (
        TrustedTemplate(name="Alpha", source="owner/alpha"),
        TrustedTemplate(name="zulu", source="owner/zulu"),
    )
    assert json.loads(path.read_text(encoding="utf-8")) == {
        "version": 1,
        "templates": [
            {"name": "Alpha", "source": "owner/alpha"},
            {"name": "zulu", "source": "owner/zulu"},
        ],
    }
    assert list(path.parent.glob(f".{path.name}.*")) == []


@pytest.mark.parametrize(
    "config",
    [
        [],
        {"version": 2, "templates": []},
        {"version": 1, "templates": "invalid"},
        {"version": 1, "templates": [{"name": "demo"}]},
        {
            "version": 1,
            "templates": [
                {"name": "demo", "source": "one"},
                {"name": "demo", "source": "two"},
            ],
        },
    ],
)
def test_registry_rejects_invalid_persisted_config(tmp_path: Path, config: object) -> None:
    path = tmp_path / "templates.json"
    path.write_text(json.dumps(config), encoding="utf-8")

    with pytest.raises(SystemExit):
        TemplateRegistry(path).entries()


def test_registry_rejects_malformed_json(tmp_path: Path) -> None:
    path = tmp_path / "templates.json"
    path.write_text("{invalid", encoding="utf-8")

    with pytest.raises(SystemExit, match="failed to read template registry"):
        TemplateRegistry(path).entries()


def test_template_source_normalization_and_name_derivation(tmp_path: Path) -> None:
    local = tmp_path / "local-template"
    local.mkdir()

    assert normalize_template_source(str(local)) == str(local.resolve())
    assert normalize_template_source("owner/repo") == "owner/repo"
    assert derive_template_name(str(local)) == "local-template"
    assert derive_template_name("owner/repo") == "repo"
    assert derive_template_name("https://github.com/owner/repo.git") == "repo"
    assert derive_template_name("git@github.com:owner/repo.git") == "repo"


def test_template_name_derivation_supports_windows_paths() -> None:
    assert derive_template_name(r"C:\templates\local-template") == "local-template"
