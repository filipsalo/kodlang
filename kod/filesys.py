"""A simple file system abstraction."""

from io import StringIO
from pathlib import Path
from typing import IO, Self


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

    @classmethod
    def from_dict(cls, files: dict[str, str | bytes]) -> Self:
        """Create a fake file system from a dictionary."""
        fs = cls()
        for path, content in files.items():
            fs.files[fs.root_path / path] = (
                content.encode("utf8") if isinstance(content, str) else content
            )
        return fs

    def __init__(self, fake_root_path: Path = Path("/")):
        self.root_path = fake_root_path
        self.files = {}

    def _open(self, path: Path, mode: str = "r", encoding: str = "utf8") -> IO:
        """Open the file with the given path."""
        assert mode == "r"
        if path not in self.files:
            raise FileNotFoundError(f"File '{path}' does not exist.")
        content = self.files[path]
        file = StringIO(content.decode("utf8"))
        file.name = path
        return file


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
