from __future__ import annotations

from pathlib import Path

import pytest

from sprout.cli import TemplateSource, main
from sprout.question import Question
from sprout.registry import TemplateRegistry
from sprout.style import Style
from tests.conftest import TemplateFactory


def test_top_level_help_lists_commands_and_legacy_syntax_is_rejected(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as help_exit:
        main(["--help"])

    assert help_exit.value.code == 0
    output = capsys.readouterr().out
    assert all(command in output for command in ("init", "add", "new", "list"))

    with pytest.raises(SystemExit) as legacy_exit:
        main(["owner/repo", "destination"])

    assert legacy_exit.value.code == 2


def test_init_creates_scaffold_and_refuses_existing_files(tmp_path: Path) -> None:
    root = tmp_path / "template-source"

    assert main(["init", str(root)]) == 0
    manifest = (root / "sprout.py").read_text(encoding="utf-8")
    assert 'key="project_name"' in manifest
    assert "default=destination.name" in manifest
    assert (root / "template" / "README.md.jinja").read_text(encoding="utf-8") == (
        "# {{ project_name }}\n"
    )

    with pytest.raises(SystemExit, match="refusing to overwrite"):
        main(["init", str(root)])


def test_init_preflights_all_targets_before_writing(tmp_path: Path) -> None:
    root = tmp_path / "template-source"
    root.mkdir()
    (root / "sprout.py").write_text("existing\n", encoding="utf-8")

    with pytest.raises(SystemExit, match="refusing to overwrite"):
        main(["init", str(root)])

    assert not (root / "template" / "README.md.jinja").exists()


def test_initialized_scaffold_generates_a_project(tmp_path: Path) -> None:
    root = tmp_path / "template-source"
    destination = tmp_path / "generated"
    main(["init", str(root)])

    assert main(["new", str(root), str(destination), "--project-name", "Demo"]) == 0
    assert (destination / "README.md").read_text(encoding="utf-8") == "# Demo\n"


def test_add_records_source_without_resolving_template(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    def fail_prepare(_cls: type[TemplateSource], _source: str) -> TemplateSource:
        raise AssertionError("add must not prepare the template source")

    monkeypatch.setattr(TemplateSource, "from_source", classmethod(fail_prepare))

    assert main(["add", "owner/repo", "--name", "demo"]) == 0
    entry = TemplateRegistry().find("demo")
    assert entry is not None
    assert entry.source == "owner/repo"


def test_add_prompts_with_derived_name(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.setattr("sprout.cli.supports_live_interaction", lambda: True)
    defaults: list[object] = []

    def fake_ask(question: Question, _answers: dict[str, object], _style: Style) -> str:
        default = question.default
        assert isinstance(default, str)
        defaults.append(default)

        return default

    monkeypatch.setattr("sprout.cli.ask_question", fake_ask)

    assert main(["add", "https://github.com/owner/repo.git"]) == 0
    assert defaults == ["repo"]
    assert TemplateRegistry().find("repo") is not None


def test_add_requires_name_when_interaction_is_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(SystemExit, match="--name is required"):
        main(["add", "owner/repo"])


def test_add_duplicate_requires_and_honors_confirmation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    main(["add", "owner/one", "--name", "demo"])

    with pytest.raises(SystemExit, match="interactive confirmation"):
        main(["add", "owner/two", "--name", "demo"])

    monkeypatch.setattr("sprout.cli.supports_live_interaction", lambda: True)

    monkeypatch.setattr("sprout.cli.ask_question", lambda *_args: False)

    with pytest.raises(SystemExit, match="was not changed"):
        main(["add", "owner/two", "--name", "demo"])
    declined_entry = TemplateRegistry().find("demo")
    assert declined_entry is not None
    assert declined_entry.source == "owner/one"

    monkeypatch.setattr("sprout.cli.ask_question", lambda *_args: True)

    assert main(["add", "owner/two", "--name", "demo"]) == 0
    entry = TemplateRegistry().find("demo")
    assert entry is not None
    assert entry.source == "owner/two"


def test_list_displays_entries_in_name_order(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    main(["add", "owner/zulu", "--name", "zulu"])
    main(["add", "owner/alpha", "--name", "Alpha"])
    capsys.readouterr()

    assert main(["list"]) == 0
    output = capsys.readouterr().out
    assert output.index("Alpha") < output.index("zulu")
    assert "owner/alpha" in output
    assert "owner/zulu" in output


def test_list_reports_empty_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    assert main(["list"]) == 0
    assert "No trusted templates" in capsys.readouterr().out


def test_new_help_lists_trusted_templates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    main(["add", "owner/zulu", "--name", "zulu"])
    main(["add", "owner/alpha", "--name", "Alpha"])
    capsys.readouterr()

    with pytest.raises(SystemExit) as help_exit:
        main(["new", "--help"])

    assert help_exit.value.code == 0
    output = capsys.readouterr().out
    assert "Trusted templates added with sprout add:" in output
    assert output.index("Alpha: owner/alpha") < output.index("zulu: owner/zulu")


def test_new_help_explains_how_to_add_trusted_templates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))

    with pytest.raises(SystemExit) as help_exit:
        main(["new", "--help"])

    assert help_exit.value.code == 0
    assert (
        "No trusted templates have been added. Use sprout add to add one."
        in capsys.readouterr().out
    )


def test_registered_local_alias_generates_project(
    monkeypatch: pytest.MonkeyPatch,
    make_template: TemplateFactory,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    template = make_template("questions = []")
    destination = tmp_path / "generated"
    main(["add", str(template), "--name", "demo"])

    assert main(["new", "demo", str(destination)]) == 0
    assert (destination / "README.md").is_file()


def test_registered_remote_alias_is_prepared_fresh_for_each_run(
    monkeypatch: pytest.MonkeyPatch,
    make_template: TemplateFactory,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    template = make_template("questions = []")
    main(["add", "owner/repo", "--name", "demo"])
    prepared_sources: list[str] = []
    cleanup_calls: list[str] = []

    def fake_prepare(_cls: type[TemplateSource], source: str) -> TemplateSource:
        prepared_sources.append(source)
        owner = TemplateSource(template)
        monkeypatch.setattr(owner, "close", lambda: cleanup_calls.append(source))

        return owner

    monkeypatch.setattr(TemplateSource, "from_source", classmethod(fake_prepare))

    assert main(["new", "demo", str(tmp_path / "one")]) == 0
    assert main(["new", "demo", str(tmp_path / "two")]) == 0
    assert prepared_sources == ["owner/repo", "owner/repo"]
    assert cleanup_calls == ["owner/repo", "owner/repo"]
