import sys
from pathlib import Path


def find_stdlib_path() -> Path:
    """Find the path to the standard library."""
    stdlib_path = Path(sys.executable)
    while not (stdlib_path / "stdlib").is_dir():
        stdlib_path = stdlib_path.parent
    stdlib_path = stdlib_path / "stdlib"
    return stdlib_path
