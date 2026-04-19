# Roadmap

## Milestone: Self-hosting

The primary near-term goal is to implement just enough language features to be able to write
the Kod compiler in Kod itself. The Python implementation will serve as a bootstrap compiler —
used to compile the Kod-written compiler, which can then compile itself going forward.

Feature work should be evaluated against whether it moves the needle toward self-hosting.
A compiler needs: string manipulation, data structures, heap allocation, file I/O, and a
sufficient type system.

### Remaining blockers

- **Arena allocation** — structs and enums are currently stack-allocated with fixed size.
  Building recursive data structures (like an AST) requires heap allocation. Design: arenas
  with explicit passing, growing automatically when full. See discussion in code history.
- **Optional types (`T?`)** — enums are now implemented, so `Optional[T]` as a built-in
  enum with `Some(T)` / `None` variants is unblocked. Needed for nullable struct fields
  (e.g. the `else` branch of an `IfStatement` node).
- **String manipulation** — lexing source code requires character access, slicing, and
  length. Currently `str` supports concatenation (`+`) but not indexing or slicing.
- **File I/O** — reading source files requires some form of file access, likely via `extern`
  bindings to libc (`fopen`, `fread`, etc.) wrapped in a stdlib module.
- **Enum function arguments** — passing enums to functions requires an extended calling
  convention (enums are multi-word values). See `docs/enums.md` for details.
- **Dynamic arrays** — fixed-size arrays exist but a resizable list/array type is needed
  for token lists, AST node children, etc.


## Pattern matching

Basic match statements are implemented (see `docs/enums.md`). Remaining:

- Match as expression (currently statement only)
- Exhaustiveness checking
- Nested patterns
- `if let` shorthand for single-variant matching


## Type system

- **Optional types** — `T?` as sugar for `Optional[T]` enum (unblocked now that enums exist)
- **Type inference** — `infer_type` currently handles literals and explicitly annotated
  variables; needs extending to cover function return types, binary operator results, etc.
- **Generics** — needed for a proper `Optional[T]`, `List[T]`, etc. Currently types like
  `ArrayType` and `EnumType` are created dynamically in Python but there is no user-facing
  generic syntax.
- Clean up type representation in the AST — `Statement`, `Expression` and similar aliases
  should be usable as real type hints throughout


## Architecture

- Module-level names should be collected earlier in the pipeline, before the typechecker
  and interpreter each do it independently
- Modules should probably only contain declarations at the top level — not arbitrary statements
- The typechecker and compiler share significant logic for resolving names and traversing the
  AST; consider extracting shared helpers or a visitor base class
- Consider making AST classes data-only and returning parse methods to the parser


## Build process

- Dead code elimination: track which module-level names are accessed; skip compiling
  unreachable functions and modules
- Built-in sampling profiler: sample the call stack at regular intervals
