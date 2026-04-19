"""Built-in types for Kod."""

import dataclasses
from abc import ABC
from typing import Any, Self


class Type:
    """A type in Kod."""

    name = "Type"

    def __init__(self, value: Any):
        self.value = value

    def __repr__(self):
        return f"<{self.name} {self.value!r}>"

    @staticmethod
    def from_name(name) -> "type[Type]":
        """Return a type from a name."""
        match name:
            case "int64":
                return Int64
            case "str":
                return String
            case "none":
                return NoneType
        raise ValueError(f"Unknown type {name!r}")

    def to_str(self) -> "String":
        """Return the value as a Kod string."""
        return String(str(self.value).encode("utf8"))

    def op_plus(self, other: Self) -> Self:
        """Add two integers."""
        return self.__class__(self.value + other.value)

    def op_minus(self, other: Self) -> Self:
        """Add two integers."""
        return self.__class__(self.value - other.value)

    def op_eq(self, other: Self) -> "Bool":
        """Compare two values."""
        if isinstance(other, NoneType):
            return Bool(False)
        return Bool(self.value == other.value)

    def op_ne(self, other: Self) -> "Bool":
        """Compare two values for inequality."""
        return Bool(self.value != other.value)

    def op_lt(self, other: Self) -> "Bool":
        """Compare two integers."""
        return Bool(self.value < other.value)

    def op_le(self, other: Self) -> "Bool":
        """Compare two integers."""
        return Bool(self.value <= other.value)

    def op_gt(self, other: Self) -> "Bool":
        """Compare two integers."""
        return Bool(self.value > other.value)

    def op_ge(self, other: Self) -> "Bool":
        """Compare two integers."""
        return Bool(self.value >= other.value)

    def op_mod(self, other: Self) -> Self:
        """Modulo two integers."""
        return self.__class__(self.value % other.value)

    def op_div(self, other: Self) -> Self:
        """Divide two integers."""
        return self.__class__(self.value // other.value)

    def op_mul(self, other: Self) -> Self:
        """Multiply two integers."""
        return self.__class__(self.value * other.value)


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


class NoneType(Type):
    """The none type."""

    name = "none"
    width = 8

    def to_bool(self) -> "Bool":
        return Bool(False)

    def op_eq(self, other) -> "Bool":
        return Bool(isinstance(other, NoneType))

    def op_ne(self, other) -> "Bool":
        return Bool(not isinstance(other, NoneType))


# Keep None_ as an alias for backward compatibility
None_ = NoneType

none_value = NoneType(None)


class ArrayType(Type, ABC):
    """An array type."""

    _cache: dict[Any, Any] = {}

    @classmethod
    def make(cls, item_type: type[Type]) -> type[Self]:
        """Make an array type."""
        if item_type not in cls._cache:
            python_name = f"{item_type.name}Array"
            kod_name = f"[{item_type.name}]"
            cls._cache[item_type] = type(
                python_name,
                (ArrayType,),
                {
                    "name": kod_name,
                    "item_type": item_type,
                    "__repr__": cls._subclass__repr__,
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
        field_ids = [f.id for f in fields]

        def __repr__(self):
            parts = ", ".join(f"{fid}={getattr(self, fid)!r}" for fid in field_ids)
            return f"<{name}({parts})>"

        data_class = dataclasses.make_dataclass(
            name,
            [(field.id, field.type) for field in fields],
            bases=(cls,),
            namespace={"__repr__": __repr__},
            kw_only=True,
        )

        field_offsets = {}
        offset = 0
        for field in fields:
            field_offsets[field.id] = offset
            offset += field.type.width
        data_class.width = offset
        data_class.struct_fields = fields
        data_class.field_offsets = field_offsets

        return data_class
