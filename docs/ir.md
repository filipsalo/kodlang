---
icon: lucide/workflow
---

# Compiler IR (design)

Status: steps 1–4 done. This page is the plan for giving the compiler an intermediate
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

1. **Neutral operations** (done). `Op` holds a `regalloc.Opcode` (`Add`,
   `Compare`, `SetIf`, `AddressPage`, …), `Mem` a direction and a width in
   bytes, and `Branch` a `BranchKind` (`Always`, `If(Cond)`, `IfZero`,
   `IfNonzero`); the arm64 lowering (`arm64_mnemonic`, `mem_mnemonic`,
   `branch_mnemonic`) prints their mnemonics. Conditional branches are now
   always written `b.cond`, which assembles to the same bytes as `bcond`
   (checked with `asm_diff.py --objects`). Still strings: the condition operand
   of `SetIf`, `Select` and `CompareIf`, and the register names.
2. **Register roles** (done for the allocator). The register pools come from a
   `regalloc.Target` (`TARGET`, `ARM64`): the caller- and callee-saved
   temporaries, the order the prologue saves registers in, and the argument
   registers. In codegen the registers it names itself stay spelled as arm64
   spells them, as role names: `x0`–`x7` for arguments and the result, `x16`,
   `x17` and `x9` as scratch (`x17` also passes a value to the reference-counting
   stubs), `fp`, `sp`, `xzr`, and `d0`, `d1` for floats. Renaming them would
   decide nothing yet: what a second target needs is to tell argument 0 from the
   result (both `x0` on arm64), and that is for its lowering, which can map
   `x0` to its first argument register and move the result there after each
   call.
3. **No text left** (done). `Mem` addresses through a `MemAt` (the base, an
   offset, an index register or a symbol's page offset); register pairs are a
   `Pair` (offset, pre- or post-index); a constant too big for one move is a
   `LoadConst`, which the line limits count as the four lines arm64 needs; an
   inlined runtime function is an `Intrinsic(label)` whose lines come from the
   arm64 table (`arm64_intrinsic`); directives and data labels are `Data`, which
   no pass reads. Nothing makes instruction text any more: `Raw`, `line_info`
   and the passes' text paths are gone, and an `Op` operand that isn't one
   token is a compiler bug. Assembly text exists only at output
   (`format_insn`, and `print_encodable` for an immediate too big to encode).
   The symbol's page (`AddressPage` with an `@PAGE` operand) is still two
   operations and arm64's way of addressing; one `AddressOf(symbol)` is left
   for the second target to need.
4. **The arm64 lowering in its own module** (done). `stdlib/kod/arm64.kod`
   holds everything that writes arm64: the mnemonics and condition names, each
   instruction's text (`format_insn`, given the allocator's vreg-to-register
   table), the inlined runtime functions, the `mov`/`movk` lines for a large
   constant or an immediate too big to encode, and `line_count`. `regalloc`
   holds the IR and the allocator and doesn't import it. Still in codegen and
   still arm64's: `peephole` (its patterns are neutral, but the immediates it
   folds are arm64's 12-bit ones) and `long_branches` (arm64's 1 MB branch
   reach), to move behind the target when a second one exists.
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
