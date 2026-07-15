from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment

from sprout.cli import (
    Manifest,
    PreparedTemplate,
    TemplateSource,
    _build_cli_parser,
    _consume_optional_value,
    _extract_template_destination,
    _flag_from_question_key,
    _format_question_help,
    _run_generate,
    _sanitize_question_key,
    main,
)
from sprout.question import Question


def _prepared_template(
    questions: list[Question],
    *,
    cli_boolean_style: str = "flags",
) -> PreparedTemplate:
    return PreparedTemplate(
        template_src="template",
        source=TemplateSource(Path()),
        manifest=Manifest(questions=questions, cli_boolean_style=cli_boolean_style),
        questions=questions,
    )


def test_consume_optional_value_variants() -> None:
    args = ["--name", "value", "template", "dest"]
    assert _consume_optional_value(args, 0) == 2

    args = ["--name=value", "template", "dest"]
    assert _consume_optional_value(args, 0) == 1

    args = ["--force", "template", "dest"]
    assert _consume_optional_value(args, 0) == 1


def test_extract_template_destination_ignores_optional_arguments() -> None:
    template, destination = _extract_template_destination(
        ["--custom", "x", "--force", "my-template", "my-destination"]
    )

    assert template == "my-template"
    assert destination == Path("my-destination").expanduser().resolve()


def test_sanitize_question_key_and_flag_generation() -> None:
    assert _sanitize_question_key("project-name") == "project_name"
    assert _sanitize_question_key("123name") == "q_123name"
    assert _flag_from_question_key("Project_Name!") == "project-name"


def test_format_question_help_keeps_prompt_and_multiselect_note() -> None:
    question = Question(
        key="workflow",
        prompt="Workflow",
        help="Pick one",
        choices=[("tests", "Tests"), ("lint", "Lint")],
        multiselect=True,
    )

    message = _format_question_help(question)

    assert "Workflow - Pick one" in message
    assert "choices:" not in message
    assert "multiple values allowed" in message


