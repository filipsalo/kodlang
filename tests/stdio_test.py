"""The harness that runs a process with every wait bounded (`running`), which
build_plumbing_test.py uses too, its own tests, and the test of
the Python launcher's SIGPIPE. What `kod run` and `kod test` do with stdin,
stdout, stderr and signals is checked in tests/stdio_test.kod.

Every wait is bounded: a process that does not answer within `WAIT` seconds is
killed with everything it started, so a regression fails the test instead of
hanging it. Everything a test starts is stopped and everything it makes under
`build/` is removed when it ends, also when pytest is stopped by SIGINT, SIGTERM
or SIGHUP (a SIGKILL of pytest itself cannot be caught and leaves nothing but
ignored files there)."""

import contextlib
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Callable, Iterator

import pytest

ROOT = Path(__file__).resolve().parent.parent
KOD = ROOT / "build" / "apps" / "kod" / "kod"
FIXTURES = ROOT / "tests" / "stdio"

# Seconds any one run may take, build included (about 1 s on an idle machine).
WAIT = float(os.environ.get("STDIO_TEST_WAIT", "60"))

# The `sh_kodc` fixture builds the tools these tests call.
pytestmark = pytest.mark.usefixtures("sh_kodc")


class Scratch:
    """A directory `build/stdio_<token>/` for the copies of the fixtures. A
    copy is named `<name>_<token>.kod`, so its program name is one no other
    run uses (`kod` builds into `build/apps/<name>`) and tests running at the
    same time from another checkout of the suite do not share an
    executable."""

    def __init__(self) -> None:
        (ROOT / "build").mkdir(exist_ok=True)
        self.dir = Path(tempfile.mkdtemp(prefix="stdio_", dir=ROOT / "build"))
        self.token = self.dir.name.removeprefix("stdio_")

    def copy(self, source: Path, filename: str, into: Path | None = None) -> str:
        """Copy `source` to `filename` in `into` (a directory below the scratch
        directory) or in the scratch directory; return the path relative to
        the repository root."""
        target = (into or self.dir) / filename
        target.parent.mkdir(exist_ok=True)
        shutil.copyfile(source, target)
        return str(target.relative_to(ROOT))

    def program(self, fixture: str) -> str:
        """A private copy of tests/stdio/<fixture>.kod."""
        return self.copy(FIXTURES / f"{fixture}.kod", f"{fixture}_{self.token}.kod")

    def remove(self) -> None:
        shutil.rmtree(self.dir, ignore_errors=True)
        # What was built from the copies (a program named after the file, or
        # after the directory for `kod test <directory>`).
        apps = ROOT / "build" / "apps"
        for app in [*apps.glob(f"*_{self.token}"), *apps.glob(f"*{self.token}*_tests")]:
            shutil.rmtree(app, ignore_errors=True)


# The processes `running` has started and not yet reaped.
LIVE: set[subprocess.Popen] = set()

# Signals that end Python without running a `finally`.
STOPPED_BY = (signal.SIGTERM, signal.SIGHUP)


class Launching:
    """Whether `running` has started a process it has not yet recorded in
    `LIVE`. A signal that arrives then would find nothing to stop and leave the
    process behind, so it waits until the process is recorded."""

    active = False
    signalled: Callable[[], None] | None = None


def kill_group(proc: subprocess.Popen) -> None:
    """SIGKILL everything in the session `proc` leads."""
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(proc.pid, signal.SIGKILL)


@contextlib.contextmanager
def removed_if_signalled(remove: Callable[[], None]) -> Iterator[None]:
    """While the block runs, SIGTERM and SIGHUP (what `timeout` and a closing
    terminal send) stop every process `running` started, call `remove`, and
    then end this process by that signal. Blocks nest: each removes what it
    made and hands the signal on to the handler it replaced, so that the
    outermost ends the process after all have removed theirs."""

    def stop(signum: int, frame) -> None:
        if Launching.active:
            Launching.signalled = lambda: stop(signum, frame)
            return
        for proc in list(LIVE):
            kill_group(proc)
        remove()
        enclosing = before[signal.Signals(signum)]
        if callable(enclosing):
            enclosing(signum, frame)
            return
        signal.signal(signum, signal.SIG_DFL)
        os.kill(os.getpid(), signum)

    try:
        before = {sig: signal.signal(sig, stop) for sig in STOPPED_BY}
    except ValueError:  # not the main thread: no handlers, only the `finally`s
        yield
        return
    try:
        yield
    finally:
        for sig, handler in before.items():
            signal.signal(sig, handler)


@contextlib.contextmanager
def scratch_dir() -> Iterator[Scratch]:
    made = Scratch()
    with removed_if_signalled(made.remove):
        try:
            yield made
        finally:
            made.remove()


@pytest.fixture(scope="module")
def scratch() -> Iterator[Scratch]:
    with scratch_dir() as made:
        yield made


