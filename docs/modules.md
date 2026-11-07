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
No local can be named like an import alias: a `let`, `mut`, parameter,
`for` variable or pattern binding named `vec` is an error,
`` `vec` is the name of an import; give the local another name ``, so
`vec.` always means the module.
A function named like an import alias doesn't hide it: with `func vec()`
declared too, `vec()` calls the function and `vec.make(1)` the module's.

To use some names unqualified instead, list them after the path:

```kod
import "./math/vec" { Vec2, dot }

func norm2(anon v: Vec2) -> int64 {
    return dot(v, v)
}
```

An import that lists names binds only those names, not its alias, so
`vec.dot` is an error there (`` unknown name `vec`; an import that lists
names binds no `vec`, so add a plain import of it to write `vec.` ``) and a
local may be named `vec`. That keeps the
usual way of naming a value after its module working:

```kod
import "net/http" { Client }

let client = Client()      // `client` is a local, and `http` names nothing
```

To have both, import the module twice: `import "./math/vec"` binds `vec`
and `import "./math/vec" { Vec2 }` adds `Vec2`, and then no local can be
named `vec`.

Each listed name must be a function, extern, constant or type the module declares; otherwise it's an error with a did-you-mean hint: `` module `vec` has no function, constant or type `dto`; did you mean `dot`? ``.

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

A bare type name `T` means, in this order: a type parameter of the generic declaration around it, a primitive (`int64`, `bool`, `str`, `bytes`, `none`), a type the module declares (its own aliases included), a type it lists in an import (`import "./pa" { Pt }`), then a builtin type. A type of a module imported without listing it, or loaded only because another module imports it, is written through the module: `pa.Pt`. Otherwise it's an error with a hint naming the file that declares it: `` unknown type `Pt`; lib/pa.kod declares `Pt`: write `pa.Pt` or list it in the import (`{ Pt }`) ``, or `` unknown type `Pt`; lib/pa.kod declares `Pt`: import it to use it here `` when the module doesn't import that file. `kod` finds the file anywhere in the program being built, so the hint also names a module that imports this one or that only another module imports. `sh_kodc` run on one file knows only that file's imports.

`m.T` means a type that the module imported as `m` declares, its own aliases included. This holds in a type, a constructor `m.T(...)`, a type argument, `m.E.V` and a pattern `b: m.T`. Types that `m` only imports aren't reachable through it. Otherwise it's an error: `` module `m` has no type `T` ``, with a did-you-mean over m's types (`` module `m` has no function or type `T` `` for a call `m.T(...)`). When `m` isn't a module this one imports, the error spells what was written: `` unknown type `m.T` ``. A generic type takes its arguments the same way, as in `m.Box[m.Pt](v: p)`, also where it is itself a type argument: `Stack[m.Box[str]]`.

A module exports only what it declares, never what it imports. When `m` lists `T` in one of its own imports, `m.T`, `m.f()`, `m.f` and `import "./m" { T }` say where `T` comes from: `` `T` is imported by `m`, not declared there; import it from lib/b.kod ``. A value of such a type can still be used without naming it, as in `let t = m.make()`. To pass a type on deliberately, `m` declares an alias of it, `type T = b.T` (which needs a plain `import "./b"`), and for a function a wrapper.

A module declares each of its names once. A function, extern, struct, enum, interface or type alias with the name of an earlier one in the same module is an error at the second declaration (`` `f` is already declared on line 1 ``), and so is a method, field or variant with the name of an earlier one of the same struct, interface or enum (`` `Kind.A` is already declared on line 2 ``). A method can't take the name of a field of its struct either; the error is at the method (`` `Bag.len` is already declared on line 3 ``).

A name an import lists counts the same way. A module can't both declare a name and list it in an import, and two imports can't list the same name, whether it names a type or a function. The later one is the error: `` `Pt` is already imported on line 1 ``, or `` `Pt` is already declared on line 3 `` when the declaration comes first. Two imports can't share a name either, unless they load the same file: after `import "./a/util"`, `import "./b/util"` is `` `util` is already imported on line 1 ``, while a second `import "./a/util" { Vec2 }` only adds to the first import's list.

