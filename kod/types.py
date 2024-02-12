"""Built-in types for Kod."""


from abc import ABC
import dataclasses
from typing import Any, Self


class Type:
    """A type in Kod."""
    name = "Type"

    def __init__(self, value: Any):
        self.value = value

    def __repr__(self):
        return f"<{self.name} {self.value!r}>"

    @staticmethod
    def from_name(name):
        """Return a type from a name."""
        match name:
            case "int64": return Int64
            case "str": return String
            case "none": return None_
        raise ValueError(f"Unknown type {name!r}")


class Bool(Type):
    """A boolean."""
    name = "bool"
    width = 1

    def to_bool(self):
        """Return the value as a Kod boolean."""
        return self


class String(Type):
    """A UTF-8 string."""
    name = "str"
    width = 8

    def __eq__(self, other):
        return self.value == other.value

    def __hash__(self):
        return hash(repr(self))

    def to_py_str(self):
        """Return the value as a Python string."""
        return self.value.decode("utf8")

    def to_str(self):
        """Return the value as a Kod string."""
        return self

    def op_plus(self, other):
        """Concatenate two strings."""
        return String(self.value + other.value)


class Int64(Type):
    """A 64-bit integer."""
    name = "int64"
    width = 8

    def to_str(self) -> String:
        """Return the value as a Kod string."""
        return String(str(self.value).encode("utf8"))

    def op_plus(self, other: Self) -> Self:
        """Add two integers."""
        return Int64(self.value + other.value)

    def op_minus(self, other: Self) -> Self:
        """Add two integers."""
        return Int64(self.value - other.value)

    def op_eq(self, other: Self) -> Bool:
        """Compare two integers."""
        return Bool(self.value == other.value)

    def op_lt(self, other: Self) -> Bool:
        """Compare two integers."""
        return Bool(self.value < other.value)

    def op_gt(self, other: Self) -> Bool:
        """Compare two integers."""
        return Bool(self.value > other.value)

    def op_mod(self, other: Self) -> Self:
        """Modulo two integers."""
        return Int64(self.value % other.value)

    def op_div(self, other: Self) -> Self:
        """Divide two integers."""
        return Int64(self.value // other.value)

    def op_mul(self, other: Self) -> Self:
        """Multiply two integers."""
        return Int64(self.value * other.value)


None_ = object()


class ArrayType(Type, ABC):
    """An array type."""
    _cache = {}

    @classmethod
    def make(cls, item_type: Type):
        """Make an array type."""
        if item_type not in cls._cache:
            python_name = f"{item_type.__name__}Array"
            kod_name = f"[{item_type.name}]"
            cls._cache[item_type] = type(
                python_name,
                (ArrayType,),
                {
                    "name": kod_name,
                    "item_type": item_type,
                    "__repr__": cls._subclass__repr__
                },
            )
        return cls._cache[item_type]

    @staticmethod
    def _subclass__repr__(subclass_instance):
        return f"<{subclass_instance.__class__.__name__} {subclass_instance.value!r}>"

    def op_index(self, index: Type):
        """Index into the array."""
        return self.value[index.value]


class StructType(Type, ABC):
    """A struct type."""

    @classmethod
    def make(cls, name, fields):
        """Make a struct type."""
        data_class = dataclasses.make_dataclass(
            name,
            [(field.id, field.type) for field in fields],
            bases=(cls,),
            namespace={"__repr__": cls._subclass__repr__},
            kw_only=True,
        )
        return data_class

    @staticmethod
    def _subclass__repr__(subclass_instance):
        return f"<{subclass_instance.__class__.__name__} {subclass_instance.value!r}>"
