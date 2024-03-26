"""A simple file system abstraction."""

from io import StringIO
from pathlib import Path
from typing import Self


class FileSystem:
    """A simple file system abstraction."""

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path

    def _resolve_path(self, path: Path) -> Path:
        """Resolve a path to an absolute path."""
        if path.is_absolute():
            if not path.is_relative_to(self.root_path):
                raise ValueError(f"Path '{path}' is not within the root path.")
            return path
        return self.root_path / path

    def open(self, path: Path, mode: str = "r", encoding: str = "utf8"):
        """Open the file with the given path."""
        path = self._resolve_path(path)
        return open(path, mode=mode, encoding=encoding)


class FakeFileSystem:
    """A fake file system for testing."""

    @classmethod
    def from_dict(cls, files: dict[str, str | bytes]) -> Self:
        """Create a fake file system from a dictionary."""
        fs = cls()
        for path, content in files.items():
            fs.files[Path(path)] = (
                content.encode("utf8") if isinstance(content, str) else content
            )
        return fs

    def __init__(self):
        self.files = {}

    def open(self, path, _mode="r"):
        """Open the file with the given path."""
        assert _mode == "r"
        if path not in self.files:
            raise FileNotFoundError(f"File '{path}' does not exist.")
        content = self.files[path]
        return StringIO(content.decode("utf8"))
