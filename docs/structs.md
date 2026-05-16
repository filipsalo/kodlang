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
p.translate(1, 0)
print_int(p.x)               // 4
```

## Memory layout (compiler)

Struct fields are laid out sequentially, each taking 8 bytes, allocated on an arena:

```
[ offset 0  ] field_0 : 8 bytes
[ offset 8  ] field_1 : 8 bytes
...
```

Struct variables hold a pointer to the arena allocation.
