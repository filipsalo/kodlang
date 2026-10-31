"""`kod run` and `kod test` replace themselves with the program (docs/cli.md):
output streams as it is written, stdin is the caller's, and the exit status or
signal is the program's own. The test reporter flushes around its lines, so the
order survives a pipe. The programs are the fixtures in tests/stdio/.

Every wait is bounded: a process that does not answer within `WAIT` seconds is
killed with everything it started, so a regression fails the test instead of
hanging it. Everything a test starts is stopped and everything it makes under
`build/` is removed when it ends, also when pytest is stopped by SIGINT, SIGTERM
or SIGHUP (a SIGKILL of pytest itself cannot be caught and leaves nothing but
ignored files there)."""

import contextlib
import os
import pty
import re
import select
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
CANARY = ROOT / "tests" / "test_block_canary.kod"

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
    then end this process by that signal."""

    def stop(signum: int, frame) -> None:
        if Launching.active:
            Launching.signalled = lambda: stop(signum, frame)
            return
        for proc in list(LIVE):
            kill_group(proc)
        remove()
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
    """Start `argv` from the repository root in a session of its own, with
    stdout a pipe and stderr a file (`stderr_text(proc)` reads it) unless the
    caller says otherwise. After `WAIT` seconds it is killed, which ends any
    read or wait the block is blocked in. At the end of the block it is
    killed, with everything it started, and reaped."""
    errors = None
    if "stderr" not in kwargs:
        errors = tempfile.TemporaryFile()
        kwargs["stderr"] = errors
    kwargs.setdefault("stdout", subprocess.PIPE)
    Launching.active = True
    try:
        proc = subprocess.Popen(
            [str(a) for a in argv], cwd=ROOT, start_new_session=True, **kwargs
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


def test_a_program_gets_stdin_and_its_output_arrives_while_it_waits(scratch):
    # `ready` can only be read now if `kod run` is not holding the output back,
    # and the line below can only reach the program if stdin is ours.
    with running(
        [KOD, "run", scratch.program("stream_stdin")], stdin=subprocess.PIPE
    ) as p:
        first = p.stdout.readline()
        assert first == b"ready\n", stderr_text(p)
        p.stdin.write(b"hello\n")
        p.stdin.flush()
        rest = p.stdout.read()
        status = p.wait()
        assert (rest, status) == (b"got hello\n", 3), stderr_text(p)


def test_b_stdout_and_stderr_keep_their_order_in_one_pipe(scratch):
    with running(
        [KOD, "run", scratch.program("interleave")], stderr=subprocess.STDOUT
    ) as p:
        out = p.stdout.read()
        status = p.wait()
    assert out == b"out1\nerr1\nout2\nerr2\nout3\n"
    assert status == 0


def test_c_the_exit_status_is_the_programs(scratch):
    with running([KOD, "run", scratch.program("exit7")]) as p:
        assert p.stdout.read() == b""
        assert p.wait() == 7, stderr_text(p)


def test_d_a_signal_ends_the_program_and_nothing_is_left_behind(scratch):
    with running([KOD, "run", scratch.program("sigterm")], stdin=subprocess.PIPE) as p:
        assert p.stdout.readline() == b"ready\n", stderr_text(p)
        p.send_signal(signal.SIGTERM)
        status = p.wait()
        assert status == -signal.SIGTERM, stderr_text(p)
        # `p` was the program: no process of its session survives it.
        with pytest.raises(ProcessLookupError):
            os.killpg(p.pid, 0)


# 203 MiB of output; `kod run` used to hold it all, as 664-697 MB.
HUGE_BYTES = 203 * 2**20
HUGE_RSS_LIMIT = 100 * 2**20


def test_e_a_lot_of_output_is_not_held_in_memory(scratch):
    total = lines = 0
    with running([KOD, "run", scratch.program("huge")]) as p:
        fd = p.stdout.fileno()
        while chunk := os.read(fd, 1 << 20):
            total += len(chunk)
            lines += chunk.count(b"\n")
        _, wait_status, usage = os.wait4(p.pid, 0)
        p.returncode = os.waitstatus_to_exitcode(wait_status)
        assert p.returncode == 0, stderr_text(p)
    assert (total, lines) == (HUGE_BYTES, HUGE_BYTES // 16)
    # The largest process of the run, `kod` before it became the program
    # included (bytes on macOS).
    assert usage.ru_maxrss < HUGE_RSS_LIMIT, usage.ru_maxrss / 2**20


CANARY_ORDER = [
    r"^\S*test_block_canary\w*\.kod$",
    r"^\s+ok\s+canary: this test passes",
    r"^\s+\S*test_block_canary\w*\.kod:\d+:\d+: assertion failed: 1 \+ 1 == 3$",
    r"^\s+FAIL\s+canary: this test fails",
    r"^1/2 passed",
]


def assert_in_order(text: str, patterns: list[str]) -> None:
    """Every pattern matches a line, and the first matches come in the order of
    the patterns."""
    lines = text.replace("\r\n", "\n").splitlines()
    at = -1
    for pattern in patterns:
        found = [i for i, line in enumerate(lines) if re.search(pattern, line)]
        assert found, f"no line matches {pattern!r} in:\n{text}"
        assert found[0] > at, f"{pattern!r} is out of order in:\n{text}"
        at = found[0]


def read_pty(master: int) -> str:
    """Everything written to the other end of a pty until it is closed (the
    process is killed after `WAIT` seconds if that does not happen)."""
    out = b""
    while True:
        select.select([master], [], [])
        try:
            data = os.read(master, 4096)
        except OSError:  # the other end is closed
            break
        if not data:
            break
        out += data
    return out.decode(errors="replace")


def test_f_on_a_terminal_a_failure_shows_its_detail_before_its_result(scratch):
    try:
        master, slave = pty.openpty()
    except OSError as e:
        pytest.skip(f"no pty can be allocated: {e}")
    canary = scratch.copy(CANARY, f"test_block_canary_{scratch.token}.kod")
    try:
        with running(
            [KOD, "test", canary], stdin=slave, stdout=slave, stderr=slave
        ) as p:
            os.close(slave)
            slave = -1
            text = read_pty(master)
            assert p.wait() == 1, text
        # Up to the failure's result line: the summary is written as the
        # process exits, and a terminal may not hand on what is still
        # unread when its other end closes.
        assert_in_order(text, CANARY_ORDER[:-1])
    finally:
        for fd in (master, slave):
            if fd >= 0:
                os.close(fd)


@pytest.mark.parametrize("target", ["file", "directory"])
def test_g_in_one_pipe_the_test_output_keeps_its_order(scratch, target):
    # The CI-log case: stdout and stderr are one pipe.
    if target == "file":
        canary = scratch.copy(CANARY, f"test_block_canary_{scratch.token}.kod")
    else:
        walked = scratch.dir / "walked"
        canary = str(walked.relative_to(ROOT))
        scratch.copy(CANARY, "test_block_canary_test.kod", into=walked)
    with running([KOD, "test", canary], stderr=subprocess.STDOUT) as p:
        text = p.stdout.read().decode()
        status = p.wait()
    assert status == 1, text
    assert_in_order(text, CANARY_ORDER)


def test_h_kod_run_says_so_and_exits_127_when_the_program_cannot_be_executed(
    scratch,
):
    if os.geteuid() == 0:
        pytest.skip("root can execute a file without an execute bit")
    prog = scratch.program("exit7")
    name = Path(prog).stem
    # Built once the usual way, so that its directories exist; the run below
    # relinks it under a umask that leaves the executable without execute bits.
    with running([KOD, "build", prog]) as p:
        p.stdout.read()
        assert p.wait() == 0, stderr_text(p)
    argv = ["sh", "-c", 'umask 0111 && exec "$@"', "sh", KOD, "run", prog]
    with running(argv) as p:
        assert p.stdout.read() == b""
        status = p.wait()
        message = stderr_text(p)
    assert status == 127, message
    assert message == f"kod: cannot execute build/apps/{name}/{name}\n"


@pytest.mark.parametrize(
    "args,output,status",
    [
        (["echo", "hi"], b"before\nhi\n", 0),
        (["/nonexistent/program"], b"before\nexec returned -1\n", 9),
        ([], b"before\nexec returned -1\n", 9),  # nothing to run
    ],
)
def test_i_process_exec_flushes_first_and_returns_only_when_it_fails(
    scratch, args, output, status
):
    # stdout is a pipe, so "before" is still buffered when exec is called.
    with running([KOD, "run", scratch.program("exec_program"), *args]) as p:
        out = p.stdout.read()
        assert (out, p.wait()) == (output, status), stderr_text(p)


REPORT_ORDER = [
    r"^\S*report_order\w*\.kod$",
    r"^stderr in first$",
    r"^printed in first$",
    r"^\s+ok\s+first\b",
    r"^stderr in second$",
    r"^printed in second$",
    r"^\s+\S*report_order\w*\.kod:\d+:\d+: assertion failed: 1 \+ 1 == 3$",
    r"^\s+FAIL\s+second\b",
    r"^third read \[\]$",
    r"^\s+ok\s+third\b",
    r"^2/3 passed",
]


def test_j_each_flush_of_the_reporter_keeps_its_place_in_one_pipe(scratch):
    # What each block writes to stderr (unbuffered) lands between the lines the
    # reporter writes to stdout: after the file header (flushed when it is
    # written), after the `ok` line of the block before (flushed with it), and
    # after what the failing block printed (flushed before its detail).
    report = scratch.copy(
        FIXTURES / "report_order.kod", f"report_order_{scratch.token}.kod"
    )
    with running(
        [KOD, "test", report], stdin=subprocess.DEVNULL, stderr=subprocess.STDOUT
    ) as p:
        text = p.stdout.read().decode()
        status = p.wait()
    assert status == 1, text
    assert_in_order(text, REPORT_ORDER)


def test_k_each_result_arrives_while_the_next_test_runs(scratch):
    # The third block waits for a line on stdin: the result lines of the two
    # before it have to be readable now, not when the binary exits.
    report = scratch.copy(
        FIXTURES / "report_order.kod", f"report_order_{scratch.token}.kod"
    )
    with running([KOD, "test", report], stdin=subprocess.PIPE) as p:
        seen = []
        while not any(re.match(r"\s+FAIL\s+second\b", line) for line in seen):
            line = p.stdout.readline().decode()
            assert line, f"output ended after {seen}\n{stderr_text(p)}"
            seen.append(line)
        assert any(re.match(r"\s+ok\s+first\b", line) for line in seen), seen
        assert p.poll() is None
        p.stdin.write(b"go\n")
        p.stdin.close()
        rest = p.stdout.read().decode()
        status = p.wait()
    assert status == 1, stderr_text(p)
    assert "third read [go]\n" in rest, rest
    assert re.search(r"^2/3 passed", rest, re.MULTILINE), rest


@pytest.mark.parametrize("how", ["index", "kod_panic"])
def test_l_a_panic_comes_after_what_the_program_printed(scratch, how):
    # stdout is a pipe, so "before the panic" is still buffered when the panic
    # message goes to stderr, which is the same pipe.
    with running(
        [KOD, "run", scratch.program("panics"), how], stderr=subprocess.STDOUT
    ) as p:
        text = p.stdout.read().decode()
        status = p.wait()
    assert status == 1, text
    assert_in_order(text, [r"^before the panic$", r"^panic: "])


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
