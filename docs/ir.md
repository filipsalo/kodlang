---
icon: lucide/workflow
---

# Compiler IR (design)

Status: steps 1–4, 8, 9 and 10 done; steps 5 and 7 measured and not landed. This page is the plan for giving the compiler an intermediate
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
   offset, an index register, scaled by the access size or not, or a symbol's
   page offset); register pairs are a
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
5. **Retain and release cancelling** (measured, dropped). The plan was explicit
   `Retain(v)` and `Release(v)` operations and a pass cancelling a retain and a
   release of the same value with nothing between them that could free it.
   There are none to cancel: each retain copies a borrowed reference into a
   place that owns it (a local's slot, 58%, or a field or element, 33%), and its
   release comes much later, when the slot is overwritten or goes out of scope.
   Nor would it pay much: compiling `codegen.kod` runs 46M retains and 50M
   releases, and with both stubs reduced to a `ret` the compile is only 5%
   faster. Most of what reference counting costs is allocating and freeing.
6. **Measured first.** Counting how often each basic block runs, on the
   compiler compiling `codegen.kod` and on the benchmarks, gives each candidate
   as a share of the instructions executed (an upper bound on the time saved:
   a 12% drop in instructions made `loop` 2% faster):

    | Candidate | compiler | sieve | qsort | inflate |
    |---|---|---|---|---|
    | Loads a loop can't change | 1.5–3.6% | 14% | 8.6–16% | 1.3–7.4% |
    | Register copies | 14% | 26% | 16% | 20% |
    | Bounds checks run | 2.3% | 4.7% | 7.6% | 3.9% |
    | Redundant loads within a block | 1.8% | 1.4% | 0.9% | 1.0% |
    | Dead stores, constant folding | <0.5% | 0 | 0 | 0.2% |

   Done from it: a frame over 256 bytes is addressed from its bottom in x28,
   one instruction per slot instead of three (5% of the compiler's
   instructions), and a large constant skips the `movk` of a zero part.
7. **Loop-invariant loads** (tried, not landed; branch `ir-hoist-loads`). After
   register allocation, a load in an innermost loop moves to just before the
   loop's top label when the loop is entered only there, its address doesn't
   change in the loop (a frame slot it doesn't store to; a heap address whose
   base it doesn't change, in a loop with no call and no heap store), a heap
   load's base is one the loop's top already reads through (so it isn't read
   early past a check for `none`), and the function leaves a register free for
   it (callee-saved when the loop makes a call). The load in the loop becomes a
   copy from that register. Done before allocation instead, the moved loads
   took registers from promoted locals, which then went back to memory.
   It made qsort and words about 2% faster and nothing else measurably, while
   the pass cost 6% of compile time: the safe rules leave most of the loads
   counted above in place (most hot loops store to the heap), and fewer
   instructions buy less time than they suggest. Not worth it as it stands.
   Register copies are the largest category but the least certain win (Apple's
   cores eliminate most of them when renaming), so they were timed first, on
   hand-edited output of the hottest loops of sieve and qsort:

    | Hand edit | sieve | qsort |
    |---|---|---|
    | Copies removed (4 of 13 and 2 of 13 instructions) | −0.3% | −0.8% |
    | Bounds checks also removed (length load, compare, branch) | −6.1% | −6.2% |

   Copies cost next to nothing, so coalescing them isn't worth a pass. Bounds
   checks cost a few percent where a hot loop indexes an array, but removing
   one needs a proof that the index is in range, which neither of these loops
   gives (`j <= n` against a length built by appends; `i`/`j` moved by the
   comparisons).

   Nor do most checks elsewhere. Of the 66M checks run compiling `codegen.kod`,
   about a fifth are in a `for k in a..len(x)` loop that leaves `x`'s length
   alone, which a simple pass could prove; another fifth follow a test such as
   `i < len(s)` and would need the conditions tracked. At the half a cycle a
   check costs in the timed loops, removing all of them would save about 2.5%
   of the compile, and the provable fifth about 0.5%; the hot checks of the
   benchmarks are none of these. Not worth a pass for now.
8. **Registers as numbers.** An instruction's registers and `Op` operands are a
   `regalloc.Reg`, an int64, instead of text: `4n+1` is vreg `n` (`v12`),
   `4n+2` its 32-bit form (`w12`), `4n+3` the immediate `#n`, and `4k` the
   `k`th name of a table (`regalloc.NAMES`): 0 is none, `x0`–`x30`, `fp`,
   `lr`, `sp` and `xzr` come first, and any other operand (a condition, a
   symbol's page, a negative immediate) is added the first time it's named.
   Codegen still names registers as text: its `emit_` functions turn each into
   a `Reg` once (`regalloc.reg_of`), so the passes compare numbers instead of
   parsing names, and nothing in an instruction is counted. The output turns
   them back (`regalloc.reg_text`, `arm64.phys_of`). The allocator's pool,
   the target's registers and each vreg's register are `Reg`s too. Labels,
   call targets, symbols in an address and directives stay text. What is
   left of the text is codegen's own: `alloc_reg` still names a vreg `v12`,
   and each `emit_` reads the name back.
9. **Machine words instead of text** (done). Assembling the output
   costs far more than compiling it: `as` takes 3.1 s on what the compiler
   writes for `codegen.kod` in 0.22 s, and about four fifths of the gates'
   CPU time. Clang's assembler spends it matching each register operand
   against every kind of register name (22 µs a line); a line written as the
   instruction's word, `.inst 0xaa0103e0` for `mov x0, x1`, assembles to the
   same bytes about 50 times faster. So `arm64.encode` gives the word of
   each instruction that names only registers and immediates, and the output
   writes that, with the instruction as a comment; anything with a label or
   a symbol, and any form `encode` doesn't know, stays text.
   `asm_diff.py --objects` checks the result: every object file in the
   corpus must have the same bytes as when the text is assembled.

   Then the object file without `as`: `kod/macho` reads the compiler's
   output (labels, the directives it writes, `.inst` words, and the
   instructions that name a label or a symbol) and writes a Mach-O object
   itself, in the compiler's own process, when `link.cfg` says `AS := kod`.
   What it writes is laid out more plainly than clang's (symbols grouped and
   sorted, data that points at a temporary label relocated against its
   section), so the check is by meaning, not bytes: `tools/as_diff.py`
   assembles every file of the corpus both ways and compares each section's
   bytes with the relocated fields cleared, each relocation's place, kind and
   target, and the symbols. Every instruction reaches it as a word except
   those, so the compiler writes the words of large constants and inlined
   functions too (`arm64.encode_text` encodes an instruction given as text).
   The Makefile keeps clang's assembler, since it runs before any compiler of
   this tree exists.
10. **Copy-on-write checks out of loops** (done). Arrays are values: before
   an element store, emit_unique checks that the array's count is 1 and
   copies it otherwise. In an innermost loop entered only at its top that
   calls nothing but panics, releases and the copy, no array can gain a
   holder (that takes a retain, a call) or be replaced where it's kept (the
   same), so `hoist_unique_checks` drops the loop's checks on an array in a
   local's slot the loop doesn't store to, or in a field of a struct in a
   register the loop doesn't write or a slot it doesn't store to, and checks
   once before the loop instead. Dropping a check that repeats one in
   straight-line code (qsort's swap) was tried and gained nothing measurable.
11. **Then, as needed:** an x86-64 lowering (see the parked assessment: register
   pools, calling convention, runtime stubs, symbol names).

## Open questions

- **Calls:** today codegen moves arguments into `x0`–`x7` itself. Roles cover
  that while a target has at least as many argument registers as a call needs;
  x86-64 has six. A `Call(target, args)` with the arguments as operands would
  let lowering place them, at the price of touching every call site.
- **Data:** string literals, vtables, line tables and the symbol table are
  emitted as directives through the same buffer. They need their own
  representation once text goes.
