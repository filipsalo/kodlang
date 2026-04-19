from pathlib import Path
from typing import Iterator, Optional

from kod.ast import Module
from kod.filesys import FileSystem, FileWrapper


class Program:
    """A program is a collection of modules."""

    def __init__(self, root_fs: FileSystem, stdlib_fs: FileSystem) -> None:
        self.root_fs = root_fs
        self.stdlib_fs = stdlib_fs
        self.builtins: Module
        self.modules: dict[Path, Module] = {}

    def __iter__(self) -> Iterator[Module]:
        return iter([self.builtins, *self.modules.values()])

    def get_module(self, name: Path) -> Module:
        """Get a module by name."""
        dbg("getting", name, "among", self.modules.keys())
        return self.modules[name]

    def add_module(self, module: Module) -> None:
        """Add a module to the program."""
        self.modules[module.source_file.canonical_path.with_suffix("")] = module

    def resolve_import(
        self, module_name: str, relative_to: Optional[Path] = None
    ) -> FileWrapper:
        """Resolve a name to a Path"""
        path = Path(module_name).with_suffix(".kod")
        if module_name.startswith("./"):
            fs = self.root_fs
            if relative_to:
                path = relative_to.parent / path
        else:
            fs = self.stdlib_fs
        return fs.open(path)
