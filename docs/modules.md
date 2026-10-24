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

To also use some names unqualified, list them after the path. The qualified form keeps working:

```kod
import "./math/vec" { Vec2, dot }

func norm2(anon v: Vec2) -> int64 {
    return dot(v, v)        // same as vec.dot(v, v)
}
```

## Where names resolve

Parameter defaults, struct field defaults and the method bodies of a generic type resolve function names and import aliases in the module that wrote them, even though they run as part of the caller's code. A default in `util.kod` that calls `helper()` calls util's own `helper`, a function util imports with `{ helper }`, or the builtin of that name, never one that belongs to the caller. Likewise `rng.seed()` in that default means util's own `import "./rng"`, whether or not the caller imports a module named `rng`:

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
value of it can be passed both ways, also inside an array, an optional or
a `Map`.

## Visibility

Top-level functions and types are visible to importing modules. There is no explicit `pub`/`private` distinction yet.

Top-level `let` and `mut` bindings are not supported by the compiler. They are skipped when parsing, so any later reference to the name fails with `unknown name`, both inside the module and from an importer. For a module-wide constant, use a function with no arguments:

```kod
func max_block() -> int64 {
    return 65535
}
```