def test_build_cli_parser_help_shows_choices_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = _build_cli_parser(
        _prepared_template([Question(key="kind", prompt="Kind", choices=[("lib", "Library")])])
    )

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["new", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert help_text.count("choices: lib") == 1


def test_build_cli_parser_adds_question_flags() -> None:
    questions = [
        Question(key="name", prompt="Project name"),
        Question(key="kind", prompt="Kind", choices=[("lib", "Library")]),
        Question(
            key="dynamic",
            prompt="Dynamic",
            choices=lambda _answers: [("x", "X")],
        ),
        Question(key="tags", prompt="Tags", multiselect=True),
        Question(key="force", prompt="Reserved key should be skipped"),
    ]
    parser = _build_cli_parser(_prepared_template(questions))

    parsed, _ = parser.parse_known_args(
        [
            "new",
            "template",
            "dest",
            "--name",
            "demo",
            "--kind",
            "lib",
            "--dynamic",
            "anything",
            "--tags",
            "a",
            "--tags",
            "b",
            "--force",
        ]
    )

    assert parsed.new.name == "demo"
    assert parsed.new.kind == "lib"
    assert parsed.new.dynamic == "anything"
    assert parsed.new.tags == ["a", "b"]
    assert parsed.new.force is True


def test_build_cli_parser_enforces_static_choices() -> None:
    parser = _build_cli_parser(
        _prepared_template([Question(key="kind", prompt="Kind", choices=[("lib", "Library")])])
    )

    with pytest.raises(SystemExit):
        parser.parse_known_args(["new", "template", "dest", "--kind", "tool"])


def test_build_cli_parser_defaults_yes_no_questions_to_boolean_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = _build_cli_parser(
        _prepared_template([Question.yes_no(key="include_license", prompt="Include license?")])
    )

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["new", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    parsed_yes = parser.parse_args(["new", "template", "dest", "--include-license"])
    parsed_no = parser.parse_args(["new", "template", "dest", "--no-include-license"])

    assert parsed_yes.include_license == "yes"
    assert parsed_no.include_license == "no"
    assert "--include-license" in help_text
    assert "--no-include-license" in help_text
    assert "choices: yes, no" not in help_text


def test_build_cli_parser_boolean_flags_are_mutually_exclusive() -> None:
    parser = _build_cli_parser(
        _prepared_template([Question.yes_no(key="include_license", prompt="Include license?")])
    )

    with pytest.raises(SystemExit):
        parser.parse_args(["new", "template", "dest", "--include-license", "--no-include-license"])


def test_build_cli_parser_rejects_yes_no_value_in_boolean_flags_mode() -> None:
    parser = _build_cli_parser(
        _prepared_template([Question.yes_no(key="include_license", prompt="Include license?")])
    )

    with pytest.raises(SystemExit):
        parser.parse_args(["new", "template", "dest", "--include-license", "no"])


def test_build_cli_parser_supports_manifest_yes_no_boolean_style(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = _build_cli_parser(
        _prepared_template(
            [Question.yes_no(key="include_license", prompt="Include license?")],
            cli_boolean_style="yes-no",
        )
    )

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["new", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    parsed = parser.parse_args(["new", "template", "dest", "--include-license", "no"])

    assert parsed.new.include_license == "no"
    assert "--include-license" in help_text
    assert "--no-include-license" not in help_text
    assert "choices: yes, no" in help_text


def test_main_passes_cli_answers_to_run_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    questions = [Question(key="name", prompt="Project name")]
    cleanup_called = {"value": False}

    source = TemplateSource(Path())
    monkeypatch.setattr(source, "close", lambda: cleanup_called.update(value=True))
    prepared = PreparedTemplate(
        template_src="template",
        source=source,
        manifest=Manifest(questions=questions),
        questions=questions,
    )

    monkeypatch.setattr("sprout.cli._load_questions_for_cli", lambda *_args: prepared)

    captured: dict[str, object] = {}

    def fake_run_generate(
        template: str,
        destination: str | Path,
        *,
        force: bool,
        initial_answers: dict[str, object] | None,
        prepared: PreparedTemplate | None,
    ) -> int:
        captured["template"] = template
        captured["destination"] = str(destination)
        captured["force"] = force
        captured["initial_answers"] = dict(initial_answers or {})
        captured["prepared"] = prepared

        return 7

    monkeypatch.setattr("sprout.cli._run_generate", fake_run_generate)

    result = main(["new", "template", "destination", "--name", "sample"])

    assert result == 7
    assert captured["initial_answers"] == {"name": "sample"}
    assert cleanup_called["value"] is True


def test_main_template_only_help_preloads_questions(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    questions = [Question(key="name", prompt="Project name")]
    cleanup_called = {"value": False}
    captured: dict[str, object] = {}

    source = TemplateSource(Path())
    monkeypatch.setattr(source, "close", lambda: cleanup_called.update(value=True))
    prepared = PreparedTemplate(
        template_src="template",
        source=source,
        manifest=Manifest(questions=questions),
        questions=questions,
    )

    def fake_load_questions_for_cli(template_src: str, destination: Path) -> PreparedTemplate:
        captured["template_src"] = template_src
        captured["destination"] = destination

        return prepared

    monkeypatch.setattr("sprout.cli._load_questions_for_cli", fake_load_questions_for_cli)

    with pytest.raises(SystemExit) as exit_info:
        main(["new", "template", "--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--name NAME" in output
    assert captured["template_src"] == "template"
    assert captured["destination"] == (Path.cwd() / "__sprout_help_destination__").resolve()
    assert cleanup_called["value"] is True


def test_main_template_only_help_falls_back_to_base_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_load_questions_for_cli(_template_src: str, _destination: Path) -> PreparedTemplate:
        raise SystemExit("bad template questions")

    monkeypatch.setattr("sprout.cli._load_questions_for_cli", fake_load_questions_for_cli)

    with pytest.raises(SystemExit) as exit_info:
        main(["new", "template", "--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--force" in output
    assert "sprout new <template> <destination> --help" in output


def test_main_destination_help_uses_real_destination(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    questions = [Question(key="name", prompt="Project name")]
    captured: dict[str, object] = {}

    def fake_load_questions_for_cli(template_src: str, destination: Path) -> PreparedTemplate:
        captured["template_src"] = template_src
        captured["destination"] = destination

        return _prepared_template(questions)

    monkeypatch.setattr("sprout.cli._load_questions_for_cli", fake_load_questions_for_cli)

    with pytest.raises(SystemExit) as exit_info:
        main(["new", "template", "destination", "--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--name NAME" in output
    assert captured["template_src"] == "template"
    assert captured["destination"] == Path("destination").expanduser().resolve()


def test_run_generate_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = Manifest(questions=[])
    cleaned = {"value": False}
    source = TemplateSource(Path())
    monkeypatch.setattr(source, "close", lambda: cleaned.update(value=True))

    monkeypatch.setattr(
        TemplateSource,
        "from_source",
        classmethod(lambda _cls, _template: source),
    )
    monkeypatch.setattr("sprout.cli._load_manifest", lambda _template_dir: manifest)

    def fake_execute_manifest(*_args: object, **_kwargs: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr("sprout.cli.execute_manifest", fake_execute_manifest)

    exit_code = _run_generate(
        "template",
        Path(),
        force=False,
        initial_answers=None,
        prepared=None,
    )

    assert exit_code == 1
    assert cleaned["value"] is True


def test_callable_questions_source_is_accepted() -> None:
    env = Environment()
    destination = Path()

    questions = [Question(key="name", prompt="Name")]
    resolved = list(
        Manifest(questions=lambda _env, _destination: questions).questions(env, destination)
    )

    assert len(resolved) == 1
    assert resolved[0].key == "name"
