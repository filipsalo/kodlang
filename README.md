# Kod `>≤((º>`

Kod is a toy language that compiles to AArch64 machine code for macOS.

## Example

```kod
// hello.kod
func main() -> int64 {
    // This is a comment
    print("Hello, world!")
    return 0
}
```

### Compiling

```shell
# uv run kod build hello.kod
# ./build/apps/hello/hello
Hello, world!
```

### Running tests

```shell
# uv run kod test stdlib    # all tests under stdlib/
# uv run kod test .         # everything under the project
```

See `docs/` for the full language reference.
