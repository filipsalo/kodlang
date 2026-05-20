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

## Parser

- [ ] Python parser raises on the first error rather than recovering and
      reporting the rest. The self-hosted parser doesn't report errors
      at all — `expect()` just `advance()`s without checking the kind,
      so syntactically bad input ends up as garbage AST that the codegen
      then trips over with confusing messages.
- [ ] Python AST nodes still carry `type[types.Type]` references (Python
      class objects) in fields like `FunctionDeclaration.return_type`.
      Keep the AST data-only so the Python frontend doesn't drift away
      from the Kod-side AST shape.

## Match / enums

- [ ] Exhaustiveness checking for match — the codegen accepts a match
      that doesn't cover every variant and just falls through.

## Build process

- [ ] Track which module-level names are actually accessed and skip
      compiling unreachable functions.
