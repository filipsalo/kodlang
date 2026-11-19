---
icon: lucide/workflow
---

# Compiler IR (design)

Status: proposed. This page is the plan for giving the compiler an intermediate
representation; it describes the compiler, not the language.

## Where it starts

`codegen.kod` walks the AST and emits arm64 instructions into a per-function
buffer of `regalloc.Insn` values. Since the structured-instructions work
(522f24e … abf4e42) most of them are no longer text:

| Variant | What it is |
|---|---|
| `Slot(store, reg, off)` | `ldr`/`str` to a frame slot |
| `Mov(dst, src)` | register move |
| `Mem(op, reg, base, off, has_off)` | load or store through a register |
| `Op(mn, a, b, c, d, flags)` | any other instruction with one-token operands |
| `Call(target)` | `bl` |
| `Branch(op, reg, target)` | `b`, `b.cond`, `cbz`, `cbnz` |
| `Label(name)` | a label |
| `Raw(text, info)` | the rest: about 60 emit sites and the directives |

After a function is emitted, passes run over the buffer (`peephole`,
`promote_locals`, `forward_copies`, register allocation, `long_branches`), and
the buffer is printed as assembly.

This is already a low-level IR, but an arm64 one: mnemonics are arm64's, physical
registers (`x0`–`x7` for arguments, `x16`/`x17` as scratch, `fp`, `sp`, `xzr`)
are named in it, and calling, addressing and immediates follow arm64's rules.

## Goal

A target-neutral low-level IR (LIR) in place of the arm64 instruction buffer:

- **Operations, not mnemonics:** `add`, `load64`, `store8`, `compare`,
  `branch_if(cond)`, `call`, `retain`, `release`, … with virtual registers and
  immediates as operands.
- **Roles, not registers:** argument *i*, the result, scratch, the frame, the
  stack. Each target maps a role to its register.
- **Lowering per target:** one pass turns LIR into a target's instructions.
  Arm64 first, printing exactly what the compiler prints today; x86-64 later.
- **Passes on LIR:** the existing ones, target-neutral where they can be, plus
  new optimisations.

Not a goal for now: SSA, a mid-level IR between the AST and LIR, or rewriting
how `codegen.kod` walks the AST. Codegen keeps doing what it does; what it emits
changes.

## How it gets there

Every step until the first optimisation keeps the output byte-identical, checked
with `make asm-diff` over the whole corpus, as the structured-instructions steps
were.

1. **Neutral operations.** `Op`'s mnemonic strings, `Branch`'s ops and `Mem`'s
   ops become enums of operations (`Add`, `Compare`, `Load(width)`,
   `BranchIf(cond)`, …). Arm64 lowering prints the mnemonic for each.
   Mechanical, over the ~600 structured emit sites.
2. **Register roles.** Physical register names in emit sites become roles
   (`arg(0)`, `scratch(1)`, `frame`, …). The register pools in
   `regalloc` describe a target rather than being arm64's.
3. **No text left.** The ~60 remaining text sites become operations that a target
   lowers to several instructions: the address of a symbol (`adrp` + `add`), a
   large constant (`mov` + `movk`), the prologue and epilogue (`stp`/`ldp`),
   indexed memory. Directives move to a separate data model, since they're not
   instructions. `line_info` and the text paths in the passes go.
4. **Target-specific passes split out.** Peepholes that are arm64 idioms (`cset`
   + `cbz` into `b.cond`) move into the arm64 lowering or an arm64 pass;
   `promote_locals`, copy forwarding and register allocation stay neutral.
5. **First optimisation:** explicit `Retain(v)` and `Release(v)` operations, and
   a pass that cancels a retain and release of the same value with nothing
   between them that could free it. Reference counting is about 30% of compile
   time; the generated code for `codegen.kod` has about 5,000 retain and 14,000
   release sites. Measured on the benchmarks before and after.
6. **Then, as needed:** constant folding, redundant-load elimination, dead stores;
   an x86-64 lowering (see the parked assessment: register pools, calling
   convention, runtime stubs, symbol names).

Steps 1–4 are the bulk of the work and change nothing a program does; step 5 is
the first that does, and is where the IR starts paying for itself.

## Open questions

- **Calls:** today codegen moves arguments into `x0`–`x7` itself. Roles cover
  that while a target has at least as many argument registers as a call needs;
  x86-64 has six. A `Call(target, args)` with the arguments as operands would
  let lowering place them, at the price of touching every call site.
- **Data:** string literals, vtables, line tables and the symbol table are
  emitted as directives through the same buffer. They need their own
  representation once text goes.
