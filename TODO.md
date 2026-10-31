# TODO

For very-specific locations, prefer a `TODO:` comment in the code
over a line here. This file collects work that doesn't have a single
pinpoint location, or where the locus might move.

## Parser

- [ ] Python parser raises on the first error rather than recovering and
      reporting the rest. (The self-hosted parser's `expect()` now
      records a structured `ParseError` on mismatch, advances past
      the bad token, and keeps going — those errors are folded into
      `cg.errors` so `kodc`, the LSP, and `try_compile` all see them.
      Could do error recovery / synchronization next; right now we
      report each `expect()` failure individually.)
- [ ] Python AST nodes still carry resolved `type[types.Type]` objects in
      `Variable.type` (struct fields + params) and `TypeDeclaration.type`.
      `return_type` is now data-only (`ast.TypeExpr` via
      `parser.parse_type_expr` / `resolve_type_expr`); extend the same
      treatment to the rest. The blocker is `StructType.make`, which reads
      `field.type.width` for struct layout — so field types must resolve
      somewhere before layout, either at parse time (as today) or in a
      dedicated resolve pass over the data-only AST.

## Python

Frozen (see `docs/self-hosting.md`): the interpreter, the Python lexer and parser,
`kod/loader.py` and the shim writer `kod/bootstrap.py` stay as the bootstrap and as a
second implementation of the language. Nothing is added to them for build logic or new
language features, so the two parser items above are low priority.

- [ ] Retire the interpreter and the Python bootstrap behind a git tag, once a compiler
      source wants a language feature the Python side lacks. The checked-in snapshot is
      then the only way back from a broken compiler, and the `both`-mode fixtures become
      compiled-only.

## Build process

- [ ] Track which module-level names are actually accessed and skip
      compiling unreachable functions.
