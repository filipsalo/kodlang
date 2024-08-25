from pathlib import Path

from kod.ast import Module


class BuildModule:
    """A module is a collection of functions."""

    def __init__(self, module: Module):
        self.module = module
        self.name = str(module.file.canonical_module_path)
        self.source_path = module.file.path
        self.asm_path = Path(self.mangled_name()).with_suffix(".s")
        self.object_path = Path(self.mangled_name()).with_suffix(".o")

    def __repr__(self):
        return f"<BuildModule {self.name}>"

    def mangled_name(self):
        """Return the mangled name of the module."""
        return f"_{self.name.replace('/', '$')}"


class Program:
    """A program is a collection of modules."""

    def __init__(self, builtins: BuildModule):
        self.builtins = builtins
        self.modules: dict[Path, BuildModule] = {}

    def __iter__(self):
        return iter([self.builtins, *self.modules.values()])

    def get_module(self, name: Path):
        """Get a module by name."""
        return self.modules[name]

    def add_module(self, module):
        """Add a module to the program."""
        self.modules[module.source_path] = module
