---
icon: lucide/house
---

# Kod

Kod is a toy language that compiles to AArch64 (Apple Silicon) machine code for macOS. It has a Python interpreter for fast iteration and a self-hosted compiler as its end goal.

```kod
func main() -> int64 {
    print("Hello, world!")
    return 0
}
```

```shell
$ python -m kod build hello.kod
$ ./build/hello
Hello, world!
```

## Features

- Compiled to native ARM64 machine code via assembly
- Python interpreter for development and bootstrapping
- Static types: `int64`, `str`, `bool`, arrays, structs, enums, optionals
- Pattern matching with `match`
- F-string interpolation (`f"hello {name}"`)
- Modules and imports
- Self-hosted ARM64 codegen written in Kod itself

## Status

Kod is a work-in-progress toy language. The primary goal is **self-hosting** — compiling the Kod compiler with itself. The Python implementation serves as the bootstrap compiler.