@contextlib.contextmanager
def running(argv: list, **kwargs) -> Iterator[subprocess.Popen]:
    """Start `argv` from the repository root (or the `cwd` the caller gives)
    in a session of its own, with stdout a pipe and stderr a file
    (`stderr_text(proc)` reads it) unless the caller says otherwise. After
    `WAIT` seconds it is killed, which ends any read or wait the block is
    blocked in. At the end of the block it is killed, with everything it
    started, and reaped."""
    errors = None
    if "stderr" not in kwargs:
        errors = tempfile.TemporaryFile()
        kwargs["stderr"] = errors
    kwargs.setdefault("stdout", subprocess.PIPE)
    kwargs.setdefault("cwd", ROOT)
    Launching.active = True
    try:
        proc = subprocess.Popen(
            [str(a) for a in argv], start_new_session=True, **kwargs
        )
        LIVE.add(proc)
    finally:
        Launching.active = False
        if Launching.signalled:
            Launching.signalled()
    proc.errors = errors  # type: ignore[attr-defined]
    expired = threading.Event()

    def expire() -> None:
        expired.set()
        kill_group(proc)

    timer = threading.Timer(WAIT, expire)
    timer.daemon = True
    timer.start()
    try:
        yield proc
    except BaseException as e:
        if expired.is_set():
            e.add_note(f"(killed: still running after {WAIT:g} s)")
        raise
    finally:
        timer.cancel()
        kill_group(proc)
        proc.wait()
        LIVE.discard(proc)
        for f in (proc.stdin, proc.stdout, errors):
            if f is not None:
                f.close()


def stderr_text(proc: subprocess.Popen) -> str:
    """What `proc` wrote to stderr so far."""
    errors = proc.errors  # type: ignore[attr-defined]
    if errors is None or errors.closed:
        return ""
    errors.seek(0)
    return errors.read().decode(errors="replace")


# A process that makes a scratch directory and a program directory, starts a
# process of its own, tells where they are, and then waits to be signalled (or,
# with the argument `launch`, signals itself while that process is being
# started). The signal is named by the other argument.
SIGNALLED_RUN = """
import os, signal, subprocess, sys, time
sys.path.insert(0, "tests")
import stdio_test as t

launch, sig = sys.argv[1] == "launch", getattr(signal, sys.argv[2])
where = {}
popen = subprocess.Popen


def report(pid):
    print(where["dir"], where["app"], pid, sep="\\t", flush=True)


def start(argv, *args, **kwargs):
    proc = popen(argv, *args, **kwargs)
    if launch and argv[0] == "sleep":  # `running` has not got it back yet
        report(proc.pid)
        os.kill(os.getpid(), sig)
    return proc


subprocess.Popen = start
with t.scratch_dir() as made:
    app = t.ROOT / "build" / "apps" / f"made_{made.token}"
    app.mkdir(parents=True, exist_ok=True)
    where.update(dir=made.dir, app=app)
    with t.running(["sleep", "300"]) as sleeper:
        report(sleeper.pid)
        time.sleep(300)
"""


@pytest.mark.parametrize(
    "sig,when",
    [(sig, "running") for sig in STOPPED_BY] + [(signal.SIGTERM, "launch")],
    ids=lambda v: v.name if isinstance(v, signal.Signals) else v,
)
def test_m_a_signal_to_pytest_removes_what_the_tests_made(sig, when):
    # `launch`: the signal comes while `running` is still starting its process.
    made = []  # what the run made, to remove if it did not
    sleeper = 0
    try:
        with running([sys.executable, "-c", SIGNALLED_RUN, when, sig.name]) as p:
            line = p.stdout.readline().decode().rstrip("\n")
            scratch_path, app, pid = line.split("\t")
            made = [Path(scratch_path), Path(app)]
            sleeper = int(pid)
            if when == "running":
                # With `launch` the process removes them as soon as it has said
                # where they are, so they may be gone by now.
                assert all(path.is_dir() for path in made)
                os.kill(p.pid, sig)
            assert p.wait() == -sig, stderr_text(p)
        assert not any(path.exists() for path in made)
        for _ in range(100):  # it is reparented and reaped, not at once
            try:
                os.kill(sleeper, 0)
            except ProcessLookupError:
                break
            time.sleep(0.05)
        else:
            pytest.fail("the process the run started is still there")
    finally:
        for path in made:
            shutil.rmtree(path, ignore_errors=True)
        if sleeper:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(sleeper, signal.SIGKILL)


def test_n_a_program_run_through_the_launcher_dies_of_a_closed_pipe(scratch):
    # Python ignores SIGPIPE, and exec keeps an ignored signal ignored, so
    # unless the launcher resets it `uv run kod run prog | head` is a program
    # that writes to a pipe nobody reads and carries on.
    with running([sys.executable, "-m", "kod", "run", scratch.program("huge")]) as p:
        assert p.stdout.read(1) == b"0", stderr_text(p)
        p.stdout.close()
        assert p.wait() == -signal.SIGPIPE, stderr_text(p)


def test_running_stops_what_a_failing_block_started():
    with pytest.raises(AssertionError):
        with running(["sleep", "300"]) as p:
            pid = p.pid
            raise AssertionError("the block fails while the process runs")
    with pytest.raises(ProcessLookupError):
        os.killpg(pid, 0)


def test_running_ends_a_wait_that_takes_too_long(monkeypatch):
    monkeypatch.setitem(globals(), "WAIT", 0.5)
    with pytest.raises(AssertionError) as failure:
        with running(["sleep", "300"]) as p:
            # `sleep` writes nothing: this read ends when the process is killed.
            assert p.stdout.read() == b"output"
    assert "killed: still running after 0.5 s" in "".join(failure.value.__notes__)
