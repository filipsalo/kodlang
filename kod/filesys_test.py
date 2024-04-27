import tempfile
from pathlib import Path

import pytest

from .filesys import FakeFileSystem, FileSystem


class TestFilesys:
    @pytest.fixture
    def fs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            tmp_dir = Path(tmp_dir)
            with open(tmp_dir / "hello.txt", "w") as f:
                f.write("Hello, real world!")
            yield FileSystem(tmp_dir)

    def test_can_read_file(self, fs: FileSystem):
        f = fs.open(Path("hello.txt"))
        assert f.read() == "Hello, real world!"

    def test_raises_filenotfound(self, fs: FileSystem):
        with pytest.raises(FileNotFoundError):
            fs.open(Path("nosuchfile.txt"))

    def test_has_name(self, fs: FileSystem):
        filename = Path("hello.txt")
        f = fs.open(filename)
        assert Path(f.name).relative_to(fs.root_path) == filename


class TestFakeFilesys:
    @pytest.fixture
    def fs(self):
        files = {
            "hello.txt": "Hello, fake world!",
            "unicode.txt": "🌍",
            "unicode-bytes.txt": b"\xf0\x9f\x8c\x8d",
        }
        return FakeFileSystem(files)

    def test_can_read_file(self, fs: FileSystem):
        f = fs.open(Path("hello.txt"))
        assert f.read() == "Hello, fake world!"

    def test_raises_filenotfound(self, fs: FileSystem):
        with pytest.raises(FileNotFoundError):
            fs.open(Path("nosuchfile.txt"))

    def test_unicode(self, fs: FileSystem):
        f = fs.open(Path("unicode.txt"))
        assert f.read() == "🌍"

    def test_unicode_bytes(self, fs: FileSystem):
        f = fs.open(Path("unicode-bytes.txt"))
        assert f.read() == "🌍"

    def test_has_name(self, fs: FileSystem):
        filename = Path("hello.txt")
        f = fs.open(filename)
        assert Path(f.name).relative_to(fs.root_path) == filename
