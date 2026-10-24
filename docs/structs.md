---
icon: lucide/box
---

# Structs

Structs are named product types — a fixed set of named fields.

## Declaration

```kod
type Point = struct {
    x: int64
    y: int64
}
```

Comments are allowed inside the body:

```kod
type Rect = struct {
    // top-left corner
    x: int64
    y: int64
    // dimensions
    width: int64
    height: int64
}
```

A field's type can name the struct itself:

```kod
type Node = struct {
    kids: [Node]
    parent: Node?
    name: str
}
```

## Construction

Pass fields by name using labeled arguments:

```kod
let p: Point = Point(x: 10, y: 20)
```

Every field must be supplied unless it has a [default](#field-defaults).
Omitting a field with no default is a compile error — there's no
implicit zero/null value:

```kod
let p: Point = Point(x: 10)   // error: struct `Point` requires field `y`
```

Each field value must have the field's type, with the same implicit
conversions as a [function argument](functions.md#argument-types):
`Point(x: "a", y: 1)` is an error (`` expected `int64`, got `str` ``), while
`3` is fine for an `int64?` field and a struct for an interface field. A
field can be given only once: `Point(x: 1, x: 2, y: 3)` is an error
(`` field `x` is given twice ``).

## Field defaults

A field may declare a default with `= expr`. When a construction omits
that field, the default expression is evaluated and stored:

```kod
type Counter = struct {
    label: str
    count: int64 = 0
    history: [int64] = []
}

let c: Counter = Counter(label: "hits")   // count = 0, history = []
let d: Counter = Counter(label: "x", count: 5)
```

The default is evaluated fresh at each construction (so a `[]` default
yields a new empty array per instance, not a shared one). Defaults are
ordinary expressions evaluated in the struct's defining module, and they
can't see the local variables of the function doing the construction. A
default must have its field's type. It is checked where it is declared, so
`count: int64 = "x"` is an error even if no construction omits `count`; a
generic struct's default is checked at each construction that omits it.

This is what lets the built-in `Map[K, V]` be created with no arguments —
all three of its fields default to `[]`:

```kod
let m: Map[str, int64] = Map[str, int64]()
```

## Field access

```kod
print_int(p.x)
print_int(p.y)
```

## Field mutation

```kod
p.x = p.x + 1
```

Reading or assigning a field the struct doesn't declare is an error, with
a did-you-mean hint when the name is close to a real field. So is `.field`
on a value that isn't a struct, such as an interface or an optional; for a
`T?`, use `p?.x`.

## Methods

Define methods inside the struct body. The first parameter must be `self`:

```kod
type Point = struct {
    x: int64
    y: int64

    func distance_sq(self) -> int64 {
        return self.x * self.x + self.y * self.y
    }

    func translate(self, dx: int64, dy: int64) -> none {
        self.x = self.x + dx
        self.y = self.y + dy
    }
}
```

Call methods with dot notation:

```kod
let p: Point = Point(x: 3, y: 4)
print_int(p.distance_sq())   // 25
p.translate(dx: 1, dy: 0)
print_int(p.x)               // 4
```

Methods can also be invoked on non-`Ident` receivers — `0.to_str()`,
`p.field.method()`, `f().bar()`, etc.

A method's parameter and return types can name the struct itself or a type
declared later in the module, so `func scaled(self, by: int64) -> Point`
inside `Point` chains as `p.scaled(by: 2).distance_sq()`.

## Generic structs

Type parameters in square brackets after the name; each unique
instantiation is monomorphised:

```kod
type Pair[A, B] = struct {
    first: A
    second: B

    func swap(self) -> Pair[B, A] {
        return Pair[B, A](first: self.second, second: self.first)
    }
}

let p: Pair[str, int64] = Pair[str, int64](first: "hello", second: 42)
let q = p.swap()    // Pair[int64, str]
```

Construction always spells the type arguments; a bare `Pair(...)` is an
error.

Every method of an instance is compiled for its type arguments, whether
it's called or not, so each must make sense for them. An error in one
names the instance, as in
`` `<` doesn't take `Color` operands (in `Box[Color]`) ``, and a line of
the template is reported for one instance only.

A generic struct or enum may name itself, with any type arguments, in its
fields, payloads and method signatures, as in `kids: [Tree[T]]` or the
`Pair[B, A]` above. The Python interpreter (`kod _interpret`) does not
parse these yet.

The built-in `Map[K, V]` is the canonical example.

## Equality

Structs have no `==` or `!=`: comparing two struct values is an error, even
two of the same type. Compare the fields you care about instead, as in
`a.x == b.x and a.y == b.y`.

## Memory layout (compiler)

Struct fields are laid out sequentially, each taking 8 bytes, allocated on an arena:

```
[ offset 0  ] field_0 : 8 bytes
[ offset 8  ] field_1 : 8 bytes
...
```

Struct variables hold a pointer to the arena allocation.
