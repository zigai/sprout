from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from jinja2 import UndefinedError

from sprout.cli.app import main
from sprout.execution import execute_manifest
from sprout.manifest_loader import load_manifest
from tests.support.template_factory import TemplateFactory


def test_main_isolates_local_imports_between_templates(
    make_template: TemplateFactory,
    tmp_path: Path,
) -> None:
    manifest = """
        from project_defaults import value

        questions = []

        def apply(context):
            target = context.destination / "result.txt"
            target.write_text(value, encoding="utf-8")
            return [target]
    """
    first = make_template(manifest, files={"project_defaults.py": "value = 'first'\n"})
    second = make_template(manifest, files={"project_defaults.py": "value = 'second'\n"})
    first_destination = tmp_path / "first"
    second_destination = tmp_path / "second"

    assert main(["new", str(first), str(first_destination)]) == 0
    assert main(["new", str(second), str(second_destination)]) == 0

    assert (first_destination / "result.txt").read_text(encoding="utf-8") == "first"
    assert (second_destination / "result.txt").read_text(encoding="utf-8") == "second"


@pytest.mark.parametrize("deferred", [False, True], ids=["sequential", "interleaved"])
def test_template_isolates_lazy_package_imports(
    make_template: TemplateFactory,
    tmp_path: Path,
    deferred: bool,
) -> None:
    manifest = """
        from local_helpers import get_value

        questions = []

        def apply(context):
            target = context.destination / "result.txt"
            target.write_text(get_value(), encoding="utf-8")
            return [target]
    """
    helper = """
        def get_value():
            from .settings import value
            return value
    """
    first = make_template(
        manifest,
        files={
            "local_helpers/__init__.py": helper,
            "local_helpers/settings.py": "value = 'first'\n",
        },
    )
    second = make_template(
        manifest,
        files={
            "local_helpers/__init__.py": helper,
            "local_helpers/settings.py": "value = 'second'\n",
        },
    )
    first_destination = tmp_path / "first"
    second_destination = tmp_path / "second"

    if deferred:
        prepared = load_manifest(first)
        load_manifest(second)
        execute_manifest(prepared, template_dir=first, destination=first_destination)
    else:
        assert main(["new", str(first), str(first_destination)]) == 0
        assert main(["new", str(second), str(second_destination)]) == 0
        assert (second_destination / "result.txt").read_text(encoding="utf-8") == "second"

    assert (first_destination / "result.txt").read_text(encoding="utf-8") == "first"


@pytest.mark.parametrize("first_helper", ["local_helpers", "outer_helpers"])
def test_nested_generation_keeps_each_templates_imports(
    make_template: TemplateFactory,
    tmp_path: Path,
    first_helper: str,
) -> None:
    helper = """
        value = "initial"

        def get_value():
            from .settings import value
            return value
    """
    second = make_template(
        """
        import local_helpers as helpers

        questions = []

        def apply(context):
            helpers.value = "second"
            target = context.destination / "result.txt"
            target.write_text(helpers.get_value(), encoding="utf-8")
            return [target]
        """,
        files={
            "local_helpers/__init__.py": helper,
            "local_helpers/settings.py": "from . import value\n",
        },
    )
    first = make_template(
        f"""
        import {first_helper} as helpers
        from sprout.cli.commands import generate

        questions = []

        def apply(context):
            helpers.value = "first"
            generate({str(second)!r}, context.destination / "child")
            target = context.destination / "result.txt"
            target.write_text(helpers.get_value(), encoding="utf-8")
            return [target]
        """,
        files={
            f"{first_helper}/__init__.py": helper,
            f"{first_helper}/settings.py": "from . import value\n",
        },
    )
    destination = tmp_path / "generated"

    assert main(["new", str(first), str(destination)]) == 0

    assert (destination / "result.txt").read_text(encoding="utf-8") == "first"
    assert (destination / "child" / "result.txt").read_text(encoding="utf-8") == "second"


