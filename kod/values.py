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
            case "bool":
                return Bool
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

    def op_plus(self, other: "String") -> "String":
        """Concatenate two strings. Non-string operands must be cast
        explicitly: `"x = " + str(n)`."""
        return String(self.value + other.value)

    def op_index(self, index: "Int64") -> "Int64":
        return Int64(self.value[index.value])


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
                    "width": 8,
                    "data_width": 24,
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

    def op_plus(self, other: "ArrayType") -> "ArrayType":
        """Concatenate two arrays."""
        return type(self)(self.value + other.value)


class StructType(Type, ABC):
    """A struct type."""

    @classmethod
    def make(cls, name, fields, methods=None):
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
        data_class.data_width = offset  # actual struct size (for arena allocation)
        data_class.width = 8  # pointer size (for stack frame layout)
        data_class.struct_fields = fields
        data_class.field_offsets = field_offsets
        data_class.methods = methods or {}

        return data_class


@dataclasses.dataclass
class EnumVariantInfo:
    """Info about a single enum variant."""

    name: str
    fields: list  # list of Variable AST nodes
    discriminant: int
    field_offsets: dict  # field_id -> byte offset within payload
    payload_width: int


class EnumValue(Type):
    """A runtime enum value."""

    def __init__(self, enum_type, variant_name, fields):
        super().__init__(None)
        self.enum_type = enum_type
        self.variant_name = variant_name
        self.fields = fields  # dict: field_name -> value

    def to_bool(self):
        return Bool(True)

    def op_eq(self, other):
        if isinstance(other, EnumValue):
            return Bool(
                self.enum_type is other.enum_type
                and self.variant_name == other.variant_name
            )
        return Bool(False)

    def op_ne(self, other):
        return Bool(not self.op_eq(other).value)

    def __repr__(self):
        return f"<{self.enum_type.name}.{self.variant_name}({self.fields!r})>"


class EnumVariantConstructor:
    """Callable constructor for enum variants with payload fields."""

    def __init__(self, enum_type, variant_name, field_names):
        self.enum_type = enum_type
        self.variant_name = variant_name
        self.field_names = field_names

    def __call__(self, *args):
        fields = dict(zip(self.field_names, args))
        return EnumValue(self.enum_type, self.variant_name, fields)


class OptionalType(Type):
    """Base class for optional types (T?)."""

    inner_type: "type[Type]"

    @classmethod
    def make(cls, inner: "type[Type]") -> "type[OptionalType]":
        """Create an optional type wrapping inner. None = null pointer, Some(v) = heap pointer."""
        return type(
            f"{inner.name}Optional",
            (cls,),
            {
                "name": f"{inner.name}?",
                "inner_type": inner,
                "width": 8,
                "data_width": 8,  # heap slot for Some payload
            },
        )

    def op_eq(self, other) -> "Bool":
        if isinstance(other, NoneType):
            return Bool(isinstance(self, NoneType))
        return Bool(self.value == other.value if hasattr(other, "value") else False)

    def op_ne(self, other) -> "Bool":
        return Bool(not self.op_eq(other).value)


class ResultType(Type):
    """A fallible result: `T or Error`. The Python interpreter doesn't
    actually wrap returned values — it propagates Err through Python
    exceptions — but we need a named type so `parse_type` produces
    something inhabitable. Width matches a pointer (the compiled
    representation is a single arena pointer)."""

    name = "ResultType"

    @classmethod
    def make(cls, inner):
        return type(
            f"{inner.name}Result",
            (cls,),
            {
                "name": f"{inner.name} or Error",
                "inner_type": inner,
                "width": 8,
                "data_width": 16,  # discriminant + payload
            },
        )


class EnumType:
    """Base class for dynamically-created enum types."""

    @classmethod
    def make(cls, name, variants):
        """Create an enum type. variants is list of (name, fields) tuples."""
        variant_infos = {}
        max_payload_width = 0

        for i, (variant_name, fields) in enumerate(variants):
            field_offsets = {}
            offset = 0
            for field in fields:
                field_offsets[field.id] = offset
                offset += field.type.width
            payload_width = offset
            max_payload_width = max(max_payload_width, payload_width)
            variant_infos[variant_name] = EnumVariantInfo(
                name=variant_name,
                fields=fields,
                discriminant=i,
                field_offsets=field_offsets,
                payload_width=payload_width,
            )

        enum_class = type(
            name,
            (cls,),
            {
                "name": name,
                "data_width": 8
                + max_payload_width,  # actual enum size (for arena allocation)
                "width": 8,  # pointer size (for stack frame layout)
                "variants": variant_infos,
                "payload_offset": 8,
                "max_payload_width": max_payload_width,
            },
        )

        for variant_name, info in variant_infos.items():
            if info.fields:
                setattr(
                    enum_class,
                    variant_name,
                    EnumVariantConstructor(
                        enum_class, variant_name, [f.id for f in info.fields]
                    ),
                )
            else:
                setattr(
                    enum_class,
                    variant_name,
                    EnumValue(enum_class, variant_name, {}),
                )

        return enum_class


class InterfaceType(Type):
    """A type-erased interface value. The interpreter never inspects this —
    method calls are resolved dynamically on the underlying instance.

    Also used as a forward-reference placeholder for self-referential
    type declarations (e.g. recursive enums), so width must match a
    pointer-sized field."""

    name = "InterfaceType"
    width = 8


class TypeParam(Type):
    """A type parameter placeholder used during generic type parsing."""

    param_name = ""
    width = 8

    @classmethod
    def make(cls, name: str) -> "type[TypeParam]":
        return type(
            f"TypeParam_{name}", (cls,), {"param_name": name, "name": name, "width": 8}
        )


def _substitute_type(t, subst: dict):
    """Recursively substitute TypeParam placeholders with concrete types."""
    if isinstance(t, type) and issubclass(t, TypeParam):
        return subst[t.param_name]
    if isinstance(t, type) and issubclass(t, ArrayType) and hasattr(t, "item_type"):
        return ArrayType.make(_substitute_type(t.item_type, subst))
    if isinstance(t, type) and issubclass(t, OptionalType) and hasattr(t, "inner_type"):
        return OptionalType.make(_substitute_type(t.inner_type, subst))
    return t


class GenericTemplate:
    """A parameterized type template (e.g. HashMap[K, V])."""

    def __init__(self, name: str, param_names: list[str], template_struct):
        self.name = name
        self.param_names = param_names
        self.template_struct = template_struct
        self._cache: dict = {}

    def instantiate(self, type_args: tuple) -> type:
        if type_args in self._cache:
            return self._cache[type_args]
        subst = dict(zip(self.param_names, type_args))
        new_fields = [
            dataclasses.replace(f, type=_substitute_type(f.type, subst))
            for f in self.template_struct.struct_fields
        ]
        inst_name = f"{self.name}[{', '.join(t.name for t in type_args)}]"
        result = StructType.make(inst_name, new_fields, self.template_struct.methods)
        self._cache[type_args] = result
        return result
