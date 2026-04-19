# Roadmap

## Milestone: Self-hosting

The primary near-term goal is to implement just enough language features to be able to write
the Kod compiler in Kod itself. The Python implementation will serve as a bootstrap compiler —
used to compile the Kod-written compiler, which can then compile itself going forward.

This means prioritising features that a compiler implementation actually needs: string
manipulation, data structures, pattern matching, file I/O, and a sufficient type system.
Feature work should be evaluated against whether it moves the needle toward self-hosting.


## Typechecker

- Two-pass type inference and checking:
  - First pass: infer types on all AST nodes
  - Second pass: check/validate types on all AST nodes
- All module-level declarations should have a canonical internal name (like functions already do)
- Keep track of types separately from the AST

## Architecture

- Should the typechecker and compiler share a visitor infrastructure? There is significant
  overlap in how both traverse the AST and resolve names. Options:
  - A shared visitor base class
  - Free functions that take `program` and `module` as arguments (like `resolve_function`)
  - Keep them separate but extract shared helpers
- Modules should probably only contain declarations at the top level — not arbitrary statements
- Module-level names should be collected earlier in the pipeline, before the typechecker and
  interpreter each do it independently
- Consider making AST classes data-only and returning parse methods to the parser

## Build process

- Dead code elimination: let the typechecker track which module-level names are accessed,
  and have the compiler skip modules and functions that are never called
- Built-in sampling profiler: sample the call stack at regular intervals

## Type system

- Clean up type representation in the AST — `Statement`, `Expression` and similar aliases
  should be usable as real type hints throughout
- Type classes for primitive types
