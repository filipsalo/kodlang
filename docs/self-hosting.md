---
icon: lucide/cpu
---

# Self-hosting

The primary goal of Kod is to compile itself — a *self-hosted* compiler. The Python implementation serves as the bootstrap compiler used to compile the Kod-written compiler, which can then compile itself going forward.

## Current status

The ARM64 code generator is written in Kod (`stdlib/kod/codegen.kod`) and runs under the Python interpreter. The full pipeline — lexer, parser, and codegen — exists in Kod source but has not yet been wired together into a working end-to-end self-hosted compile.

**What exists in Kod:**

- `stdlib/kod/ast.kod` — AST node types
- `stdlib/kod/lexer.kod` — Tokenizer
- `stdlib/kod/parser.kod` — Parser
- `stdlib/kod/codegen.kod` — ARM64 assembly emitter (~1850 lines)

**Next step:** wire up a `main` that reads a source file, drives the parser, and calls the codegen to emit assembly that `as` can assemble.

## Architecture

```
Source (.kod)
     │
     ▼
  Lexer          tokens
     │
     ▼
  Parser         AST (IDs into a node pool)
     │
     ▼
  Codegen        ARM64 assembly (stdout)
     │
     ▼
    as / ld      native binary
```

The self-hosted compiler targets a subset of Kod — enough to compile itself. It does not need to implement every feature the Python interpreter supports.

## Codegen design

The code generator in `stdlib/kod/codegen.kod` follows a single-pass design:

- **Register pool**: `x8`–`x15` (caller-saved), used as expression temporaries
- **Stack frame**: locals at `[fp, #-N]`, frame pointer convention matches ARM64 ABI
- **Enums**: represented as tagged structs on an arena heap
- **Strings**: arena-allocated, zero-terminated; `_kod_str_concat` for concatenation
- **Arrays**: 24-byte header `{ ptr, len, cap }`; elements 8 bytes each

## Remaining work

To achieve self-hosting the following are still needed:

- [ ] Entry point: `main` that reads source from a file and drives the pipeline
- [ ] File I/O in compiled mode (reading source files)
- [ ] Enough of the AST node types compiled to work with the parser output
- [ ] Fixing any codegen bugs revealed by actually compiling a real Kod file
- [ ] Generating a binary that can build itself

## Bootstrap process

Once the self-hosted compiler can compile itself, the bootstrap sequence is:

```
stage0: Python interpreter compiles codegen.kod → stage1 binary
stage1: stage1 binary compiles codegen.kod      → stage2 binary
stage2: stage2 binary compiles codegen.kod      → stage3 binary (identical to stage2)
```

If stage2 and stage3 are bit-for-bit identical, self-hosting is confirmed.
