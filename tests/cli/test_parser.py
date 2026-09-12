from __future__ import annotations

from pathlib import Path

import pytest
from jinja2 import Environment

from sprout.cli.app import main
from sprout.cli.commands import _run_generate
from sprout.cli.parser import (
    PreparedTemplate,
    _consume_optional_value,
    _extract_template_destination,
    _flag_from_question_key,
    _format_question_help,
    build_cli_parser,
    sanitize_question_key,
)
from sprout.manifest import Manifest
from sprout.prompt.question import Question
from sprout.template_source import TemplateSource


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
    assert sanitize_question_key("project-name") == "project_name"
    assert sanitize_question_key("123name") == "q_123name"
    assert _flag_from_question_key("Project_Name!") == "project-name"


def test_format_question_help_keeps_prompt_and_multiselect_note() -> None:
    question = Question(
        key="workflow",
        prompt="workflow",
        help="Pick one",
        choices=[("tests", "Tests"), ("lint", "Lint")],
        multiselect=True,
    )

    message = _format_question_help(question)

    assert "Workflow - Pick one" in message
    assert "choices:" not in message
    assert "multiple values allowed" in message


@pytest.mark.parametrize(
    ("args", "expected_help"),
    [
        (["init", "--help"], "[DIRECTORY]  Directory where the scaffold should be created"),
        (["add", "--help"], "SOURCE       Local path, Git URL, or GitHub owner/repo shorthand"),
        (["add", "--help"], "--name NAME           Trusted template name; prompts when omitted"),
        (["new", "--help"], "TEMPLATE     Trusted name, local path, or Git repository containing"),
        (["new", "--help"], "DESTINATION  Target directory for the generated project"),
        (
            ["new", "--help"],
            "--force               Overwrite files in the destination directory if they",
        ),
    ],
)
def test_command_help_uses_aligned_sentence_case_descriptions(
    args: list[str],
    expected_help: str,
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        main(args)

    assert exit_info.value.code == 0
    assert expected_help in capsys.readouterr().out


def test_build_cli_parser_help_shows_choices_once(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_cli_parser(
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
    parser = build_cli_parser(_prepared_template(questions))

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
    parser = build_cli_parser(
        _prepared_template([Question(key="kind", prompt="Kind", choices=[("lib", "Library")])])
    )

    with pytest.raises(SystemExit):
        parser.parse_known_args(["new", "template", "dest", "--kind", "tool"])


def test_build_cli_parser_defaults_yes_no_questions_to_boolean_flags(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_cli_parser(
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
    assert "--[no-]include-license" in help_text
    assert "choices: yes, no" not in help_text


def test_build_cli_parser_boolean_flags_are_mutually_exclusive() -> None:
    parser = build_cli_parser(
        _prepared_template([Question.yes_no(key="include_license", prompt="Include license?")])
    )

    with pytest.raises(SystemExit):
        parser.parse_args(["new", "template", "dest", "--include-license", "--no-include-license"])


def test_build_cli_parser_rejects_yes_no_value_in_boolean_flags_mode() -> None:
    parser = build_cli_parser(
        _prepared_template([Question.yes_no(key="include_license", prompt="Include license?")])
    )

    with pytest.raises(SystemExit):
        parser.parse_args(["new", "template", "dest", "--include-license", "no"])


def test_build_cli_parser_supports_manifest_yes_no_boolean_style(
    capsys: pytest.CaptureFixture[str],
) -> None:
    parser = build_cli_parser(
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

    monkeypatch.setattr("sprout.cli.parser._load_questions_for_cli", lambda *_args: prepared)

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

    monkeypatch.setattr("sprout.cli.commands._run_generate", fake_run_generate)

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

    monkeypatch.setattr("sprout.cli.parser._load_questions_for_cli", fake_load_questions_for_cli)

    with pytest.raises(SystemExit) as exit_info:
        main(["new", "template", "--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--name <name>" in output
    assert captured["template_src"] == "template"
    assert captured["destination"] == (Path.cwd() / "__sprout_help_destination__").resolve()
    assert cleanup_called["value"] is True


def test_main_template_only_help_falls_back_to_base_help(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    def fake_load_questions_for_cli(_template_src: str, _destination: Path) -> PreparedTemplate:
        raise SystemExit("bad template questions")

    monkeypatch.setattr("sprout.cli.parser._load_questions_for_cli", fake_load_questions_for_cli)

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

    monkeypatch.setattr("sprout.cli.parser._load_questions_for_cli", fake_load_questions_for_cli)

    with pytest.raises(SystemExit) as exit_info:
        main(["new", "template", "destination", "--help"])

    assert exit_info.value.code == 0
    output = capsys.readouterr().out
    assert "--name <name>" in output
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
    monkeypatch.setattr("sprout.cli.commands.load_manifest", lambda _template_dir: manifest)

    def fake_execute_manifest(*_args: object, **_kwargs: object) -> object:
        raise KeyboardInterrupt

    monkeypatch.setattr("sprout.cli.commands.execute_manifest", fake_execute_manifest)

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


def test_build_cli_parser_formats_grouped_sections_and_synopsis(
    capsys: pytest.CaptureFixture[str],
) -> None:
    questions = [
        Question(key="project_name", prompt="Project name", default="demo"),
        Question(key="author_name", prompt="Author name", default="author"),
        Question.yes_no(key="create_github_repo", prompt="Create repo?", default=False),
        Question(key="copyright_license", prompt="License", default="MIT"),
    ]
    parser = build_cli_parser(_prepared_template(questions))

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["new", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "Usage: sprout new [options] TEMPLATE DESTINATION" in help_text
    assert "Project:" in help_text
    assert "Metadata:" in help_text
    assert "Git:" in help_text
    assert "Features:" in help_text
    assert "--[no-]create-github-repo" in help_text
    assert "Create repo [default: no]" in help_text
    assert "[default: demo]" in help_text
    assert "[default: author]" in help_text
    assert "[default: no]" in help_text
    assert "[default: MIT]" in help_text


def test_build_cli_parser_boolean_pair_action_conflicts() -> None:
    parser = build_cli_parser(
        _prepared_template([Question.yes_no(key="git_init", prompt="Initialize git?")])
    )

    # Same flag repeated is allowed
    parsed = parser.parse_args(["new", "tmpl", "dest", "--git-init", "--git-init"])
    assert parsed.new.git_init == "yes"

    # Conflicting flags raise an error
    with pytest.raises(SystemExit):
        parser.parse_args(["new", "tmpl", "dest", "--git-init", "--no-git-init"])

    with pytest.raises(SystemExit):
        parser.parse_args(["new", "tmpl", "dest", "--no-git-init", "--git-init"])


def test_build_cli_parser_truncates_long_choices_and_formats_defaults(
    capsys: pytest.CaptureFixture[str],
) -> None:
    many_choices = [(f"opt_{i}", f"Option {i}") for i in range(15)]
    questions = [
        Question(key="choice_field", prompt="Pick option", choices=many_choices),
        Question(key="list_field", prompt="Tags", default=["alpha", "beta"]),
        Question(key="probe_field", prompt="Name", default="__sprout_help_destination__"),
    ]
    parser = build_cli_parser(_prepared_template(questions))

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["new", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "...; 15 available" in help_text
    assert "[default: alpha, beta]" in help_text
    assert "__sprout_help_destination__" not in help_text


def test_build_cli_parser_derives_clean_metavars_and_supports_override(
    capsys: pytest.CaptureFixture[str],
) -> None:
    questions = [
        Question(key="package_name", prompt="Package name"),
        Question(key="author_email", prompt="Author email"),
        Question(key="repository_url", prompt="Repository URL"),
        Question(key="python_version", prompt="Python version"),
        Question(key="project_type", prompt="Project type"),
        Question(key="custom_option", prompt="Custom option", metavar="CUSTOM"),
    ]
    parser = build_cli_parser(_prepared_template(questions))

    with pytest.raises(SystemExit) as exit_info:
        parser.parse_args(["new", "--help"])

    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "--package-name <name>" in help_text
    assert "--author-email <email>" in help_text
    assert "--repository-url <url>" in help_text
    assert "--python-version <version>" in help_text
    assert "--project-type <type>" in help_text
    assert "--custom-option <custom>" in help_text
