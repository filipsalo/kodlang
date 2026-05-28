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

## Construction

Pass fields by name using labeled arguments:

```kod
let p: Point = Point(x: 10, y: 20)
```

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
ordinary expressions evaluated in the struct's defining module.

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
```

The built-in `Map[K, V]` is the canonical example.

## Memory layout (compiler)

Struct fields are laid out sequentially, each taking 8 bytes, allocated on an arena:

```
[ offset 0  ] field_0 : 8 bytes
[ offset 8  ] field_1 : 8 bytes
...
```

Struct variables hold a pointer to the arena allocation.
