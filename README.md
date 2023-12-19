# Kod `>≤((º>`

Kod is a toy language that compiles to x86 machine code for macOS.

## Example

```go
// hello.kod
func main() -> int32 {
    // This is a comment
    print("Hello, world!")
}
```

### Compiling

```shell
# python -m kod build hello.kod
# ./build/hello
Hello, world!
```

### Output the AST

```shell
# python -m kod parse hello.kod
```