Each module's structs, enums, interfaces and type aliases are its own. Two modules may declare a type of the same name, and they are different types: `pa.Pt` and `pb.Pt` don't convert to each other, `is _: pa.Pt` doesn't hold for a `pb.Pt`, and `Box[pa.Pt]` and `Box[pb.Pt]` are different instances. Aliases of different types may share a name across modules, and an alias may take its target's name (`type Pt = pb.Pt`), so a module that imports only this one reaches the type as its `Pt`. Only the builtins may declare `Map`, `Option`, `Result`, `Error`, `Stringable` or `ExitCode`; anywhere else it's an error: `` `Option` is the name of a builtin type; give this type another name ``. A module is one module however its path is spelled: `import "./lib/../lib/pa"` and `import "./lib/pa"` load the same file once.

A message writes a type by its bare name, unless another module of the program declares a struct, enum or interface of that name too (an alias doesn't count, as a message writes the type it stands for). Then it's written the way the module being compiled would write it (`pa.Pt`, or `Pt` when the module has it under that name: declared, aliased or listed in an import), or with its file when that module can't name it (`Pt (lib/pb.kod)`).

## Standard library

The stdlib lives under `stdlib/` in the repository.

| Module | Contents |
|--------|----------|
| `builtins` | Always imported. `print`, `print_int`, `len`, `fail`, `Map[K, V]`, the `Error` / `Stringable` / `ExitCode` interfaces. |
| `primitives/int64`, `primitives/float64`, `primitives/str`, `primitives/bool` (and `int64_float`, `str_float`, which hold `to_float64` and `parse_float`) | Methods on the primitive types (`to_str`, `hash`, `parse_float`). Auto-loaded; not imported directly. |
| `io` | `read_file`, `write_file`, and stdin/stdout/stderr helpers. |
| `fs` | `FileSystem` interface with `DiskFs` (real disk) and `MemFs` (in-memory, for tests). |
| `process` | `process.run(argv)` — spawn a subprocess and capture stdout/stderr/exit code. `process.exec(argv)` — replace the calling process (compiled programs only). |
| `env` | `get`, `set` and `unset` for environment variables. See [Built-ins](builtins.md#environment-variables). |
| `time` | `monotonic_ns()`, `unix_ns()`, `Duration`, `sleep(d)`, and `Time` with `now()`, `parse(s)` and `parse_date(s)`. See [Time](time.md). |
| `sets` | `Set[T]`, a hash set built on `Map`: `Set[str]()`. |
| `sort` | `sorted(xs)` and `sorted_by(xs, less:)`, stable, returning a new array. See [Arrays](arrays.md#sorting). |
| `arrays` | `contains(xs, x)` and `equal(a, b)`. See [Arrays](arrays.md#helpers). |
| `json` | Strict JSON parse/emit, with builders. See [JSON](json.md). |
| `strbuilder`, `stream`, `posix` | `StrBuilder`; `Reader` / `Writer` and `IoError`; file descriptors. See [Strings](strings.md) and [Streams](io.md). |
| `net/tcp`, `net/tls`, `net/http` | TCP, TLS, and HTTP/1.1 messages with a client. See [Streams](io.md) and [HTTP client](http.md). |
| `jsonrpc` | Content-Length framed messages on stdin/stdout, as used by LSP. |
| `encoding/base64` | Base64, standard and URL-safe, strict decoding. See [Encodings](encoding.md). |
| `hash/crc32` | CRC-32 (gzip polynomial), streaming or one-shot. |
| `compress/deflate`, `compress/gzip` | Deflate encoder (fixed Huffman, optional LZ77) and a gzip writer. |
| `kod/ast` | AST node types (for the self-hosted compiler). |
| `kod/lexing` | Tokenizer (self-hosted). |
| `kod/parsing` | Parser (self-hosted). |
| `kod/codegen` | ARM64 code generator. |

## Circular imports

Circular imports work: a struct, enum or interface
declared in a module of the cycle is the same type on either side, so a
value of it can be passed both ways, also inside an array, an optional, a
`Map` or another generic type's instance such as `Box[Pt]`, and `is`
recovers a struct from an interface value whichever side boxed it.

## Visibility

Top-level functions, externs, constants and types are visible to importing modules, except those whose name starts with `_`. Those are private to the module that declares them, which uses them like any other name:

```kod
// lib.kod
let _LIMIT: int64 = 3

type _Slot = struct {
    n: int64
}

func _clamp(anon n: int64) -> int64 {
    if n > _LIMIT {
        return _LIMIT
    }
    return n
}

func slots(anon n: int64) -> int64 {
    return _Slot(n: _clamp(n)).n
}

// main.kod
import "./lib"

func main() -> int64 {
    print_int(lib.slots(5))     // 3
    lib._clamp(5)               // error: `_clamp` is private to module `lib`
    return 0
}
```

The same error is reported for `lib._LIMIT`, `lib._Slot(...)`, `lib._Slot` in a type, and `_clamp` in an import list (`import "./lib" { _clamp }`). Did-you-mean hints never suggest another module's private names.

A private name keeps a helper out of the module's interface, so the module can change or remove it without breaking its importers. A public function may still take or return a private type: callers can use such a value, its fields and its methods, but can't write the type's name. Fields and methods whose names start with `_` are private to their struct; see [Structs](structs.md#private-fields).

A module's top level holds declarations (`func`, `type`, `interface`, `import`, `extern` and `test`) and constants (`let NAME: T = value`, see [Module-level constants](types.md#module-level-constants)). A top-level `mut` and any statement there are an error. A constant is visible to importing modules like a function.

## Symbol and object names

A module is identified by its normalized path: `./x` and `./a/../x` are one module, while `x` (the file under `stdlib/`) and `./x` (the project's own) are two. Everything a module emits (functions, types, tests) is labelled `$<prefix>$<name>`. The prefix is computed from the path and from whether `stdlib/<path>.kod` exists (step 5):

1. Drop the `.kod` extension, and the leading `/` of an absolute path.
2. A path under `stdlib/` drops that directory: `stdlib/io.kod` is `io`, `stdlib/kod/ast.kod` is `kod$ast`.
3. Each remaining byte becomes symbol characters. `/` becomes `$`. Letters, digits and `_` stay. `.` stays, except as the first byte. Every other byte (space, `-`, `+`, `@`, `$`, each byte of a non-ASCII character) becomes `$$` followed by its two lowercase hex digits: `my-app` is `my$$2dapp`.
4. The label is `$<prefix>$<name>`, and the assembler reads `$` followed by a digit as a number, and takes no `$$name` at all, so a prefix is never empty and never starts with `$` or a digit. If it would, a `.` is put in front: `-x` is `.$$2dx`, `01_hello` is `.01_hello`, `2024/report` is `.2024$report`, and a file named `.kod` is `.`. (A digit after an inner `$` is fine: `tests/3d` is `tests$3d`.) The assembler also reads `.` and digits followed by `e` or `E` as a number (`.1e5`), so then that letter is written `$$65` or `$$45` as well: `1e5` is `.1$$655`, `2East/lib` is `.2$$45ast$lib`.
5. A module outside `stdlib/` whose path also exists under `stdlib/` is in the namespace `.user$`: a project's `io.kod` is `.user$io` and does not clash with the stdlib `io`. The check is a file test, so on a case-insensitive volume a project's `Io.kod` also gets the marker; that is harmless, because every project module is recompiled for each program.

Two different normalized paths never get the same prefix: a prefix's own leading `.` is always escaped by step 3, so a raw leading `.` comes only from step 4, the marker `.user$` starts `.u`, which step 4 never produces, and `$$65` and `$$45` are escapes that step 3 never writes (it keeps letters). (An absolute path and the relative path with the same components still collide, as before.)

A vtable and a type's identity word are shared between objects by label, so their labels have to differ for different types as well: the parts of those labels are joined with `$$for$`, `$$of$` and the like, which step 3 never writes (a `$$` it writes has two hex digits after it). `is` and interface calls therefore can't mix up two types, whatever their paths are called.

`kod build` writes a program's objects under `build/apps/<stem>/<stem>.obj/`, mirroring the source tree: `stdlib/json.kod` becomes `<stem>.obj/stdlib/json.kod.o`, a project's `lib/json.kod` becomes `<stem>.obj/lib/json.kod.o`; the assembly `.s` sits beside each `.o`. A `..` directory is written `%2e%2e` (a `.` one `%2e`), the root of an absolute path `%2f`, and a literal `%` in a name `%25`. The `_main` shim is `<stem>.obj/<entry>.main.{s,o}` (`<stem>.obj/<first entry>.testmain.{s,o}` for tests). The executable is `build/apps/<stem>/<stem>`, or `<stem>_test` for `kod test`; `<stem>.obj` can equal neither. `<stem>` is the entry's file name without `.kod`; for `kod test <dir>` it is the directory with every byte outside letters, digits, `_` and `-` replaced by `_` (its last 200 bytes, when it is longer), then `_tests`. A file whose name without `.kod` is empty, `.` or `..` (`.kod`, `..kod`, `...kod`) has no program name and is refused. An entry named `kod` or `lsp` (other than `tools/kod.kod` and `tools/lsp.kod`, however they are spelled) is refused, because its executable would replace the tool. So is one whose directory the volume takes for the tool's, such as `KOD` on a case-insensitive volume.

The object path has to fit the file system as well: a file name of more than about 240 bytes (the shim adds `.kod.main.s`), or an absolute entry path of more than about 950 bytes (`build/apps/<stem>/<stem>.obj/%2f/` goes in front of it), is too long, and the build stops with a message that a file could not be opened or a directory made.

`kod test <dir>` builds every `*_test.kod` below `<dir>` into one program, except a file with a path component below `<dir>` that starts with `.` (worktrees under `.claude/`, editor files, the scratch `.kod_compile_test.kod`) and a `build` directory directly below `<dir>`. `kod test <file>` takes the file named, whatever its path.

## Link inputs

A module that needs C code or a system library says so in the comment lines at the top of its file, before its first declaration:

```
// kod:require ${OPENSSL}/include/openssl/ssl.h  brew install openssl@3
// kod:cc tls.c -I${OPENSSL}/include
// kod:link -L${OPENSSL}/lib -lssl -lcrypto

import "io"
```

- `kod:cc <file.c> [flags...]`: a C file beside the module. `kod build` compiles it with `CC` and `CFLAGS` of `link.cfg` followed by the flags given, and links the object. Flags are passed as written; a relative `-I` is relative to the repository root, where `kod` runs. The file is compiled on every build, like the modules, so an edit to it, to a header it includes or to `CC` and `CFLAGS` is picked up by the next one. A C file that several modules of a program name (or several test files of one `kod test <dir>`) is compiled and linked once; naming it with different flags is an error.
- `kod:link <args...>`: arguments for the final link, after all objects: `-lz`, `-L...`, `-framework Security`, a path to a `.a`. They are passed in the order the modules appear in the program, and a `-lname` that comes up again is passed once.
- `kod:require <file> [hint...]`: the file (a path from the repository root, or an absolute one) must exist before anything is compiled; otherwise the build stops with `path:line:1: error: needs <file> (<hint>)` (`needs <file>` when there is no hint), for each such file, naming the line of the directive. Use it for a file outside the repository that the other lines rely on, so that a machine without it gets the hint instead of `'openssl/err.h' file not found`.

`${NAME}` in a word is replaced by the value of `NAME` in `link.cfg`, or in `link.local.cfg` when that overrides it (the example assumes `link.cfg` has an `OPENSSL` line). A name that neither file sets, or one whose value is not exactly one word, is an error, and so is a `$` that does not start `${NAME}`. Words are separated by spaces; there is no quoting, and a tab or another control character in a directive line is an error.

Only the leading block counts: the lines from the top of the file that are blank or start with `//`, up to the first other line. In it a line that starts with `// kod:` (after any indent) is a directive, and any other comment line is just a comment; a `// kod:` line further down is a comment too and does nothing. A line in the block that is spelled like a directive but not so (`//kod:cc x.c`, `//  kod:cc x.c`, `// Kod:cc x.c`, `// kod :cc x.c`) is an error, so that a slip is not taken for a comment. A UTF-8 byte order mark at the start of the file is skipped, as the compiler skips it. Put a blank line after the block, or the first declaration takes it as its doc comment (shown on hover).

These are errors, `path:line:1: error: ...`, from `kod build`, `kod run`, `kod test` and `kod check`: an unknown directive (`unknown directive kod:linkk`), a directive spelled almost right, a tab in a directive line, a directive without its argument, a `kod:cc` that does not name a `.c` file beside the module (a bare file name ending in `.c`, which has to exist), and a `${NAME}` that cannot be replaced. `kod check` validates the lines, and that the C file is there, but it does not test `kod:require` and compiles no C.

Only a program that imports the module compiles its C file or passes its arguments, and that includes a module that only a test file imports: `kod test` reads the lines of every module of its program, and `kod test <dir>` builds all its files into one program, so one test file's missing `kod:require` file stops them all. A program that imports no such module compiles no C file. A C file's object is `<stem>.obj/<path>.c.o` in the tree of [Symbol and object names](#symbol-and-object-names), next to the module's own `<path>.kod.o`. If the C compiler fails, `kod` shows its output and `kod: compiling <file> failed`, exits 1 and links nothing.

A module that declares link inputs cannot be one that the Makefile builds: it does not read their lines. That is a module listed in `STAGE0_KOD` of `link.cfg`, one of the compiler's own modules (`COMPILER_KOD` in the Makefile) and `kodc.kod` and `tools/kod.kod`. For a `STAGE0_KOD` module the driver says so (`path:line:1: error: ...`) and stops, rather than leave the lines unread; for the others a test of the repository checks that there are none.

C files export bare symbols into one namespace shared with libc and `runtime.c`: name them `kod_<module>_...`. `#include "kod_rt.h"` (`CFLAGS` has `-I stdlib`) declares what they need of the runtime:

- `KodStr`: what a Kod `str` is when it crosses into C. `buf` points at `len` bytes followed by a NUL byte, and a `str` parameter or result is a `KodStr *`.
- `KodArray`: a Kod `[T]`: `ptr` points at `len` 8-byte slots, with room for `cap`.
- `arena_alloc(size)`: memory that is never freed.
- `rc_alloc(size, mask)`: a counted object, zeroed, with a count of 1 that the caller owns. `mask` says which of its 8-byte slots hold references, bit 0 for the first; it must not use bits past 20. `rc_alloc_raw` is the same but leaves filling it to the caller. `rc_retain_c(p)` and `rc_release_c(p)` count a reference up and down, and do nothing for memory outside the counted heap.
- `kod_str_new(len)`: a new `str` of `len` bytes for the caller to fill in. `kod_str_from_bytes(p, n)`: a `str` that is a copy of `n` bytes at `p`, which may contain NUL bytes.
- `kod_panic(msg)`: print `panic: ` and the message with a backtrace, and exit 1.

A function value isn't a C function pointer, so an `extern` can't take or return one: `` an `extern` can't take or return a function value ``.

Kod values are [reference counted](memory-layout.md#reclaiming-memory), and C code follows the same rules as generated code. A parameter is borrowed: it stays alive during the call, and C code that keeps it after returning calls `rc_retain_c`. A result is owned by the caller, which releases it, so returning anything other than a new object, such as a parameter or something kept in a static, takes an `rc_retain_c` first. The same goes for references written into an object: each one needs its own count.
