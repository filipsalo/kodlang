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

First build the toolchain with `make kod`; after that `./kod` (a link at the
repository root to the native tool) rebuilds it whenever its sources change.

```shell
# ./kod build hello.kod
# ./build/apps/hello/hello
Hello, world!
```

### Running tests

```shell
# ./kod test stdlib        # all tests under stdlib/
# ./kod test .             # everything under the project
```

See `docs/` for the full language reference.
