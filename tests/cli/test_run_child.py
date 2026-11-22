"""``ppk2 run`` child-handling tests: real child processes, no PPK2 involved."""

import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from ppk2.cli.commands.run import run, spawn_and_wait


def test_child_exit_code_propagates() -> None:
    assert spawn_and_wait([sys.executable, "-c", "raise SystemExit(7)"]) == 7
    assert spawn_and_wait([sys.executable, "-c", "raise SystemExit(0)"]) == 0


def test_missing_executable_exits_127(capsys: pytest.CaptureFixture[str]) -> None:
    code = spawn_and_wait(["/nonexistent/definitely-not-a-binary"])
    captured = capsys.readouterr()
    assert code == 127
    assert "command not found" in captured.err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX sessions only")
def test_child_runs_in_its_own_session() -> None:
    """start_new_session=True -> the child is its own session leader.

    The isolation is what keeps a terminal Ctrl-C from racing the
    wrapper and the child for the same SIGINT: the wrapper forwards
    it deliberately instead.
    """
    probe = "import os, sys; sys.exit(0 if os.getsid(0) == os.getpid() else 1)"
    assert spawn_and_wait([sys.executable, "-c", probe]) == 0


def test_run_without_command_exits_2(capsys: pytest.CaptureFixture[str]) -> None:
    """The `run -- <cmd>` contract: no command -> usage-style exit 2, no device I/O."""
    assert run(None, None, [], None, 3.3, False) == 2
    assert "requires a command" in capsys.readouterr().err


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals only")
def test_signal_killed_child_maps_to_128_plus_n() -> None:
    """SIGTERM-killed child -> 143 (128 + 15), the shell convention.

     ``proc.wait()`` reports ``-15``; propagating that raw would reach
     the shell as ``256 - 15 = 241``. The Rust port maps to ``128 + N``
    : so do we.
    """
    self_kill = "import os, signal; os.kill(os.getpid(), signal.SIGTERM)"
    assert spawn_and_wait([sys.executable, "-c", self_kill]) == 143


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX signals only")
def test_a_terminated_wrapper_takes_its_child_with_it(tmp_path: Path) -> None:
    """SIGTERM to the wrapper (CI cancellation): the child must not outlive it.

    The child would write a file after two seconds. The wrapper is
    terminated before that, and the file must never appear.
    """
    late = tmp_path / "late"
    child = f"import time, pathlib; time.sleep(2); pathlib.Path({str(late)!r}).write_text('x')"
    wrapper = textwrap.dedent(f"""
        import sys
        from ppk2.cli.commands.run import spawn_and_wait
        from ppk2.cli.signals import signals_to_systemexit
        with signals_to_systemexit("SIGTERM"):
            print("ready", flush=True)
            spawn_and_wait([sys.executable, "-c", {child!r}])
    """)
    proc = subprocess.Popen([sys.executable, "-c", wrapper], stdout=subprocess.PIPE)
    assert proc.stdout is not None
    assert proc.stdout.readline().strip() == b"ready"
    time.sleep(0.3)  # the child is up
    proc.send_signal(signal.SIGTERM)
    assert proc.wait(timeout=10) == 143
    time.sleep(2.5)
    assert not late.exists()
