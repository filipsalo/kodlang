---
icon: lucide/box
---

# Structs

Structs are named product types — a fixed set of named fields. They come in
two kinds:

- A `struct` is a value, like an `int64` or an array: assigning it, passing
  it or storing it gives the other place the struct as it is, and changing a
  field later changes only the struct where it was changed (see
  [Field mutation](#field-mutation)).
- A `shared struct` is one object that everything holding it shares: a
  field assigned through any of them shows through all of them. It is for
  things with state of their own, such as a parser, a log or a node in a
  graph.

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

A shared struct is declared the same way, with `shared` before `struct`:

```kod
type Parser = shared struct {
    pos: int64
}
```

`shared` is a word only before `struct`; it can still name a variable or a
field.

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
call. A struct without `init` is built from its fields as described above.

A [generic struct](#generic-structs) may declare `init` too. It returns the
struct with its own type parameters, `Range[T]` or `Range[T] or Error`, and is
called with the type arguments spelled out as for any construction of one:

```kod
type Range[T] = struct {
    lo: T
    hi: T

    func init(lo: T, hi: T) -> Range[T] or Error {
        if hi < lo {
            throw Backwards()
        }
        return Range[T](:lo, :hi)
    }
}

let r = try Range[int64](lo: 2, hi: 9)
```

Inside its own functions, any instance of the struct is built from its
fields, so a method of `Pair[A, B]` can make a `Pair[B, A]` directly.

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

## Private methods

A method whose name starts with `_` is private in the same way: only the
struct's own functions can call it, as `self._name(...)` or on another value
of the struct.

```kod
type Duration = struct {
    _ns: int64

    func _whole(self, unit: int64) -> int64 {
        return self._ns / unit
    }

    func as_ms(self) -> int64 {
        return self._whole(unit: 1 000 000)
    }
}

d.as_ms()               // fine
d._whole(unit: 1)       // error: method `_whole` is private to `Duration`
```

That keeps helpers that assume the struct's invariants, or that would break
them, out of the struct's interface. A method of a primitive type such as
`str` or `int64` is private to the module that declares it.

An interface can't declare a private method: calling it through the
interface would reach the struct's method from outside.

## Weak fields

A field declared `weak` refers to a struct without keeping it alive, for a
reference back up a tree or across a graph, which would otherwise make a
[cycle](memory-layout.md#reclaiming-memory) that is never freed:

```kod
type Node = shared struct {
    name: str
    children: [Node] = []
    weak parent: Node?           // starts as none
}

let root = Node(name: "root")
let leaf = Node(name: "leaf", parent: root)
root.children += [leaf]

if leaf.parent is Node(p) {
    print(p.name)                // root
}
```

- Only a shared struct has weak fields, and a weak field's type is an
  optional shared struct, `S?`: a value has no identity to refer back to.
  It starts as `none`
  unless it has a default or the construction gives it a value.
- Assigning to it, or giving it a value in a construction, doesn't count as
  a reference: when nothing else refers to the struct, it is freed, and from
  then on the field reads as `none`.
- Reading it gives a `S?` of its own, which keeps the struct alive for as
  long as it is used, as any other value does: `p` above can't be freed out
  from under the code that reads it.
- Each read checks whether the struct is still there and makes a new
  optional, so a weak field costs a little more to read than a plain one.

`weak` is only special before a field's name; elsewhere it is an ordinary
name.

## Field access

```kod
print_int(p.x)
print_int(p.y)
```

## Field mutation

```kod
p.x = p.x + 1
```

A field of a struct is assigned only through a name that could be assigned:
a `mut` binding or a `mut` parameter, or a field or element of something
that may itself be changed. On a `let` struct, a parameter not declared
`mut` or a `for` variable, `p.x = 1` is an error
(`` cannot change `p`, an immutable binding; declare it with `mut` ``), and
so is changing an array in one of its fields. Each place has a struct of its
own, so a change shows only there:

```kod
mut a = Point(x: 1, y: 2)
let b = a
a.x = 10                     // a.x is 10, b.x is still 1

mut line = Line(from: a, to: b)
line.from.y = 5              // line.from.y is 5, a.y is still 2
```

As with arrays, nothing is copied until it has to be: assigning or passing a
struct shares it, and its fields are copied the first time one holder
changes it while another still has it.

A shared struct's fields are assigned through any name that holds it, `mut`
or not, and every holder sees the change.

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

    func translate(mut self, dx: int64, dy: int64) -> none {
        self.x = self.x + dx
        self.y = self.y + dy
    }
}
```

Call methods with dot notation:

```kod
mut p: Point = Point(x: 3, y: 4)
print_int(p.distance_sq())   // 25
p.translate(dx: 1, dy: 0)
print_int(p.x)               // 4
```

A method that changes its struct declares `mut self`, like a
[`mut` parameter](functions.md#mut-parameters): the receiver is the
caller's struct, which must be one the caller could change (`p` is `mut`
above), and has the method's changes when it returns. The call needs no
`mut`. Other methods can't assign to `self`'s fields
(`` cannot change `self`; declare the method with `mut self` ``). A
`mut self` method isn't one an interface can call, so it doesn't make the
struct satisfy an interface. A shared struct's methods change it through
any `self`, and can't declare `mut self`.

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

A method of an instance is compiled for its type arguments when something
uses it: a call, an operator or other syntax that calls it, or the instance
becoming a value of an interface, which uses all of that interface's methods.
So a `Box[T]` whose `contains` uses `==` can hold a struct that has no `==`, as
long as nothing calls `contains` on that `Box`. Only a method's signature is
checked otherwise, so a mistake in the body of a method nothing uses isn't
reported, as with a generic function nothing calls. An error in a body names the
instance, as in
`` `<` doesn't take `Color` operands; declare `op_lt` on `Color` to use it (in `Box[Color]`) ``, and a line of
the template is reported for one instance only.

A generic struct or enum may name itself, with any type arguments, in its
fields, payloads and method signatures, as in `kids: [Tree[T]]` or the
`Pair[B, A]` above. The instances have to end, though: one that keeps naming a
bigger type, like `next: W[[T]]?` in `W[T]` or a called method of `W[T]` that
makes a `W[[T]]`, is an error once it is 64 instances deep
(`` generic type `W` is 64 instances deep; each one names another with a new type ``).
Methods that branch into new types are stopped earlier, when a module passes 4096
instances.

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

When the left operand has no method for the operator, the right operand's
reflected method is called instead, with the left operand as its argument:
`3 * price` calls `op_rmul` on `price` with `3`. The left operand can be of
any type, such as an `int64`, a `float64` or a struct without `op_mul`:

```kod
type Vec = struct {
    x: float64
    y: float64

    func op_rmul(self, k: float64) -> Vec {
        return Vec(x: self.x * k, y: self.y * k)
    }
}

let v = 2.0 * Vec(x: 1.0, y: 2.0)     // Vec(x: 2.0, y: 4.0)
```

The reflected methods are `op_radd`, `op_rsub`, `op_rmul`, `op_rdiv` and
`op_rmod`. The left operand's own method, when it has one, always wins, even
if it doesn't take the right operand's type; and there is no reflected
comparison.

A method that implements an operator takes `self` and one more parameter, and
the comparison methods return `bool`; otherwise it is an error where the
operator is used. A struct that doesn't declare the method still can't use the
operator, so `a + b` on a plain struct is the same error as before, and
`a == b` still tells you to compare the fields. A prefix minus is `0 - x`,
so `-price` calls `op_rsub` with `0`. `not`, `and`, `or` and `is` are never
overloaded.

## Memory layout (compiler)

Struct fields are laid out sequentially, each taking 8 bytes, allocated on the [heap](memory-layout.md#the-heap):

```
[ offset 0  ] field_0 : 8 bytes
[ offset 8  ] field_1 : 8 bytes
...
```

Struct variables hold a pointer to the allocation. The allocation is
counted like any other object; before a struct (not a shared one) is
changed, generated code checks that the count is 1, and otherwise
`_kod_obj_unique` copies it, retaining what its fields refer to, stores the
copy where the struct was, and lets go of the original.
