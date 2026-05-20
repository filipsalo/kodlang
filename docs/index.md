---
icon: lucide/house
---

# Kod

Kod is a toy language that compiles to AArch64 (Apple Silicon) machine code for macOS. A Python frontend bootstraps the self-hosted compiler (`sh_kodc`), which compiles Kod programs — including itself.

```kod
func main() -> int64 {
    print("Hello, world!")
    return 0
}
```

```shell
$ uv run kod build hello.kod
$ ./build/apps/hello/hello
Hello, world!
```

## Features

- Compiled to native ARM64 machine code (via `as` + `ld`)
- Static types: `int64`, `str`, `bool`, arrays `[T]`, structs, enums, optionals `T?`, generics `T[U, V]`
- Pattern matching via `match`, plus `if X is .Variant(bindings)` sugar
- F-string interpolation (`f"hello {name}"`), auto-`to_str` for non-string interpolands
- Interfaces with vtable dispatch; primitives implement them via implicit boxing
- Error handling via `T or Error`, `try` / `must` / `throw`
- `test "description" { ... }` syntax with `assert <expr>` (source captured)
- Modules and imports (`import "kod/ast"`, `import "./helper"`)
- Self-hosted ARM64 codegen written in Kod itself

## Status

The self-hosted compiler (`sh_kodc`) is the production path. The Python frontend (`kod _interpret`, `kod _emit-asm`) remains for development and bootstrapping.
