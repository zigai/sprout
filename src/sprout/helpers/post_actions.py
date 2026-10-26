from __future__ import annotations

import json
import shlex
import shutil
import subprocess
from collections.abc import Generator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, Protocol

from rich.console import Console
from rich.theme import Theme

from sprout.errors import SproutGenerationError
from sprout.extensions.git_defaults import get_default_branch
from sprout.helpers.github import github_repository_target, is_github_repository_url

GitHubVisibility = Literal["private", "public"]
_DEFAULT_CONSOLE = Console(
    theme=Theme(
        {
            "repr.path": "bright_blue",
            "repr.filename": "bright_blue",
            "repr.url": "underline bright_blue",
            "markdown.link": "bright_blue",
            "markdown.link_url": "underline bright_blue",
        }
    )
)


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
    initial_branch: str | None = None
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
        self.console = console if console is not None else _DEFAULT_CONSOLE
        self.options = options or ProjectPostActionOptions()
        self._default_branch: str | None = None
        self._git_repository_initialized = False
        self._github_repository_created = False
        self._github_repository_id: int | None = None
        self._github_repository_url: str | None = None
        self._github_default: str | None = None
        self._remote_added = False

    def run(self) -> GitPostActionResult:
        if self.answers.get(self.options.create_github_repo_key) or self.answers.get(
            self.options.git_init_key
        ):
            self.prepare_default_branch()

        if bool(self.answers.get(self.options.create_github_repo_key)):
            repository_url = self.answers.get(self.options.repository_url_key)
            if not isinstance(repository_url, str) or not is_github_repository_url(repository_url):
                self.console.print(
                    "[yellow]Repository URL is not a GitHub URL; gh will use the repo name.[/yellow]"
                )
            initial_commit_ready = self.create_initial_commit()
            if not initial_commit_ready:
                raise SproutGenerationError("Could not create the initial Git commit.")

            github_repo_created = self.create_github_repo(push=True)
            if not github_repo_created:
                raise SproutGenerationError("Could not push the initial Git commit.")

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

    @contextmanager
    def generation(self) -> Generator[None]:
        """Clean up a repository created by this instance if generation fails."""
        try:
            yield
        except BaseException as e:
            if self._github_repository_id is not None:
                try:
                    self._delete_github_repo()
                except (OSError, SproutGenerationError) as cleanup_error:
                    if self._github_repository_id is None:
                        raise BaseExceptionGroup(
                            "Generation failed; the GitHub repository was deleted, "
                            "but local remote cleanup failed.",
                            [e, cleanup_error],
                        ) from None

                    raise BaseExceptionGroup(
                        f"Generation failed; cleanup failed for {self._github_repository_url} "
                        f"(repository ID {self._github_repository_id}). "
                        "The repository may remain; deletion requires repository administration "
                        "permission and, for classic tokens, delete_repo scope.",
                        [e, cleanup_error],
                    ) from None

            raise

    def prepare_default_branch(self) -> str:
        """Prepare Git/GitHub after render validation and return the initial push branch."""
        if self._default_branch is not None:
            return self._default_branch

        create_github_repo = bool(
            self.answers.get(self.options.create_github_repo_key) or self._github_repository_created
        )
        if not (self.answers.get(self.options.git_init_key) or create_github_repo):
            branch = self.options.initial_branch or get_default_branch()
            self._default_branch = branch
            return branch

        if not self.ensure_git_repo():
            raise SproutGenerationError("Could not prepare the project's Git repository.")

        git_executable = shutil.which("git")
        if git_executable is None:
            raise SproutGenerationError("Git is required to resolve the project's branch.")

        if create_github_repo:
            if not self.create_github_repo():
                raise SproutGenerationError("Could not prepare the project's GitHub repository.")

            if self._git_repository_initialized:
                self._use_github_default_branch(git_executable)

        result = subprocess.run(  # noqa: S603
            [git_executable, "symbolic-ref", "--short", "HEAD"],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )
        branch = result.stdout.strip()
        if result.returncode != 0 or not branch:
            raise SproutGenerationError("Could not resolve the project's Git branch.")

        if create_github_repo and branch != self._github_default:
            raise SproutGenerationError(
                "The existing Git branch differs from the new GitHub repository's default branch."
            )

        self._default_branch = branch

        return branch

    def ensure_git_repo(self) -> bool:
        git_executable = shutil.which("git")
        if git_executable is None:
            self.console.print(
                "[yellow]Git is not installed; skipping local repository initialization.[/yellow]"
            )

            return False

        if (self.destination / ".git").exists():
            return True

        branch = self.options.initial_branch or get_default_branch()
        result = subprocess.run(  # noqa: S603
            [git_executable, "init", "-b", branch],
            cwd=self.destination,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            self._git_repository_initialized = True
            return True

        details = result.stderr.strip() or "unknown error"
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

        if self._github_repository_created:
            return self._push_initial_commit(gh_executable) if push else True

        visibility = _normalise_visibility(
            str(self.answers.get(self.options.visibility_key) or self.options.default_visibility),
            default=self.options.default_visibility,
        )
        repository_target = github_repository_target(
            self.answers,
            repository_url_key=self.options.repository_url_key,
            repo_name_key=self.options.repo_name_key,
            fallback_repo_name=self.options.fallback_repo_name,
        )
        endpoint, repository_name = self._github_create_endpoint(gh_executable, repository_target)
        command = [
            gh_executable,
            "api",
            "--method",
            "POST",
            endpoint,
            "-f",
            f"name={repository_name}",
            "-F",
            f"private={str(visibility == 'private').lower()}",
        ]
        description = str(self.answers.get(self.options.description_key) or "").strip()
        if description:
            command.extend(["-f", f"description={description}"])

        git_repository_ready = self._git_repository_initialized or self.ensure_git_repo()
        result = subprocess.run(  # noqa: S603
            command,
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            details = result.stderr.strip() or result.stdout.strip() or "unknown error"
            self.console.print(
                f"[yellow]Could not confirm creation of GitHub repository {repository_target}: "
                f"{details}. If the request reached GitHub, check this repository manually; "
                "cleanup requires the ID from a successful create response.[/yellow]"
            )

            return False

        clone_url = self._record_github_repository(result.stdout, repository_target)
        if git_repository_ready:
            git_executable = shutil.which("git")
            if git_executable is None:
                raise SproutGenerationError("Git is required to add the repository remote.")

            remote = subprocess.run(  # noqa: S603
                [git_executable, "remote", "add", self.options.remote_name, clone_url],
                cwd=self.destination,
                capture_output=True,
                text=True,
                check=False,
            )
            if remote.returncode != 0:
                raise SproutGenerationError("Could not add the GitHub repository remote.")

            self._remote_added = True

        if not push or not git_repository_ready:
            return True

        return self._push_initial_commit(gh_executable)

    def _record_github_repository(self, response: str, repository_target: str) -> str:
        try:
            repository = json.loads(response)
        except json.JSONDecodeError as e:
            raise SproutGenerationError(
                f"GitHub returned an invalid create response for {repository_target}; "
                "creation may have succeeded. Check this resource manually."
            ) from e

        repository_id = repository.get("id") if isinstance(repository, dict) else None
        if type(repository_id) is not int or repository_id <= 0:
            raise SproutGenerationError(
                f"GitHub returned no repository ID after creating {repository_target}; "
                "check this resource manually."
            )

        self._github_repository_id = repository_id
        self._github_repository_url = f"https://github.com/{repository_target}"
        self._github_repository_created = True
        repository_url = repository.get("html_url")
        clone_url = repository.get("clone_url")
        if (
            not isinstance(repository_url, str)
            or not repository_url
            or not isinstance(clone_url, str)
            or not clone_url
        ):
            raise SproutGenerationError("GitHub returned invalid repository URLs.")

        self._github_repository_url = repository_url
        branch = repository.get("default_branch")
        if not isinstance(branch, str) or not branch or branch == "null":
            raise SproutGenerationError("Could not resolve the GitHub repository's default branch.")

        self._default_branch = None
        self._github_default = branch

        return clone_url

    def _github_create_endpoint(
        self, gh_executable: str, repository_target: str
    ) -> tuple[str, str]:
        endpoint = "user/repos"
        if "/" in repository_target:
            owner, repository_name = repository_target.split("/", 1)
            owner_result = subprocess.run(  # noqa: S603
                [gh_executable, "api", f"users/{owner}", "--jq", ".type"],
                cwd=self.destination,
                capture_output=True,
                text=True,
                check=False,
            )
            if owner_result.returncode != 0:
                raise SproutGenerationError("Could not resolve the GitHub repository owner.")

            if owner_result.stdout.strip() == "Organization":
                endpoint = f"orgs/{owner}/repos"
            else:
                login = subprocess.run(  # noqa: S603
                    [gh_executable, "api", "user", "--jq", ".login"],
                    cwd=self.destination,
                    capture_output=True,
                    text=True,
                    check=False,
                )
                if login.returncode != 0 or login.stdout.strip().casefold() != owner.casefold():
                    raise SproutGenerationError("Repository owner is not the authenticated user.")
        else:
            repository_name = repository_target

        return endpoint, repository_name

    def _delete_github_repo(self) -> None:
        gh_executable = shutil.which("gh")
        if gh_executable is None:
            raise SproutGenerationError("GitHub CLI is unavailable for cleanup.")

        # Use the creation ID so a renamed or reused repository name cannot change the target.
        result = subprocess.run(  # noqa: S603
            [
                gh_executable,
                "api",
                "--method",
                "DELETE",
                f"repositories/{self._github_repository_id}",
            ],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SproutGenerationError(
                result.stderr.strip() or "GitHub rejected repository cleanup."
            )

        self._github_repository_created = False
        self._github_repository_id = None
        if self._remote_added:
            git_executable = shutil.which("git")
            if git_executable is None:
                raise SproutGenerationError("Git is unavailable to remove the local remote.")

            remote = subprocess.run(  # noqa: S603
                [git_executable, "remote", "remove", self.options.remote_name],
                cwd=self.destination,
                capture_output=True,
                text=True,
                check=False,
            )
            if remote.returncode != 0:
                raise SproutGenerationError(
                    f"GitHub repository deleted, but local remote {self.options.remote_name} remains."
                )

            self._remote_added = False

    def _push_initial_commit(self, gh_executable: str) -> bool:
        self.prepare_default_branch()
        git_executable = shutil.which("git")
        if git_executable is None:
            return False

        credential_helper = f"!{shlex.quote(gh_executable)} auth git-credential"
        push_result = subprocess.run(  # noqa: S603
            [
                git_executable,
                "-c",
                "credential.helper=",
                "-c",
                f"credential.helper={credential_helper}",
                "push",
                "--set-upstream",
                self.options.remote_name,
                "HEAD",
            ],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )
        if push_result.returncode == 0:
            return True

        details = push_result.stderr.strip() or push_result.stdout.strip() or "unknown error"
        self.console.print(
            f"[yellow]GitHub repository was created, but the initial push failed: {details}[/yellow]"
        )

        return False

    def _use_github_default_branch(self, git_executable: str) -> None:
        github_branch = self._github_default
        if github_branch is None:
            raise SproutGenerationError("Could not resolve the GitHub repository's default branch.")

        result = subprocess.run(  # noqa: S603
            [git_executable, "branch", "-M", github_branch],
            cwd=self.destination,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise SproutGenerationError("Could not set the GitHub repository's default branch.")

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
    initial_branch: str | None = None,
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
    initial_branch: str | None = None,
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
    initial_branch: str | None = None,
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
    if normalized == "private":
        return "private"
    if normalized == "public":
        return "public"

    return default


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
