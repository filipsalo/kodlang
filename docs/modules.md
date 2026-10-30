---
icon: lucide/package
---

# Modules

Each `.kod` file is a module. Imports name either a file relative to the importing module or a stdlib module.

## Importing

Two forms:

```kod
import "./utils"        // relative — utils.kod next to the importing file
import "./math/vec"     // relative — math/vec.kod below the importing file's directory
import "kod/ast"        // stdlib — stdlib/kod/ast.kod
import "io"             // stdlib — stdlib/io.kod
```

Paths beginning with `./` resolve against the directory of the importing file, not the project root or the current directory. Anything else resolves under `stdlib/`.

The imported module's public names are accessible via the import alias, which is the last path component:

```kod
import "./math/vec"

func origin() -> vec.Vec2 {
    return vec.Vec2(x: 0, y: 0)
}
```

Qualified constructors have the imported type, so `let v = vec.Vec2(x: 1, y: 2)`
needs no annotation before `v.x`. Calling a function the module doesn't
declare, such as `vec.lenght(v)`, is an error with a did-you-mean hint.
A local or parameter named like an import alias hides the module where
it is in force. After `let vec = Thing()`, `vec.len()` calls `Thing`'s
method until the block that declared it ends. Before that `let`, in its
own initializer (`let vec = vec.make(1)`) and after its block, `vec.` is
the module again, or an outer binding of that name. In a type or a type
argument, `vec.Vec2` always means the module, and so does the enum in a
pattern or an `is`, such as `vec.Shape.Circle`. In an expression, where
the local is in force, `vec.Vec2(...)` calls a method of the local and
`vec.Shape.Circle` reads a field of it, and `x is vec.Vec2` and a pattern
`vec.Vec2(b)` are errors: `` `vec` is a local here, so `vec.Vec2` doesn't
name a type of its module; give the local another name ``.
A function named like an import alias doesn't hide it: with `func vec()`
declared too, `vec()` calls the function and `vec.make(1)` the module's.

To also use some names unqualified, list them after the path. The qualified form keeps working:

```kod
import "./math/vec" { Vec2, dot }

func norm2(anon v: Vec2) -> int64 {
    return dot(v, v)        // same as vec.dot(v, v)
}
```

## Where names resolve

Parameter defaults, struct field defaults and the method bodies of a generic type resolve function names, type names and import aliases in the module that wrote them, even though they run as part of the caller's code. A default in `util.kod` that calls `helper()` calls util's own `helper`, a function util imports with `{ helper }`, or the builtin of that name, never one that belongs to the caller. Likewise `rng.seed()` in that default means util's own `import "./rng"`, whether or not the caller imports a module named `rng`:

```kod
// util.kod
func helper() -> int64 {
    return 1
}

func f(x: int64 = helper()) -> int64 {
    return x
}

// main.kod
import "./util"

func helper() -> int64 {
    return 2
}

func main() -> int64 {
    let helper = 3          // not visible to util's default either
    print(f"{util.f()}")    // 1
    return 0
}
```

The same holds for a function literal or a function value used as a default (`cb: func() -> int64 = helper`). A name the defining module doesn't have is an error, reported at the default when a call leaves the parameter out, even when the caller happens to declare it.

A bare type name `T` means, in this order: a type parameter of the generic declaration around it, a primitive (`int64`, `bool`, `str`, `bytes`, `none`), a type the module declares (its own aliases included), a type it lists in an import (`import "./pa" { Pt }`), then a builtin type. A type of a module imported without listing it, or loaded only because another module imports it, is written through the module: `pa.Pt`. Otherwise it's an error with a hint naming the file that declares it: `` unknown type `Pt`; lib/pa.kod declares `Pt`: write `pa.Pt` or list it in the import (`{ Pt }`) ``, or `` unknown type `Pt`; lib/pa.kod declares `Pt`: import it to use it here `` when the module doesn't import that file.

`m.T` means a type that the module imported as `m` declares, its own aliases included. This holds in a type, a constructor `m.T(...)`, a type argument, `m.E.V`, `is m.T` and a pattern `m.T(b)`, except where a local named `m` is in force (see above). Types that `m` only imports aren't reachable through it. Otherwise it's an error: `` module `m` has no type `T` ``, with a did-you-mean over m's types (`` module `m` has no function or type `T` `` for a call `m.T(...)`). When `m` isn't a module this one imports, the error spells what was written: `` unknown type `m.T` ``.

