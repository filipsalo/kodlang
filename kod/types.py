"""Built-in types for Kod."""

from collections import namedtuple


Type = namedtuple("Type", ["name", "width"])

# The types in Kod
Int64 = Type("int64", 8)
Int32 = Type("int32", 4)
String = Type("str", 8)
Boolean = Type("bool", 1)
None_ = Type("none", 0)

BUILTIN_TYPES = {
    "int64": Int64,
    "int32": Int32,
    "str": String,
    "bool": Boolean,
    "None": None_,
}
