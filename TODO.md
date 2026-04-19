# TODO

## Typechecker

- [ ] Fix name collision: `collect_functions` keys on function name only, so two modules
      with a function of the same name silently overwrite each other — key should be the
      fully-qualified label name
- [ ] `collect_functions` only collects top-level declarations — functions defined inside
      other functions (if supported) would be missed
- [ ] Type-check `Import` nodes: warn on unused imports
- [ ] Deduplicate `resolve_function` logic shared between `Compiler` and `TypeChecker`
      (see `Compiler.resolve_function` — nearly identical to the dot-call path in the typechecker)
- [ ] Should `TypeChecker` use a visitor pattern? Currently hand-rolling dispatch with `match`.

## Parser

- [ ] Parser should recover from errors and keep parsing rather than stopping at the first one
- [ ] Struct types shouldn't carry Python-level type objects in the AST — keep AST data-only

## Interpreter

- [ ] Implement type classes for the primitives
- [ ] Add `.to_str()` method on builtin types
- [ ] Support string concatenation (`+`)

## Build process

- [ ] Track which module-level names are actually accessed; skip compiling unreachable functions
