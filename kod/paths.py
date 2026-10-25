import sys
from pathlib import Path


def find_stdlib_path() -> Path:
    """Find the path to the standard library."""
    # This checkout's own stdlib first: a worktree run with another
    # checkout's .venv python would otherwise load that checkout's stdlib.
    local = Path(__file__).resolve().parent.parent / "stdlib"
    if local.is_dir():
        return local
    for parent in Path(sys.executable).parents:
        if (parent / "stdlib").is_dir():
            return parent / "stdlib"
    raise SystemExit("kod: can't find the stdlib; run kod from a Kod checkout")
