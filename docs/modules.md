---
icon: lucide/package
---

# Modules

Each `.kod` file is a module. Modules are imported by path, relative to the project root.

## Importing

Two forms:

```kod
import "./utils"        // relative — utils.kod next to the importing file
import "./math/vec"     // relative — math/vec.kod in a sibling directory
import "kod/ast"        // stdlib — stdlib/kod/ast.kod
import "io"             // stdlib — stdlib/io.kod
```

Paths beginning with `./` resolve relative to the importing file. Anything else resolves under `stdlib/`.

The imported module's public names are accessible via the import alias (the last path component by default):

```kod
import "./math/vec"

let v: vec.Vec2 = vec.Vec2(x: 1, y: 2)
```

## Standard library

The stdlib lives under `stdlib/` in the repository.

| Module | Contents |
|--------|----------|
| `builtins` | Always imported. `print`, `print_int`, `len`, `fail`, `Map[K, V]`, the `Error` / `Stringable` / `ExitCode` interfaces. |
| `primitives/int64`, `primitives/str`, `primitives/bool` | Methods on the primitive types (`to_str`, `hash`). Auto-loaded; not imported directly. |
| `io` | `read_file`. |
| `process` | `process.run(argv)` — spawn a subprocess and capture stdout/stderr/exit code. |
| `kod/ast` | AST node types (for the self-hosted compiler). |
| `kod/lexing` | Tokenizer (self-hosted). |
| `kod/parsing` | Parser (self-hosted). |
| `kod/codegen` | ARM64 code generator. |

## Circular imports

Circular imports are not supported. The dependency graph must be a DAG.

## Visibility

All top-level declarations (functions, types, variables) are visible to importing modules. There is no explicit `pub`/`private` distinction yet.
