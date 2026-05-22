# tree-sitter-kod

Tree-sitter grammar for the Kod language. Editor-grade parsing — good enough
for syntax highlighting, code folding, and structural navigation. The Kod
self-hosted parser remains the source of truth for everything semantic.

## Build & test

```sh
tree-sitter generate
tree-sitter test
tree-sitter parse path/to/file.kod
```

## Editor integration

The `tree-sitter` block in `package.json` points editors at the right
highlight query. For Zed, Neovim, Helix, etc. the standard parser-discovery
flow picks the grammar up; see your editor's tree-sitter docs.

## Coverage notes

What works (all checked against the in-tree compiler sources):

- All top-level decls: imports, externs, free functions, structs (with
  generic type parameters), enums, interfaces, type aliases, `test` blocks.
- Statements: `let`, `let .Pat(...) = ... else`, assignments + `+=`,
  `if`/`else if`/`else`, `for cond`, `for x in xs`, `match`, `throw`,
  `try`, `must`, `assert`, `break`, `continue`, `return [expr]`.
- Expressions: binary ops with realistic precedence, field access,
  indexing, slicing, calls (with labeled args), array literals, f-string
  interpolation, char literals, implicit-variant references (`.Foo`).
- Types: named, generic, array, optional, `T or Error`.

Known limitations — would need an external scanner or a heavier rewrite:

- **Triple-quoted strings** (`"""..."""`, `f"""..."""`) aren't matched —
  tree-sitter regex has no look-ahead, so detecting the closing triple
  requires C-side scanning. They parse as a sequence of broken
  single-quoted strings; tree-sitter recovers and the rest of the file
  highlights fine.
- **Single-statement match arms** with greedy bodies sometimes chain into
  the next arm (`.A -> x` followed by `.B` is parsed as `.A -> x.B`).
  Block bodies (`.A -> { x }`) avoid this entirely and are the common
  shape in real code anyway.
- Pattern bindings vs expression args inside `.Variant(...)` aren't
  distinguished in the parse tree — both look like a call on an
  implicit-variant callee. Highlighting doesn't need the distinction.

The grammar's intentionally GLR-friendly: where two parses are equally
valid (e.g. struct construction vs function call), it picks one and moves
on rather than declaring a conflict.
