from __future__ import annotations

import shutil
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from sprout.project.github import github_repository_target, is_github_repository_url

GitHubVisibility = Literal["private", "public"]


class SupportsConsolePrint(Protocol):
    def print(self, *objects: Any) -> None: ...  # noqa: ANN401 - Rich renderables are dynamic.


@dataclass(frozen=True)
class GitPostActionResult:
    git_repository_ready: bool
    initial_commit_ready: bool
    github_repository_created: bool


@dataclass(frozen=True)
class ProjectPostActionOptions:
    author_email_key: str = "author_email"
    author_name_key: str = "author_name"
    commit_message: str = "chore: initialize project"
    create_github_repo_key: str = "create_github_repo"
    default_visibility: GitHubVisibility = "private"
    description_key: str = "description"
    fallback_repo_name: str = "project"
    git_init_key: str = "git_init"
    initial_branch: str = "main"
    remote_name: str = "origin"
    repo_name_key: str = "repo_name"
    repository_url_key: str = "repository_url"
    visibility_key: str = "github_repo_visibility"


class ProjectPostActions:
    """Coordinate Git and GitHub setup for one generated project."""

    def __init__(
        self,
        destination: Path,
        answers: Mapping[str, object] | None = None,
        *,
        console: SupportsConsolePrint | None = None,
        options: ProjectPostActionOptions | None = None,
    ) -> None:
        self.destination = destination
        self.answers = answers or {}
        self.console = _resolve_console(console)
        self.options = options or ProjectPostActionOptions()

    def run(self) -> GitPostActionResult:
        if bool(self.answers.get(self.options.create_github_repo_key)):
            repository_url = self.answers.get(self.options.repository_url_key)
            if not isinstance(repository_url, str) or not is_github_repository_url(repository_url):
                self.console.print(
                    "[yellow]Repository URL is not a GitHub URL; gh will use the repo name.[/yellow]"
                )
            initial_commit_ready = self.create_initial_commit()
            github_repo_created = self.create_github_repo(push=initial_commit_ready)

            return GitPostActionResult(
                git_repository_ready=initial_commit_ready,
                initial_commit_ready=initial_commit_ready,
                github_repository_created=github_repo_created,
            )

        if bool(self.answers.get(self.options.git_init_key)):
            initial_commit_ready = self.create_initial_commit()
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

    def ensure_git_repo(self) -> bool:
        git_executable = shutil.which("git")
        if git_executable is None:
            self.console.print(
                "[yellow]Git is not installed; skipping local repository initialization.[/yellow]"
            )

            return False

        if (self.destination / ".git").exists():
            return True

        result = subprocess.run(  # noqa: S603
            [git_executable, "init", "-b", self.options.initial_branch],
            cwd=self.destination,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True

        fallback = subprocess.run(  # noqa: S603
            [git_executable, "init"],
            cwd=self.destination,
            check=False,
            capture_output=True,
            text=True,
        )
        if fallback.returncode == 0:
            subprocess.run(  # noqa: S603
                [git_executable, "branch", "-M", self.options.initial_branch],
                cwd=self.destination,
                check=False,
            )

            return True

        details = fallback.stderr.strip() or result.stderr.strip() or "unknown error"
        self.console.print(f"[yellow]Failed to initialize git repository: {details}[/yellow]")

        return False

    def has_git_commits(self, *, git_executable: str | None = None) -> bool:
        resolved_git = git_executable or shutil.which("git")
        if resolved_git is None:
            return False

        result = subprocess.run(  # noqa: S603
            [resolved_git, "rev-parse", "--verify", "HEAD"],
            cwd=self.destination,
            check=False,
            capture_output=True,
            text=True,
        )

        return result.returncode == 0

    def create_initial_commit(self) -> bool:
        git_executable = shutil.which("git")
        if git_executable is None:
            self.console.print("[yellow]Git is not installed; skipping initial commit.[/yellow]")
            return False
        if not self.ensure_git_repo():
            return False

        add_result = subprocess.run(  # noqa: S603
            [git_executable, "add", "--all"],
            cwd=self.destination,
            check=False,
            capture_output=True,
            text=True,
        )
        if add_result.returncode != 0:
            details = add_result.stderr.strip() or add_result.stdout.strip() or "unknown error"
            self.console.print(
                f"[yellow]Failed to stage files for initial commit: {details}[/yellow]"
            )

            return self.has_git_commits(git_executable=git_executable)

        staged_diff_result = subprocess.run(  # noqa: S603
            [git_executable, "diff", "--cached", "--quiet", "--exit-code"],
            cwd=self.destination,
            check=False,
            capture_output=True,
            text=True,
        )
        if staged_diff_result.returncode == 0:
            return self.has_git_commits(git_executable=git_executable)

        if staged_diff_result.returncode != 1:
            details = (
                staged_diff_result.stderr.strip()
                or staged_diff_result.stdout.strip()
                or "unknown error"
            )
            self.console.print(f"[yellow]Failed to inspect staged changes: {details}[/yellow]")

            return self.has_git_commits(git_executable=git_executable)

        return self._commit_staged_changes(git_executable)

    def create_github_repo(self, *, push: bool = False) -> bool:
        gh_executable = shutil.which("gh")
        if gh_executable is None:
            self.console.print(
                "[yellow]GitHub CLI not found; skipping repository creation.[/yellow]"
            )

            return False

        visibility = _normalise_visibility(
            str(self.answers.get(self.options.visibility_key) or self.options.default_visibility),
            default=self.options.default_visibility,
        )
        command = [
            gh_executable,
            "repo",
            "create",
            github_repository_target(
                self.answers,
                repository_url_key=self.options.repository_url_key,
                repo_name_key=self.options.repo_name_key,
                fallback_repo_name=self.options.fallback_repo_name,
            ),
            f"--{visibility}",
        ]
        description = str(self.answers.get(self.options.description_key) or "").strip()
        if description:
            command.extend(["--description", description])

        if self.ensure_git_repo():
            command.extend(
                ["--source", str(self.destination), "--remote", self.options.remote_name]
            )
            if push:
                command.append("--push")

        result = subprocess.run(  # noqa: S603
            command,
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode == 0:
            return True

        details = result.stderr.strip() or result.stdout.strip() or "unknown error"
        self.console.print(f"[yellow]Failed to create GitHub repository: {details}[/yellow]")

        return False

    def _commit_staged_changes(self, git_executable: str) -> bool:
        commit_command: list[str] = [git_executable]
        author_name = str(self.answers.get(self.options.author_name_key) or "").strip()
        author_email = str(self.answers.get(self.options.author_email_key) or "").strip()

        if author_name:
            commit_command.extend(["-c", f"user.name={author_name}"])

        if author_email:
            commit_command.extend(["-c", f"user.email={author_email}"])

        commit_command.extend(["commit", "-m", self.options.commit_message])

        commit_result = subprocess.run(  # noqa: S603
            commit_command,
            cwd=self.destination,
            check=False,
            capture_output=True,
            text=True,
        )
        if commit_result.returncode == 0:
            return True

        details = commit_result.stderr.strip() or commit_result.stdout.strip() or "unknown error"
        self.console.print(f"[yellow]Failed to create initial commit: {details}[/yellow]")

        return self.has_git_commits(git_executable=git_executable)


def ensure_git_repo(
    destination: Path,
    *,
    console: SupportsConsolePrint | None = None,
    initial_branch: str = "main",
) -> bool:
    options = ProjectPostActionOptions(initial_branch=initial_branch)

    return ProjectPostActions(destination, console=console, options=options).ensure_git_repo()


def has_git_commits(destination: Path, *, git_executable: str | None = None) -> bool:
    return ProjectPostActions(destination).has_git_commits(git_executable=git_executable)


def create_initial_commit(
    destination: Path,
    answers: Mapping[str, object] | None = None,
    *,
    console: SupportsConsolePrint | None = None,
    message: str = "chore: initialize project",
    author_name_key: str = "author_name",
    author_email_key: str = "author_email",
    initial_branch: str = "main",
) -> bool:
    options = ProjectPostActionOptions(
        author_email_key=author_email_key,
        author_name_key=author_name_key,
        commit_message=message,
        initial_branch=initial_branch,
    )

    return ProjectPostActions(
        destination,
        answers,
        console=console,
        options=options,
    ).create_initial_commit()


def create_github_repo(
    destination: Path,
    answers: Mapping[str, object] | None = None,
    *,
    console: SupportsConsolePrint | None = None,
    push: bool = False,
    repository_url_key: str = "repository_url",
    repo_name_key: str = "repo_name",
    fallback_repo_name: str = "project",
    description_key: str = "description",
    visibility_key: str = "github_repo_visibility",
    default_visibility: GitHubVisibility = "private",
    remote_name: str = "origin",
) -> bool:
    options = ProjectPostActionOptions(
        default_visibility=default_visibility,
        description_key=description_key,
        fallback_repo_name=fallback_repo_name,
        remote_name=remote_name,
        repo_name_key=repo_name_key,
        repository_url_key=repository_url_key,
        visibility_key=visibility_key,
    )

    return ProjectPostActions(
        destination,
        answers,
        console=console,
        options=options,
    ).create_github_repo(push=push)


def run_git_post_actions(
    destination: Path,
    answers: Mapping[str, object],
    *,
    console: SupportsConsolePrint | None = None,
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
    options = ProjectPostActionOptions(
        commit_message=commit_message,
        create_github_repo_key=create_github_repo_key,
        default_visibility=default_visibility,
        description_key=description_key,
        fallback_repo_name=fallback_repo_name,
        git_init_key=git_init_key,
        initial_branch=initial_branch,
        repo_name_key=repo_name_key,
        repository_url_key=repository_url_key,
        visibility_key=visibility_key,
    )

    return ProjectPostActions(
        destination,
        answers,
        console=console,
        options=options,
    ).run()


def _normalise_visibility(value: str, *, default: GitHubVisibility) -> GitHubVisibility:
    normalized = value.strip().lower()
    if normalized in {"private", "public"}:
        return normalized

    return default


def _resolve_console(console: SupportsConsolePrint | None) -> SupportsConsolePrint:
    if console is not None:
        return console

    from sprout.prompt import console as prompt_console

    return prompt_console


__all__ = [
    "GitHubVisibility",
    "GitPostActionResult",
    "ProjectPostActionOptions",
    "ProjectPostActions",
    "SupportsConsolePrint",
    "create_github_repo",
    "create_initial_commit",
    "ensure_git_repo",
    "has_git_commits",
    "run_git_post_actions",
]
