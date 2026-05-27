# TODO

For very-specific locations, prefer a `TODO:` comment in the code
over a line here. This file collects work that doesn't have a single
pinpoint location, or where the locus might move.

## Self-hosting / build pipeline

- [ ] **Move more orchestration into sh_kodc.** runtime_main composition
      lives in Kod and runs via sh_kodc. The next pieces — driving `as`,
      `clang`, `ld`, walking modules — are still in Python. Subprocess
      support is there (`process.run`); just needs the pieces ported.

## Parser

- [ ] Python parser raises on the first error rather than recovering and
      reporting the rest. (The self-hosted parser's `expect()` now
      records a structured `ParseError` on mismatch, advances past
      the bad token, and keeps going — those errors are folded into
      `cg.errors` so `kodc`, the LSP, and `try_compile` all see them.
      Could do error recovery / synchronization next; right now we
      report each `expect()` failure individually.)
- [ ] Python AST nodes still carry `type[types.Type]` references (Python
      class objects) in fields like `FunctionDeclaration.return_type`.
      Keep the AST data-only so the Python frontend doesn't drift away
      from the Kod-side AST shape.

## Build process

- [ ] Track which module-level names are actually accessed and skip
      compiling unreachable functions.