def test_main_generates_project_from_local_template(
    make_template: TemplateFactory,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    template_root = make_template(
        """
        from sprout import Question

        questions = [Question(key="name", prompt="Project name")]
        """
    )
    destination = tmp_path / "generated"

    exit_code = main(["new", str(template_root), str(destination), "--name", "demo"])

    assert exit_code == 0
    assert (destination / "README.md").read_text(encoding="utf-8") == "name=demo\n"
    output = capsys.readouterr().out
    assert f"Generated files in ~{os.sep}generated" in output
    assert "  • README.md" in output


def test_main_honors_should_skip_file(make_template: TemplateFactory, tmp_path: Path) -> None:
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

    exit_code = main(["new", str(template_root), str(destination), "--no-include-license"])

    assert exit_code == 0
    assert (destination / "README.md").read_text(encoding="utf-8") == "name=False\n"
    assert not (destination / "LICENSE").exists()


def test_main_supports_yes_no_cli_boolean_style(
    make_template: TemplateFactory,
    tmp_path: Path,
) -> None:
    template_root = make_template(
        """
        from sprout import Question

        cli_boolean_style = "yes-no"
        questions = [Question.yes_no(key="include_license", prompt="Include license?", default=True)]
        """,
        files={"template/README.md.jinja": "include_license={{ include_license }}\n"},
    )
    destination = tmp_path / "generated"

    exit_code = main(["new", str(template_root), str(destination), "--include-license", "no"])

    assert exit_code == 0
    assert (destination / "README.md").read_text(encoding="utf-8") == "include_license=False\n"


def test_main_supports_apply_hook(make_template: TemplateFactory, tmp_path: Path) -> None:
    template_root = make_template(
        """
        from sprout import render_templates

        questions = []

        def apply(context):
            created = render_templates(
                context.env,
                context.template_dir,
                context.destination,
                context.answers,
                render_paths=True,
            )
            extra = context.destination / "EXTRA.txt"
            extra.write_text("extra\\n", encoding="utf-8")
            created.append(extra)
            return created
        """,
        files={"template/README.md.jinja": "generated\n"},
    )
    destination = tmp_path / "generated"

    exit_code = main(["new", str(template_root), str(destination)])

    assert exit_code == 0
    assert (destination / "README.md").read_text(encoding="utf-8") == "generated\n"
    assert (destination / "EXTRA.txt").read_text(encoding="utf-8") == "extra\n"


@pytest.mark.parametrize("suffix", [".txt", ".txt.jinja"], ids=["copy", "render"])
@pytest.mark.parametrize("directory_link", [False, True], ids=["file-link", "directory-link"])
def test_main_rejects_destination_symlink_escape(
    make_template: TemplateFactory,
    tmp_path: Path,
    suffix: str,
    directory_link: bool,
) -> None:
    relative = f"folder/target{suffix}" if directory_link else f"target{suffix}"
    template_root = make_template("questions = []", files={f"template/{relative}": "replacement"})
    destination = tmp_path / "generated"
    destination.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    protected = outside / "target.txt"
    protected.write_text("protected", encoding="utf-8")
    link = destination / ("folder" if directory_link else "target.txt")
    link.symlink_to(outside if directory_link else protected, target_is_directory=directory_link)

    with pytest.raises(SystemExit, match="stay within the destination"):
        main(["new", str(template_root), str(destination), "--force"])

    assert protected.read_text(encoding="utf-8") == "protected"


def test_main_rejects_copy_target_directory_with_outside_link(
    make_template: TemplateFactory,
    tmp_path: Path,
) -> None:
    template_root = make_template("questions = []", files={"template/a.txt": "replacement"})
    destination = tmp_path / "generated"
    target_directory = destination / "a.txt"
    target_directory.mkdir(parents=True)
    protected = tmp_path / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    (target_directory / "a.txt").symlink_to(protected)

    with pytest.raises(SystemExit):
        main(["new", str(template_root), str(destination), "--force"])

    assert protected.read_text(encoding="utf-8") == "protected"


@pytest.mark.parametrize("suffix", [".txt", ".txt.jinja"], ids=["copy", "render"])
def test_main_does_not_overwrite_outside_hard_link(
    make_template: TemplateFactory,
    tmp_path: Path,
    suffix: str,
) -> None:
    template_root = make_template("questions = []", files={f"template/a{suffix}": "replacement"})
    destination = tmp_path / "generated"
    destination.mkdir()
    protected = tmp_path / "protected.txt"
    protected.write_text("protected", encoding="utf-8")
    protected.chmod(0o755)
    mode = protected.stat().st_mode
    (destination / "a.txt").hardlink_to(protected)

    assert main(["new", str(template_root), str(destination), "--force"]) == 0

    assert protected.read_text(encoding="utf-8") == "protected"
    assert protected.stat().st_mode == mode
    assert (destination / "a.txt").read_text(encoding="utf-8") == "replacement"

    if suffix == ".txt.jinja":
        assert (destination / "a.txt").stat().st_mode == mode


@pytest.mark.parametrize("existing", [False, True], ids=["new-destination", "existing-child"])
def test_main_rejects_file_directory_collision_before_overwriting(
    make_template: TemplateFactory,
    tmp_path: Path,
    existing: bool,
) -> None:
    template_root = make_template(
        "questions = []",
        files={"template/a.jinja": "file", "template/a/b.jinja": "replacement"},
    )
    destination = tmp_path / "generated"
    protected = destination / "a" / "b"
    if existing:
        protected.parent.mkdir(parents=True)
        protected.write_text("protected", encoding="utf-8")

    with pytest.raises(SystemExit):
        main(["new", str(template_root), str(destination), "--force"])

    files = {
        path.relative_to(destination).as_posix(): path.read_text(encoding="utf-8")
        for path in destination.rglob("*")
        if path.is_file()
    }
    assert files == ({"a/b": "protected"} if existing else {})


def test_main_respects_filesystem_case_identity(
    make_template: TemplateFactory,
    tmp_path: Path,
) -> None:
    template_root = make_template(
        """
        from sprout import Question

        questions = [Question(key="first", prompt="First"), Question(key="second", prompt="Second")]
        """,
        files={
            "template/{{ first }}.json.jinja": "first",
            "template/{{ second }}.json.jinja": "second",
        },
    )
    destination = tmp_path / "generated"
    destination.mkdir()
    protected = destination / "settings.json"
    protected.write_text("protected", encoding="utf-8")
    aliases = (destination / "SETTINGS.json").exists()
    args = [
        "new",
        str(template_root),
        str(destination),
        "--force",
        "--first",
        "settings",
        "--second",
        "SETTINGS",
    ]

    if aliases:
        with pytest.raises(SystemExit):
            main(args)

        assert protected.read_text(encoding="utf-8") == "protected"
    else:
        assert main(args) == 0
        assert protected.read_text(encoding="utf-8") == "first"
        assert (destination / "SETTINGS.json").read_text(encoding="utf-8") == "second"


@pytest.mark.parametrize(
    "sources",
    [("a.txt", "a.txt.jinja"), ("{{ first }}.txt.jinja", "{{ second }}.txt.jinja")],
    ids=["suffix-collision", "rendered-path-collision"],
)
def test_main_rejects_output_collisions_before_overwriting(
    make_template: TemplateFactory,
    tmp_path: Path,
    sources: tuple[str, str],
) -> None:
    template_root = make_template(
        """
        from sprout import Question

        questions = [Question(key="first", prompt="First"), Question(key="second", prompt="Second")]
        """,
        files={f"template/{sources[0]}": "first", f"template/{sources[1]}": "second"},
    )
    destination = tmp_path / "generated"
    destination.mkdir()
    protected = destination / "a.txt"
    protected.write_text("protected", encoding="utf-8")

    with pytest.raises(SystemExit, match="same destination"):
        main(
            [
                "new",
                str(template_root),
                str(destination),
                "--force",
                "--first",
                "a",
                "--second",
                "a",
            ]
        )

    assert protected.read_text(encoding="utf-8") == "protected"
    assert list(destination.iterdir()) == [protected]


@pytest.mark.parametrize("branch", ["master", "development"])
def test_main_renders_effective_git_default_branch(
    make_template: TemplateFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    branch: str,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "init.defaultBranch")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", branch)
    template = make_template(
        "questions = []",
        files={"template/.github/workflows/tests.yml.jinja": "branches: [{{ default_branch }}]\n"},
    )
    destination = tmp_path / "generated"

    assert main(["new", str(template), str(destination)]) == 0

    assert (destination / ".github/workflows/tests.yml").read_text() == f"branches: [{branch}]\n"


@pytest.mark.parametrize(
    ("github", "remote_branch", "expected_branch"),
    [
        (False, "", "development"),
        (True, "trunk", "trunk"),
        (True, "", None),
        (True, "null", None),
    ],
)
def test_generation_renders_and_pushes_resolved_branch(
    make_template: TemplateFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    github: bool,
    remote_branch: str,
    expected_branch: str | None,
) -> None:
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", "init.defaultBranch")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", "development")
    template = make_template(
        f"""
        from sprout import render_templates
        from sprout.helpers import ProjectPostActions

        questions = []

        def apply(context):
            actions = ProjectPostActions(context.destination, {{
                "create_github_repo": {github!r},
                "git_init": True,
                "repository_url": "https://github.com/example/sample",
                "author_name": "Example Author",
                "author_email": "author@example.com",
            }})
            def prepare():
                context.answers["default_branch"] = actions.prepare_default_branch()

            with actions.generation():
                created = render_templates(context.env, context.template_dir,
                                           context.destination, context.answers, prepare=prepare)
                actions.run()
                return created
        """,
        files={"template/.github/workflows/tests.yml.jinja": "branches: [{{ default_branch }}]\n"},
    )
    destination = tmp_path / "generated"
    real_run = subprocess.run
    real_which = shutil.which
    pushed: list[str] = []
    created: list[str] = []

    def fake_run(command, **kwargs):
        if command[0] == "/fake/gh":
            if "POST" in command:
                created.append("example/sample")

                return subprocess.CompletedProcess(
                    command,
                    0,
                    json.dumps(
                        {
                            "id": 1234,
                            "html_url": "https://github.com/example/sample",
                            "clone_url": "https://github.com/example/sample.git",
                            "default_branch": remote_branch,
                        }
                    ),
                    "",
                )

            if "DELETE" in command:
                return subprocess.CompletedProcess(command, 0, "", "")

            if command[2] == "users/example":
                return subprocess.CompletedProcess(command, 0, "User", "")

            if command[2] == "user":
                return subprocess.CompletedProcess(command, 0, "example", "")

            pytest.fail(f"Unexpected GitHub command: {command}")

        if "push" in command:
            pushed.append(
                real_run(
                    [real_which("git"), "symbolic-ref", "--short", "HEAD"],
                    cwd=destination,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()
            )

            return subprocess.CompletedProcess(command, 0, "", "")

        return real_run(command, **kwargs)

    monkeypatch.setattr(
        shutil, "which", lambda name: "/fake/gh" if name == "gh" else real_which(name)
    )
    monkeypatch.setattr(subprocess, "run", fake_run)

    if expected_branch is None:
        with pytest.raises(
            SystemExit, match="Could not resolve the GitHub repository's default branch"
        ):
            main(["new", str(template), str(destination)])

        assert created == ["example/sample"]
        assert pushed == []
        assert not (destination / ".github/workflows/tests.yml").exists()

        return

    assert main(["new", str(template), str(destination)]) == 0

    assert created == (["example/sample"] if github else [])
    assert pushed == (["trunk"] if github else [])
    assert (
        destination / ".github/workflows/tests.yml"
    ).read_text() == f"branches: [{expected_branch}]\n"
    assert (
        real_run(
            [real_which("git"), "show", "HEAD:.github/workflows/tests.yml"],
            cwd=destination,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        == f"branches: [{expected_branch}]\n"
    )


@pytest.mark.parametrize(
    ("failure", "cleanup_fails", "expected_created"),
    [
        ("jinja", False, False),
        ("path", False, False),
        ("collision", False, False),
        ("branch", False, True),
        ("branch-path", False, True),
        ("branch-collision", False, True),
        ("branch", True, True),
        ("write", False, True),
        ("create", False, False),
    ],
)
def test_generation_owns_only_repositories_it_creates(
    make_template: TemplateFactory,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
    cleanup_fails: bool,
    expected_created: bool,
) -> None:
    template = make_template(
        """
        from sprout import render_templates
        from sprout.helpers import ProjectPostActions
        questions = []
        def apply(context):
            context.answers["separator"] = "/"
            actions = ProjectPostActions(context.destination, {
                "create_github_repo": True, "repository_url": "https://github.com/example/sample",
            })
            def prepare():
                context.answers["default_branch"] = actions.prepare_default_branch()
            with actions.generation():
                return render_templates(context.env, context.template_dir, context.destination,
                                        context.answers, render_paths=True, prepare=prepare)
        """,
        files={"template/a.txt.jinja": "generated", "template/z.txt.jinja": "generated"},
    )
    source = template / "template"
    invalid_sources = {
        "jinja": ("z.txt.jinja", "{{ missing.attribute }}"),
        "path": ("{{ '..' }}{{ separator }}escape.txt.jinja", "invalid"),
        "collision": ("a.txt", "collision"),
        "branch": (
            "z.txt.jinja",
            "{% if default_branch == 'trunk' %}{{ missing.attribute }}{% endif %}",
        ),
        "branch-path": (
            "{{ '..' if default_branch == 'trunk' else 'valid' }}{{ separator }}escape.txt.jinja",
            "invalid",
        ),
        "branch-collision": (
            "{{ 'a.txt' if default_branch == 'trunk' else 'valid' }}.jinja",
            "collision",
        ),
    }
    if failure in invalid_sources:
        name, content = invalid_sources[failure]
        (source / name).write_text(content)

    destination = tmp_path / "generated"
    destination.mkdir()
    protected = destination / "a.txt"
    protected.write_text("original")
    real_run = subprocess.run
    real_which = shutil.which
    real_replace = Path.replace
    remote_exists = False
    deleted: list[str] = []

    def fake_run(command, **kwargs):
        nonlocal remote_exists

        if command[0] == "/fake/gh":
            if "POST" in command:
                remote_exists = failure != "create"
                return subprocess.CompletedProcess(
                    command,
                    int(not remote_exists),
                    json.dumps(
                        {
                            "id": 1234,
                            "html_url": "https://github.com/example/sample",
                            "clone_url": "https://github.com/example/sample.git",
                            "default_branch": "trunk",
                        }
                    ),
                    "repository already exists" if not remote_exists else "",
                )

            if "DELETE" in command:
                deleted.append(command[-1])
                assert remote_exists
                remote_exists = cleanup_fails

                return subprocess.CompletedProcess(
                    command,
                    int(cleanup_fails),
                    "",
                    "HTTP 403: delete_repo required" if cleanup_fails else "",
                )

            output = {"users/example": "User", "user": "example"}[command[2]]

            return subprocess.CompletedProcess(command, 0, output, "")

        assert "push" not in command

        return real_run(command, **kwargs)

    def replace(path, target):
        if failure == "write" and Path(target) == destination / "z.txt":
            raise OSError("injected replacement failure")

        return real_replace(path, target)

    monkeypatch.setattr(
        shutil, "which", lambda name: "/fake/gh" if name == "gh" else real_which(name)
    )
    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(Path, "replace", replace)

    if cleanup_fails:
        with pytest.raises(ExceptionGroup) as error:
            main(["new", str(template), str(destination), "--force"])

        assert "https://github.com/example/sample" in str(error.value)
        assert "1234" in str(error.value)
        assert "missing" in str(error.value.exceptions[0])
        assert "delete_repo" in str(error.value.exceptions[1])
    else:
        with pytest.raises((SystemExit, UndefinedError)):
            main(["new", str(template), str(destination), "--force"])

    assert deleted == (["repositories/1234"] if expected_created else [])
    assert remote_exists is cleanup_fails
    assert protected.read_text() == "original"
    assert not (destination / "z.txt").exists()
