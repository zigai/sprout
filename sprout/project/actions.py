from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from sprout.project.github import github_repository_target, is_github_repository_url

GitHubVisibility = Literal["private", "public"]


class ConsoleLike(Protocol):
    def print(self, *objects: object) -> None: ...


@dataclass(frozen=True)
class GitPostActionResult:
    git_repository_ready: bool
    initial_commit_ready: bool
    github_repository_created: bool


def ensure_git_repo(
    destination: Path,
    *,
    console: ConsoleLike | None = None,
    initial_branch: str = "main",
) -> bool:
    output = _resolve_console(console)
    git_executable = shutil.which("git")
    if git_executable is None:
        output.print(
            "[yellow]Git is not installed; skipping local repository initialization.[/yellow]"
        )

        return False

    if (destination / ".git").exists():
        return True

    result = subprocess.run(  # noqa: S603
        [git_executable, "init", "-b", initial_branch],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode == 0:
        return True

    fallback = subprocess.run(  # noqa: S603
        [git_executable, "init"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    if fallback.returncode == 0:
        subprocess.run(  # noqa: S603
            [git_executable, "branch", "-M", initial_branch],
            cwd=destination,
            check=False,
        )

        return True

    details = fallback.stderr.strip() or result.stderr.strip() or "unknown error"
    output.print(f"[yellow]Failed to initialize git repository: {details}[/yellow]")

    return False


def has_git_commits(destination: Path, *, git_executable: str | None = None) -> bool:
    resolved_git = git_executable or shutil.which("git")
    if resolved_git is None:
        return False

    result = subprocess.run(  # noqa: S603
        [resolved_git, "rev-parse", "--verify", "HEAD"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )

    return result.returncode == 0


def create_initial_commit(
    destination: Path,
    answers: Mapping[str, object] | None = None,
    *,
    console: ConsoleLike | None = None,
    message: str = "chore: initialize project",
    author_name_key: str = "author_name",
    author_email_key: str = "author_email",
    initial_branch: str = "main",
) -> bool:
    output = _resolve_console(console)
    git_executable = shutil.which("git")
    if git_executable is None:
        output.print("[yellow]Git is not installed; skipping initial commit.[/yellow]")
        return False
    if not ensure_git_repo(destination, console=output, initial_branch=initial_branch):
        return False

    add_result = subprocess.run(  # noqa: S603
        [git_executable, "add", "--all"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    if add_result.returncode != 0:
        details = add_result.stderr.strip() or add_result.stdout.strip() or "unknown error"
        output.print(f"[yellow]Failed to stage files for initial commit: {details}[/yellow]")

        return has_git_commits(destination, git_executable=git_executable)

    staged_diff_result = subprocess.run(  # noqa: S603
        [git_executable, "diff", "--cached", "--quiet", "--exit-code"],
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    if staged_diff_result.returncode == 0:
        return has_git_commits(destination, git_executable=git_executable)

    if staged_diff_result.returncode != 1:
        details = (
            staged_diff_result.stderr.strip()
            or staged_diff_result.stdout.strip()
            or "unknown error"
        )
        output.print(f"[yellow]Failed to inspect staged changes: {details}[/yellow]")
        return has_git_commits(destination, git_executable=git_executable)

    return _commit_staged_changes(
        destination,
        answers or {},
        console=output,
        git_executable=git_executable,
        message=message,
        author_name_key=author_name_key,
        author_email_key=author_email_key,
    )


def _commit_staged_changes(
    destination: Path,
    answers: Mapping[str, object],
    *,
    console: ConsoleLike,
    git_executable: str,
    message: str,
    author_name_key: str,
    author_email_key: str,
) -> bool:
    commit_command: list[str] = [git_executable]
    author_name = str(answers.get(author_name_key) or "").strip()
    author_email = str(answers.get(author_email_key) or "").strip()

    if author_name:
        commit_command.extend(["-c", f"user.name={author_name}"])

    if author_email:
        commit_command.extend(["-c", f"user.email={author_email}"])

    commit_command.extend(["commit", "-m", message])

    commit_result = subprocess.run(  # noqa: S603
        commit_command,
        cwd=destination,
        check=False,
        capture_output=True,
        text=True,
    )
    if commit_result.returncode == 0:
        return True

    details = commit_result.stderr.strip() or commit_result.stdout.strip() or "unknown error"
    console.print(f"[yellow]Failed to create initial commit: {details}[/yellow]")

    return has_git_commits(destination, git_executable=git_executable)


def create_github_repo(
    destination: Path,
    answers: Mapping[str, object] | None = None,
    *,
    console: ConsoleLike | None = None,
    push: bool = False,
    repository_url_key: str = "repository_url",
    repo_name_key: str = "repo_name",
    fallback_repo_name: str = "project",
    description_key: str = "description",
    visibility_key: str = "github_repo_visibility",
    default_visibility: GitHubVisibility = "private",
    remote_name: str = "origin",
) -> bool:
    output = _resolve_console(console)
    gh_executable = shutil.which("gh")
    if gh_executable is None:
        output.print("[yellow]GitHub CLI not found; skipping repository creation.[/yellow]")
        return False

    answer_values = answers or {}
    visibility = _normalise_visibility(
        str(answer_values.get(visibility_key) or default_visibility),
        default=default_visibility,
    )
    command = [
        gh_executable,
        "repo",
        "create",
        github_repository_target(
            answer_values,
            repository_url_key=repository_url_key,
            repo_name_key=repo_name_key,
            fallback_repo_name=fallback_repo_name,
        ),
        f"--{visibility}",
    ]
    description = str(answer_values.get(description_key) or "").strip()
    if description:
        command.extend(["--description", description])

    if ensure_git_repo(destination, console=output):
        command.extend(["--source", str(destination), "--remote", remote_name])
        if push:
            command.append("--push")

    result = subprocess.run(  # noqa: S603
        command,
        cwd=destination,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode == 0:
        return True

    details = result.stderr.strip() or result.stdout.strip() or "unknown error"
    output.print(f"[yellow]Failed to create GitHub repository: {details}[/yellow]")

    return False


def run_git_post_actions(
    destination: Path,
    answers: Mapping[str, object],
    *,
    console: ConsoleLike | None = None,
    create_github_repo_key: str = "create_github_repo",
    git_init_key: str = "git_init",
    repository_url_key: str = "repository_url",
    repo_name_key: str = "repo_name",
    fallback_repo_name: str = "project",
    description_key: str = "description",
    visibility_key: str = "github_repo_visibility",
    default_visibility: GitHubVisibility = "private",
    commit_message: str = "chore: initialize project",
    initial_branch: str = "main",
) -> GitPostActionResult:
    output = _resolve_console(console)
    if bool(answers.get(create_github_repo_key)):
        if not is_github_repository_url(answers.get(repository_url_key)):
            output.print(
                "[yellow]Repository URL is not a GitHub URL; gh will use the repo name.[/yellow]"
            )
        initial_commit_ready = create_initial_commit(
            destination,
            answers,
            console=output,
            message=commit_message,
            initial_branch=initial_branch,
        )
        github_repo_created = create_github_repo(
            destination,
            answers,
            console=output,
            push=initial_commit_ready,
            repository_url_key=repository_url_key,
            repo_name_key=repo_name_key,
            fallback_repo_name=fallback_repo_name,
            description_key=description_key,
            visibility_key=visibility_key,
            default_visibility=default_visibility,
        )

        return GitPostActionResult(
            git_repository_ready=initial_commit_ready,
            initial_commit_ready=initial_commit_ready,
            github_repository_created=github_repo_created,
        )

    if bool(answers.get(git_init_key)):
        initial_commit_ready = create_initial_commit(
            destination,
            answers,
            console=output,
            message=commit_message,
            initial_branch=initial_branch,
        )
        return GitPostActionResult(
            git_repository_ready=initial_commit_ready,
            initial_commit_ready=initial_commit_ready,
            github_repository_created=False,
        )

    return GitPostActionResult(
        git_repository_ready=False,
        initial_commit_ready=False,
        github_repository_created=False,
    )


def _normalise_visibility(value: str, *, default: GitHubVisibility) -> GitHubVisibility:
    normalized = value.strip().lower()
    if normalized in {"private", "public"}:
        return normalized

    return default


def _resolve_console(console: ConsoleLike | None) -> ConsoleLike:
    if console is not None:
        return console

    from sprout.prompt import console as prompt_console

    return prompt_console


__all__ = [
    "ConsoleLike",
    "GitHubVisibility",
    "GitPostActionResult",
    "create_github_repo",
    "create_initial_commit",
    "ensure_git_repo",
    "has_git_commits",
    "run_git_post_actions",
]
