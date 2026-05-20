# TODO

For very-specific locations, prefer a `TODO:` comment in the code
over a line here. This file collects work that doesn't have a single
pinpoint location, or where the locus might move.

## Self-hosting / build pipeline

- [ ] **Walk imports transitively in `kodc.kod`'s entry loader.** Today
      only modules the entry file imports directly are registered. If
      A imports B and B imports C, C isn't loaded unless A also
      imports it. `resolve_field_kinds` patches up registration-order
      within the loaded set but can't conjure structs from unloaded
      modules. See the TODO at `kodc.kod`'s import-walk loop.
- [ ] **Port `compose_test_runtime_main_asm` to Kod.** Depends on the
      transitive-import item above (the test variant needs to find
      every module with `test` blocks across the import graph).
- [ ] **Route the integrated `kod build` path through sh_kodc** for
      `compose_runtime_main_asm`. Currently only the CLI handler in
      `kod/__main__.py` delegates; `kod/builder.py:build_runtime_main`
      still uses the Python composer in-process.

## Codegen

- [ ] **Enum variant field kinds aren't re-resolved.**
      `resolve_field_kinds` only fixes struct fields. Enum variants
      could have the same registration-order issue; no in-tree case
      bites today.
- [ ] **`mov xN, #imm` outside `load`/`mov_to`.** Several emit sites
      use `mov reg, #N` for buffer sizes, enum discriminants, etc.
      They pass small controlled values today, but should route
      through `emit_load_imm` if any ever exceed 16 bits.

## Tests

- [ ] **`tests/transitive_entry.kod` / `tests/transitive_dep.kod`** are
      manual cross-module fixtures; don't match `*_test.kod` so
      `kod test .` doesn't pick them up. Leave as fixtures or rename
      into the auto-run set.

## Typechecker

- [ ] Fix name collision: `collect_functions` keys on function name only, so two modules
      with a function of the same name silently overwrite each other — key should be the
      fully-qualified label name
- [ ] `infer_type` only handles literals and explicitly annotated variables — extend to
      cover more expression types (function call return types, binary operator results, etc.)
- [ ] Type-check `Import` nodes: warn on unused imports
- [ ] Deduplicate `resolve_function` logic shared between `Compiler` and `TypeChecker`
      (see `Compiler.resolve_function` — nearly identical to the dot-call path in the typechecker)
- [ ] Enforce that `none` comparisons only appear with optional types (currently only
      catches the case where both sides' types are known; needs broader coverage)

## Parser

- [ ] Parser should recover from errors and keep parsing rather than stopping at the first one
- [ ] Struct types shouldn't carry Python-level type objects in the AST — keep AST data-only

## Enums

- [ ] Enum function argument passing — the current calling convention only passes one
      register per argument; enums need two (discriminant + payload). Requires ABI changes
      or passing by reference via arenas
- [ ] Match as expression (currently statement only)
- [ ] Exhaustiveness checking for match

## Optional types (`T?`)

- [ ] Design and implement `Optional[T]` as a built-in enum with `Some(T)` and `None`
      variants, with `T?` as syntactic sugar — enums are now implemented so this is unblocked

## Interpreter

- [ ] Add `.to_str()` method on builtin types
- [ ] Implement type classes for the primitives

## Build process

- [ ] Track which module-level names are actually accessed; skip compiling unreachable functions
