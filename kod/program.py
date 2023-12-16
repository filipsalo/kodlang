from pathlib import Path


class Module:
    """A module is a collection of functions."""
    def __init__(self, name: str, path: Path, ast):
        self.name = name
        self.source_path = path
        self.ast = ast
        self.asm_path = Path(self.mangled_name()).with_suffix(".s")
        self.object_path = Path(self.mangled_name()).with_suffix(".o")

    def __repr__(self):
        return f"<Module {self.name}>"

    def mangled_name(self):
        """Return the mangled name of the module."""
        return f"_{self.name.replace('/', '$')}"


class Program:
    """A program is a collection of modules."""
    def __init__(self):
        self.modules = {}

    def __iter__(self):
        return iter(self.modules.values())

    def get_module(self, name):
        """Get a module by name."""
        return self.modules[name]

    def add_module(self, module):
        """Add a module to the program."""
        self.modules[module.name] = module
