---
icon: lucide/bug
---

# Debugging

A program `kod build` makes can be run under `lldb`, the debugger that comes
with Xcode's command line tools: breakpoints on Kod lines, a backtrace with
Kod functions, files and lines, and stepping a line at a time.

```
$ ./kod build hello.kod
$ lldb build/apps/hello/hello
(lldb) b hello.kod:12
Breakpoint 1: where = hello`greet + 20 at hello.kod:12, address = 0x...
(lldb) run
(lldb) bt
* frame #0: hello`greet at hello.kod:12
  frame #1: hello`main at hello.kod:20
(lldb) next
```

Functions go by their Kod names: `b greet` stops in `greet`, and a method is
its type's name and its own, `b Counter.bump`. (`b main` also finds the C
`main` that starts every program.)

## What the debugger is told

Each object the compiler writes carries DWARF, the format debuggers read:

- a line table: for each statement, where its instructions start, and its
  file and line;
- for each function, its name, file and line, and where its instructions
  start and end;
- its parameters and locals that live in the function's frame, with their
  types.

So `b file.kod:N`, `bt`, `next`, `step` and `finish` work, a crash under the
debugger stops at its Kod line, and `frame variable` shows values:

```
(lldb) frame variable
(str) name = (buf = "kod", len = 3)
([int64]) xs = {
  ptr = 0x0000300000000058
  len = 4
  cap = 6
}
(Pet) pet = {
  name = 0x0000000100035780
  age = 3
  tags = 0x0000300000000018
  owner = 0x0000300000000008
  happy = true
}
(lldb) p xs.ptr[3]
(long) 42
(lldb) p *pet.owner
(Counter)  (n = 9)
```

An `int64`, `bool` or `float64` shows as a number. A `str` (and `bytes`)
shows as its buffer and length, an array as its elements' pointer, length and
room, and a struct as its fields; a field or element that is one of those
holds a pointer to it, which `*` follows. Other types (enums, optionals,
maps, functions, ...) show as an address, under their Kod name.

What isn't shown yet: a local the compiler keeps in a register rather than in
the frame, which is most small ones (`register read` finds those), and the
locals of a function inlined into the one stopped in. A value whose last use
is past may already be released: a `str`, array or struct then reads as 0, or
as memory lldb can't read. A line inside a function that was inlined into its
caller has no instructions of its own; a breakpoint there lands on the call.

The debug information stays in the objects, under `build/`; the executable
only records where they are, as clang's does without `-g` flags of its own.
A program copied elsewhere is debugged with `dsymutil` first, which gathers
it into a `.dSYM` bundle beside the executable:

```
$ dsymutil build/apps/hello/hello
```

The compiler itself (`build/stage1/sh_kodc`, the snapshot) is linked without
that record, so that two builds of it can be compared byte for byte.

## Developer mode

`lldb` needs the system's permission to control another process. On a Mac
where Developer Mode is off, `run` stops at "Developer mode is currently
disabled" until it is turned on (`DevToolsSecurity -enable`, as an
administrator). Setting breakpoints, `image lookup` and the other commands
that only read the program work without it.
