# TODO

For very-specific locations, prefer a `TODO:` comment in the code
over a line here. This file collects work that doesn't have a single
pinpoint location, or where the locus might move.

## Self-hosting / build pipeline

- [ ] **Move more orchestration into sh_kodc.** runtime_main composition
      lives in Kod and runs via sh_kodc. The next pieces — driving `as`,
      `clang`, `ld`, walking modules — are still in Python. Subprocess
      support is there (`process.run`); just needs the pieces ported.

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

- [ ] Wildcard-arm requirement for `int64` and `str` matches. Today
      they silently fall through on unmatched values; future change
      either requires a `_` arm at compile time or inserts a runtime
      panic for the no-arm case.

## Build process

- [ ] Track which module-level names are actually accessed and skip
      compiling unreachable functions.
