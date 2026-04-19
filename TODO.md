# TODO

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
