---
icon: lucide/terminal
---

# CLI reference

Invoke Kod via `python -m kod <command> <file>`.

## Commands

### `interpret`

Run a program through the Python interpreter. No compilation step — fast for development.

```shell
python -m kod interpret hello.kod
```

### `run`

Alias for `interpret`.

### `build`

Compile a program to a native ARM64 binary. Output goes to `build/<name>`.

```shell
python -m kod build hello.kod
./build/hello
```

The build process:

1. Parse all modules
2. Compile each module to ARM64 assembly (`.s` files in `build/`)
3. Assemble with `as`
4. Link with `ld` against the runtime (`arena.c`, `runtime.c`)

### `compile`

Emit assembly for a single module to stdout without assembling:

```shell
python -m kod compile hello.kod
```

Useful for inspecting the generated ARM64 assembly.

### `parse`

Parse a file and dump the AST to stdout:

```shell
python -m kod parse hello.kod
```

## Options

| Flag | Description |
|------|-------------|
| `--no-type-check` | Skip type checking (interpreter mode only) |

## Output files

`build/` is created in the project root and contains:

| File | Description |
|------|-------------|
| `build/<name>` | Final executable |
| `build/<module>.s` | Assembly source for each module |
| `build/<module>.o` | Object file for each module |
| `build/runtime_main.s` | Generated `_main` trampoline |
| `build/arena.o` | Compiled arena allocator |
| `build/runtime.o` | Compiled string/array runtime |
