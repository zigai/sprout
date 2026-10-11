from __future__ import annotations

import multiprocessing
import os
import sys
from multiprocessing.connection import Connection
from multiprocessing.synchronize import Event
from pathlib import Path

import pytest

from sprout.cli.app import main
from sprout.registry import TemplateRegistry


def _add_template_process(
    path: Path,
    name: str,
    ready: Connection,
    release: Event | None = None,
) -> None:
    signaled = False

    def observe_registry_write(event: str, args: tuple[object, ...]) -> None:
        nonlocal signaled
        if signaled:
            return

        if release is None and event in {"fcntl.flock", "msvcrt.locking"}:
            signaled = True
            ready.send(None)
            return

        if event != "open" or not isinstance(args[0], str) or not isinstance(args[2], int):
            return

        opened = Path(args[0])
        if (
            opened.parent != path.parent
            or opened == path.with_name(f"{path.name}.lock")
            or not args[2] & (os.O_WRONLY | os.O_RDWR)
        ):
            return

        signaled = True
        ready.send(None)
        if release is not None and not release.wait(timeout=10):
            raise TimeoutError("registry writer was not released")

    sys.addaudithook(observe_registry_write)
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr("sprout.registry.user_config_path", lambda *_args, **_kwargs: path.parent)
        assert main(["add", f"https://example.com/{name}.git", "--name", name]) == 0
        ready.close()


def test_concurrent_add_commands_preserve_both_aliases(tmp_path: Path) -> None:
    path = tmp_path / "config" / "templates.json"
    context = multiprocessing.get_context("spawn")
    release = context.Event()
    first_ready, first_signal = context.Pipe(duplex=False)
    second_ready, second_signal = context.Pipe(duplex=False)
    first = context.Process(
        target=_add_template_process,
        args=(path, "first", first_signal, release),
    )
    second = context.Process(
        target=_add_template_process,
        args=(path, "second", second_signal),
    )
    try:
        first.start()
        assert first_ready.poll(timeout=10), "first writer did not reach the save"
        first_ready.recv()
        second.start()
        assert second_ready.poll(timeout=10), "second command did not reach the save"
        second_ready.recv()
        release.set()
        first.join(timeout=10)
        second.join(timeout=10)

        assert first.exitcode == 0
        assert second.exitcode == 0
        assert {(entry.name, entry.source) for entry in TemplateRegistry(path).entries()} == {
            ("first", "https://example.com/first.git"),
            ("second", "https://example.com/second.git"),
        }
    finally:
        release.set()
        for process in (first, second):
            if process.pid is not None:
                process.join(timeout=10)
                if process.is_alive():
                    process.terminate()
                    process.join(timeout=10)
                process.close()
        for connection in (first_ready, first_signal, second_ready, second_signal):
            connection.close()
