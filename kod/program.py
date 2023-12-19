from pathlib import Path


class BuildModule:
    """A module is a collection of functions."""
    def __init__(self, module):
        self.module = module
        self.name = module.name
        self.source_path = module.path
        self.asm_path = Path(self.mangled_name()).with_suffix(".s")
        self.object_path = Path(self.mangled_name()).with_suffix(".o")

    def __repr__(self):
        return f"<BuildModule {self.module.name}>"

    def mangled_name(self):
        """Return the mangled name of the module."""
        return f"_{self.module.name.replace('/', '$')}"


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