A module declares each of its names once. A function, extern, struct, enum, interface or type alias with the name of an earlier one in the same module is an error at the second declaration (`` `f` is already declared on line 1 ``), and so is a method, field or variant with the name of an earlier one of the same struct, interface or enum (`` `Kind.A` is already declared on line 2 ``). A method can't take the name of a field of its struct either; the error is at the method (`` `Bag.len` is already declared on line 3 ``).

A name an import lists counts the same way. A module can't both declare a name and list it in an import, and two imports can't list the same name, whether it names a type or a function. The later one is the error: `` `Pt` is already imported on line 1 ``, or `` `Pt` is already declared on line 3 `` when the declaration comes first. Two imports can't share a name either, unless they load the same file: after `import "./a/util"`, `import "./b/util"` is `` `util` is already imported on line 1 ``, while a second `import "./a/util" { Vec2 }` only adds to the first import's list.

Each module's structs, enums, interfaces and type aliases are its own. Two modules may declare a type of the same name, and they are different types: `pa.Pt` and `pb.Pt` don't convert to each other, `is pa.Pt` doesn't hold for a `pb.Pt`, and `Box[pa.Pt]` and `Box[pb.Pt]` are different instances. Aliases of different types may share a name across modules, and an alias may take its target's name (`type Pt = pb.Pt`), so a module that imports only this one reaches the type as its `Pt`. Only the builtins may declare `Map`, `Option`, `Result`, `Error`, `Stringable` or `ExitCode`; anywhere else it's an error: `` `Option` is the name of a builtin type; give this type another name ``. A module is one module however its path is spelled: `import "./lib/../lib/pa"` and `import "./lib/pa"` load the same file once.

A message writes a type by its bare name, unless another module of the program declares a struct, enum or interface of that name too (an alias doesn't count, as a message writes the type it stands for). Then it's written the way the module being compiled would write it (`pa.Pt`, or `Pt` when the module has it under that name: declared, aliased or listed in an import), or with its file when that module can't name it (`Pt (lib/pb.kod)`).

## Standard library

The stdlib lives under `stdlib/` in the repository.

| Module | Contents |
|--------|----------|
| `builtins` | Always imported. `print`, `print_int`, `len`, `fail`, `Map[K, V]`, `Option[T]`, the `Error` / `Stringable` / `ExitCode` interfaces. |
| `primitives/int64`, `primitives/str`, `primitives/bool` | Methods on the primitive types (`to_str`, `hash`). Auto-loaded; not imported directly. |
| `io` | `read_file`, `write_file`, and stdin/stdout/stderr helpers. |
| `fs` | `FileSystem` interface with `DiskFs` (real disk) and `MemFs` (in-memory, for tests). |
| `process` | `process.run(argv)` — spawn a subprocess and capture stdout/stderr/exit code. |
| `time` | `monotonic_ns()` and `unix_ns()`. |
| `set` | `Set[T]`, a hash set built on `Map`. |
| `sort` | `sorted_int64`, `sorted_str` (insertion sort; returns a new array). |
| `json` | Minimal JSON parse/emit, int64 numbers only. See [JSON](json.md). |
| `jsonrpc` | Content-Length framed messages on stdin/stdout, as used by LSP. |
| `hash/crc32` | CRC-32 (gzip polynomial), streaming or one-shot. |
| `compress/deflate`, `compress/gzip` | Deflate encoder (fixed Huffman, optional LZ77) and a gzip writer. |
| `kod/ast` | AST node types (for the self-hosted compiler). |
| `kod/lexing` | Tokenizer (self-hosted). |
| `kod/parsing` | Parser (self-hosted). |
| `kod/codegen` | ARM64 code generator. |

## Circular imports

Keep the dependency graph a DAG: the interpreter can't load circular
imports. The compiler accepts them, and a struct, enum or interface
declared in a module of the cycle is the same type on either side, so a
value of it can be passed both ways, also inside an array, an optional, a
`Map` or another generic type's instance such as `Box[Pt]`, and `is`
recovers a struct from an interface value whichever side boxed it.

## Visibility

Top-level functions and types are visible to importing modules. There is no explicit `pub`/`private` distinction yet.

A module's top level holds only declarations (`func`, `type`, `interface`, `import`, `extern` and `test`). Top-level `let` and `mut` bindings aren't supported, and they and any other statement there are an error. For a module-wide constant, use a function with no arguments:

```kod
func max_block() -> int64 {
    return 65535
}
```
