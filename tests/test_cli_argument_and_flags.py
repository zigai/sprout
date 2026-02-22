from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment

from sprout.cli import (
    Manifest,
    PreparedTemplate,
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


def _prepared_template(questions: list[Question]) -> PreparedTemplate:
    return PreparedTemplate(
        template_src="template",
        template_dir=Path(),
        manifest=Manifest(questions=questions),
        cleanup=lambda: None,
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


def test_format_question_help_includes_choices_and_multiselect() -> None:
    question = Question(
        key="workflow",
        prompt="Workflow",
        help="Pick one",
        choices=[("tests", "Tests"), ("lint", "Lint")],
        multiselect=True,
    )

    message = _format_question_help(question)

    assert "Workflow - Pick one" in message
    assert "choices: tests, lint" in message
    assert "multiple values allowed" in message


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

    assert parsed.name == "demo"
    assert parsed.kind == "lib"
    assert parsed.dynamic == "anything"
    assert parsed.tags == ["a", "b"]
    assert parsed.force is True


def test_build_cli_parser_enforces_static_choices() -> None:
    parser = _build_cli_parser(
        _prepared_template([Question(key="kind", prompt="Kind", choices=[("lib", "Library")])])
    )

    with pytest.raises(SystemExit):
        parser.parse_known_args(["template", "dest", "--kind", "tool"])


def test_main_passes_cli_answers_to_run_generate(monkeypatch: pytest.MonkeyPatch) -> None:
    questions = [Question(key="name", prompt="Project name")]
    cleanup_called = {"value": False}

    prepared = PreparedTemplate(
        template_src="template",
        template_dir=Path(),
        manifest=Manifest(questions=questions),
        cleanup=lambda: cleanup_called.update(value=True),
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

    result = main(["template", "destination", "--name", "sample"])

    assert result == 7
    assert captured["initial_answers"] == {"name": "sample"}
    assert cleanup_called["value"] is True


def test_run_generate_handles_keyboard_interrupt(monkeypatch: pytest.MonkeyPatch) -> None:
    manifest = Manifest(questions=[])
    cleaned = {"value": False}

    monkeypatch.setattr(
        "sprout.cli._resolve_template",
        lambda _args: (Path(), lambda: cleaned.update(value=True), manifest),
    )

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
