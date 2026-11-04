#!/usr/bin/env python
"""I am the Kod language.

User-facing commands (run from the repository root; they refresh the toolchain
with `make` and hand off to the native tool, build/apps/kod/kod):
    kod build <file>     compile to an executable
    kod run <file>       build, then execute
    kod check <file>     compile through codegen; report errors but emit no
                         artifacts (exits non-zero if anything failed)
    kod test <path>      run `test` blocks in a file, or in every
                         `*_test.kod` under a directory
"""

import argparse
import fcntl
import os
import signal
import subprocess
import sys
from pathlib import Path

_NATIVE_COMMANDS = {"build", "run", "test", "check"}


def _make_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="kod")

    subparsers = parser.add_subparsers(dest="command", metavar="<command>")
    subparsers.required = True

    # Public commands. They never get here: `main` hands them to the native
    # tool before parsing; they are listed for `--help`.
    p = subparsers.add_parser("build", help="compile to an executable")
    p.add_argument("file", type=str)

    p = subparsers.add_parser("run", help="build, then execute")
    p.add_argument("file", type=str)
    p.add_argument("args", nargs="*")

    p = subparsers.add_parser(
        "check", help="parse + codegen; report errors but emit nothing"
    )
    p.add_argument("file", type=str)

    p = subparsers.add_parser("test", help="run `test` blocks")
    p.add_argument("path", type=str)

    return parser


def _refresh_toolchain(root: Path) -> None:
    """Rebuild sh_kodc, the stage0 objects and the native driver if any of
    their sources changed. The up-to-date check (`make -q`) costs ~10 ms.
    A lock serializes concurrent `kod` invocations so two rebuilds never
    write the same objects at once."""
    targets = ["stage1", "kod"]
    # Don't inherit an outer `make test`'s flags (-B would rebuild on
    # every call, -j prints jobserver warnings, -i hides failures).
    env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("MAKEFLAGS", "MFLAGS", "MAKELEVEL")
    }
    (root / "build").mkdir(exist_ok=True)
    with open(root / "build" / ".toolchain.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            up_to_date = subprocess.run(
                ["make", "-s", "-q", *targets], cwd=root, env=env, check=False
            )
        except FileNotFoundError:
            return
        if up_to_date.returncode == 0:
            return
        result = subprocess.run(
            ["make", "-s", *targets],
            cwd=root,
            env=env,
            stdout=sys.stderr,
            check=False,
        )
    if result.returncode != 0:
        print("kod: failed to rebuild the toolchain", file=sys.stderr)
        sys.exit(result.returncode)


def _hand_off_to_native() -> int:
    """Exec `build/apps/kod/kod` with the same argv. From the repo root,
    first bring the toolchain up to date. There is no other way to build:
    when the native tool is missing, say so."""
    root = Path.cwd()
    if (root / "Makefile").exists() and (root / "kodc.kod").exists():
        _refresh_toolchain(root)
    native = root / "build" / "apps" / "kod" / "kod"
    if not native.exists():
        print(
            "kod: build/apps/kod/kod not found; "
            "run kod from the repository root after `make kod`",
            file=sys.stderr,
        )
        return 1
    # Python ignores SIGPIPE and SIGXFSZ, and exec keeps what is ignored: the
    # program (`kod run` replaces itself with it) would not die of a closed
    # pipe, as it does when the shell starts it.
    for ignored in (signal.SIGPIPE, signal.SIGXFSZ):
        signal.signal(ignored, signal.SIG_DFL)
    os.execv(str(native), [str(native), *sys.argv[1:]])


def main():
    """Main entry point."""
    if len(sys.argv) > 1 and sys.argv[1] in _NATIVE_COMMANDS:
        return _hand_off_to_native()

    _make_parser().parse_args()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
