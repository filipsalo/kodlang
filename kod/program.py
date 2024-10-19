from pathlib import Path
from typing import Iterator

from kod.ast import Module


class Program:
    """A program is a collection of modules."""

    def __init__(self, builtins: Module) -> None:
        self.builtins = builtins
        self.modules: dict[Path, Module] = {}

    def __iter__(self) -> Iterator[Module]:
        return iter([self.builtins, *self.modules.values()])

    def get_module(self, name: Path) -> Module:
        """Get a module by name."""
        return self.modules[name]

    def add_module(self, module) -> None:
        """Add a module to the program."""
        self.modules[module.canonical_name] = module
