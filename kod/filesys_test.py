import tempfile
from pathlib import Path

import pytest

from .filesys import FakeFileSystem, FileSystem


class TestFilesys:
    @pytest.fixture
    def fs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir = Path(tmp_dir)
            (tmp_dir / "hello.txt").write_text("Hello, real world!")
            yield FileSystem(tmp_dir)

    def test_can_read_file(self, fs: FileSystem):
        with fs.open(Path("hello.txt")) as f:
            assert f.read() == "Hello, real world!"

    def test_raises_filenotfound(self, fs: FileSystem):
        with pytest.raises(FileNotFoundError):
            fs.open(Path("nosuchfile.txt"))


class TestFakeFilesys:
    @pytest.fixture
    def fs(self):
        files = {
            "hello.txt": "Hello, fake world!",
            "unicode.txt": "🌍",
            "unicode-bytes.txt": b"\xf0\x9f\x8c\x8d",
        }
        return FakeFileSystem.from_dict(files)

    def test_can_read_file(self, fs: FileSystem):
        with fs.open(Path("hello.txt")) as f:
            assert f.read() == "Hello, fake world!"

    def test_raises_filenotfound(self, fs: FileSystem):
        with pytest.raises(FileNotFoundError):
            fs.open(Path("nosuchfile.txt"))

    def test_unicode(self, fs: FileSystem):
        with fs.open(Path("unicode.txt")) as f:
            assert f.read() == "🌍"

    def test_unicode_bytes(self, fs: FileSystem):
        with fs.open(Path("unicode-bytes.txt")) as f:
            assert f.read() == "🌍"
