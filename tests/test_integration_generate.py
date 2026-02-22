from __future__ import annotations

from pathlib import Path

from sprout.cli import main
from tests.conftest import MakeTemplate


def test_main_generates_project_from_local_template(
    make_template: MakeTemplate,
    tmp_path: Path,
) -> None:
    template_root = make_template(
        """
        from sprout import Question

        questions = [Question(key="name", prompt="Project name")]
        """
    )
    destination = tmp_path / "generated"

    exit_code = main([str(template_root), str(destination), "--name", "demo"])

    assert exit_code == 0
    assert (destination / "README.md").read_text(encoding="utf-8") == "name=demo\n"


def test_main_honors_should_skip_file(make_template: MakeTemplate, tmp_path: Path) -> None:
    template_root = make_template(
        """
        from sprout import Question

        questions = [Question.yes_no(key="include_license", prompt="Include license?", default=True)]

        def should_skip_file(relative_path: str, answers: dict[str, object]) -> bool:
            return relative_path == "LICENSE.jinja" and not bool(answers.get("include_license"))
        """,
        files={
            "template/README.md.jinja": "name={{ include_license }}\n",
            "template/LICENSE.jinja": "license\n",
        },
    )
    destination = tmp_path / "generated"

    exit_code = main([str(template_root), str(destination), "--include-license", "no"])

    assert exit_code == 0
    assert (destination / "README.md").read_text(encoding="utf-8") == "name=False\n"
    assert not (destination / "LICENSE").exists()


def test_main_supports_apply_hook(make_template: MakeTemplate, tmp_path: Path) -> None:
    template_root = make_template(
        """
        from pathlib import Path

        questions = []

        def apply(env, template_dir: Path, destination: Path, answers, render_templates):
            created = render_templates(
                env,
                template_dir,
                destination,
                answers,
                render_paths=True,
            )
            extra = destination / "EXTRA.txt"
            extra.write_text("extra\\n", encoding="utf-8")
            created.append(extra)
            return created
        """,
        files={"template/README.md.jinja": "generated\n"},
    )
    destination = tmp_path / "generated"

    exit_code = main([str(template_root), str(destination)])

    assert exit_code == 0
    assert (destination / "README.md").read_text(encoding="utf-8") == "generated\n"
    assert (destination / "EXTRA.txt").read_text(encoding="utf-8") == "extra\n"
