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

Pass fields by name using labeled arguments, in any order:

```kod
let p: Point = Point(x: 10, y: 20)
let q: Point = Point(y: 20, x: 10)   // the same point
```

The values are computed in the order they're written. Every value needs
its label, so `Point(10, 20)` is an error at each value:

```kod
let p: Point = Point(10, 20)
// error: argument 1 of `Point` needs a field label (`x:`)
// error: argument 2 of `Point` needs a field label (`y:`)
```

Each unlabelled value is offered the next field, in declaration order,
that no label names.

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
default must have its field's type, which is checked where it is declared,
so `count: int64 = "x"` is an error even if no construction omits `count`.
Anything else wrong in it, such as an unknown name or variant, is reported
where a construction omits the field, and a generic struct's default is
checked only at each construction that omits it.

This is what lets the built-in `Map[K, V]` be created with no arguments —
all three of its fields default to `[]`:

```kod
let m: Map[str, int64] = Map[str, int64]()
```

## Custom constructors

A struct may declare its own constructor, a function named `init` inside the
body with no `self`:

```kod
type Port = struct {
    number: int64

    func init(number: int64) -> Port or Error {
        if number < 1 or number > 65535 {
            throw BadPort(number: number)
        }
        return Port(number: number)
    }
}

let p = try Port(number: 8080)     // calls init
```

From then on `Port(...)` anywhere outside the struct's own functions calls
`init`, with the usual rules for a function call: labels, defaults and
[skipped labels](functions.md). The field constructor is not available there,
so a label `init` doesn't declare is an error. `init` is the only way to make a
`Port`, and whatever it checks holds for every `Port` at the moment it is made.

Inside the struct's own functions, `init` and the other methods, `Port(...)`
is the field constructor as before. That is how `init` builds the value, and
how methods such as `op_add` make a new one without going through the checks
again. A method can't call `init` itself.

`init` must return the struct (`-> Port`) or a result of it (`-> Port or Error`),
which makes `try Port(...)` and `must Port(...)` work as for any fallible
call. It may not be a generic struct's: `init` on a `Box[T]` is an error for
now. A struct without `init` is built from its fields as described above.

Public fields stay assignable, so `p.number = 0` is still possible after a
checked construction. To keep what `init` checks true for the value's whole
life, make the field [private](#private-fields).

## Private fields

A field whose name starts with `_` is private: only the struct's own
functions (`init`, its methods and its operator methods) can read or assign
it, or name it in the field constructor.

```kod
type Duration = struct {
    _ns: int64

    func init(seconds: int64 = 0, ms: int64 = 0) -> Duration {
        return Duration(_ns: seconds * 1 000 000 000 + ms * 1 000 000)
    }

    func as_ms(self) -> int64 {
        return self._ns / 1 000 000
    }
}

let d = Duration(seconds: 5)
print_int(d.as_ms())    // 5000
d._ns                   // error: field `_ns` is private to `Duration`
d._ns = 0               // error: field `_ns` is private to `Duration`
```

Only `Duration`'s own functions can set `_ns`, so whatever `init` checks
about it holds for as long as the value lives.
Callers depend only on the methods, so the representation can change
without breaking them: `Duration` could store microseconds instead and no
caller would notice.

Outside the struct, a private field can't be named in the field constructor
either. A private field with a [default](#field-defaults) is filled in from
it; a private field without one means the struct can only be built through
`init` or its own functions. Public and private fields mix freely.

Privacy covers the field, not what it points to. A method that returns a
private array returns the array itself, which the caller can then change by
indexing it; return a copy when that matters.

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

## Operators

A struct gives the arithmetic and comparison operators a meaning by declaring
methods with reserved names. The operator on the left operand's struct calls
the method with the right operand as its one argument:

| Operator | Method | Returns |
|---|---|---|
| `a + b` | `op_add(self, other)` | any type |
| `a - b` | `op_sub(self, other)` | any type |
| `a * b` | `op_mul(self, other)` | any type |
| `a / b` | `op_div(self, other)` | any type |
| `a % b` | `op_mod(self, other)` | any type |
| `a == b`, `a != b` | `op_eq(self, other)` | `bool` |
| `a < b`, `a > b`, `a <= b`, `a >= b` | `op_lt(self, other)` | `bool` |

```kod
type Money = struct {
    cents: int64

    func op_add(self, other: Money) -> Money {
        return Money(cents: self.cents + other.cents)
    }

    func op_mul(self, times: int64) -> Money {
        return Money(cents: self.cents * times)
    }

    func op_eq(self, other: Money) -> bool {
        return self.cents == other.cents
    }

    func op_lt(self, other: Money) -> bool {
        return self.cents < other.cents
    }
}

let total = Money(cents: 250) + Money(cents: 100) * 3     // 550
if total > Money(cents: 500) { ... }
```

`!=` is `not op_eq`. The four orderings come from `op_lt` alone: `a > b` is
`b < a`, `a <= b` is `not (b < a)` and `a >= b` is `not (a < b)`. `a += b` and
`a -= b` are `a = a + b` and `a = a - b`, and `a < b < c` chains as it does for
numbers. The operators keep their usual precedence, and the operands are
evaluated left to right whichever one the method belongs to.

A struct is the right operand when the left is an `int64`: `3 * price` calls
`op_rmul` on `price` with `3` as its argument. The reflected methods are
`op_radd`, `op_rsub`, `op_rmul`, `op_rdiv` and `op_rmod`; each is tried only
when the left operand isn't a struct, and there is no reflected comparison.

A method that implements an operator takes `self` and one more parameter, and
the comparison methods return `bool`; otherwise it is an error where the
operator is used. A struct that doesn't declare the method still can't use the
operator, so `a + b` on a plain struct is the same error as before, and
`a == b` still tells you to compare the fields. A prefix minus is `0 - x`,
so `-price` calls `op_rsub` with `0`. `not`, `and`, `or` and `is` are never
overloaded.

## Memory layout (compiler)

Struct fields are laid out sequentially, each taking 8 bytes, allocated on an arena:

```
[ offset 0  ] field_0 : 8 bytes
[ offset 8  ] field_1 : 8 bytes
...
```

Struct variables hold a pointer to the arena allocation.
