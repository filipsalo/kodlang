---
icon: lucide/package
---

# Modules

Each `.kod` file is a module. Modules are imported by path, relative to the project root.

## Importing

```kod
import "utils"          // imports utils.kod from the same directory
import "math/vec"       // imports math/vec.kod
import "kod/ast"        // imports from the stdlib
```

The imported module's public names are accessible via the import alias (the last path component by default):

```kod
import "math/vec"

let v: vec.Vec2 = vec.Vec2(x: 1, y: 2)
```

## Standard library

The stdlib lives under `stdlib/` in the repository. Key modules:

| Module | Contents |
|--------|----------|
| `builtins` | Always imported — `print`, `print_int`, `len`, `int_to_str`, etc. |
| `kod/ast` | AST node types (for the self-hosted compiler) |
| `kod/lexer` | Lexer (for the self-hosted compiler) |
| `kod/parser` | Parser (for the self-hosted compiler) |
| `kod/codegen` | ARM64 code generator written in Kod |

## Circular imports

Circular imports are not supported. The dependency graph must be a DAG.

## Visibility

All top-level declarations (functions, types, variables) are visible to importing modules. There is no explicit `pub`/`private` distinction yet.
