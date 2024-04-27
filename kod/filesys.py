"""A simple file system abstraction."""

import os
import tempfile
from pathlib import Path
from typing import IO


class FileSystem:
    """A simple file system abstraction."""

    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path

    def _resolve_path(self, path: Path) -> Path:
        """Resolve a path to an absolute path."""
        path = self.root_path / path
        if not path.is_relative_to(self.root_path):
            raise ValueError(f"Path '{path}' is not within the root path.")
        return path

    def _open(self, path: Path, mode: str = "r", encoding: str = "utf8") -> IO:
        """Open the file with the given path."""
        return open(path, mode=mode, encoding=encoding)

    def open(
        self, path: Path, mode: str = "r", encoding: str = "utf8"
    ) -> "FileWrapper":
        """Open the file with the given path."""
        path = self._resolve_path(path)
        return FileWrapper(self, path, self._open(path, mode, encoding))

    def __repr__(self):
        return f"{self.__class__.__name__}(root_path={self.root_path!r})"


class FakeFileSystem(FileSystem):
    """A fake file system for testing."""

    def __init__(self, files: dict[str, str | bytes]) -> None:
        self._dir = tempfile.TemporaryDirectory(prefix="kod-build-")
        self.root_path = Path(self._dir.name)
        for path, content in files.items():
            path = self._resolve_path(Path(path))
            if isinstance(content, str):
                path.write_text(content)
            else:
                path.write_bytes(content)
        os.makedirs(self.root_path / "build")


class FileWrapper:
    """A wrapper for a file."""

    def __init__(self, fs: FileSystem, path: Path, file: IO):
        self.fs = fs
        self.path = path
        self.file = file

    def __repr__(self):
        return f"{self.__class__.__name__}(path={self.path!r})"

    @property
    def canonical_module_path(self):
        """Return the canonical module name."""
        return self.path.relative_to(self.fs.root_path).with_suffix("")

    def __getattr__(self, name):
        return getattr(self.file, name)
