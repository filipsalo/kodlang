---
icon: lucide/siren
---

# Panics

A panic is how a program stops at a bug: an index out of range, a division by
zero, a failed `must` or `assert`, a key that isn't in a map, a call of
`panic(msg)`. It prints the message and a backtrace to stderr and the program
exits with status 1.

Errors a program expects (a file that isn't there, input that doesn't parse)
are values of type `T or Error`, not panics: see
[Error handling](types.md#fallible-types-t-or-error).

## Catching a panic

A program that does many independent pieces of work, such as a server
answering requests, can keep one piece's bug from ending the others. The
`panics` module runs a function and catches a panic in it:

<!-- kod:
import "panics"
import "tasks"
func answer(anon n: int64) -> str or Error {
    return f"{100 / n}"
}
-->
```kod
let p = panics.run(func() {
    let xs = [1, 2, 3]
    print(xs[5])
})
if p is panics.Panic(caught) {
    print(caught.message)      // index 5 out of bounds for array of length 3
    kod_eprint(caught.backtrace)
}
```

| | |
|---|---|
| `panics.run(body) -> Panic?` | calls `body`, a `func() -> none`: the panic that stopped it, or none |
| `panics.catch(body) -> T or Error` | calls `body`, a `func() -> T or Error`: what it gave back, or the `Panic` that stopped it, as the error |
| `panics.again(p)` | panics with `p`'s message; its backtrace is `p`'s |

A `Panic` is an error with these fields:

| | |
|---|---|
| `message: str` | what would have followed `panic: ` |
| `backtrace: str` | the lines that would have followed it, `backtrace:` first, down to the catch |

Nothing is printed for a panic that is caught: the code that caught it decides.

<!-- kod:
import "panics"
func answer(anon n: int64) -> str or Error {
    return f"{100 / n}"
}
-->
```kod
match panics.catch(func() -> str or Error { return try answer(0) }) {
    Err(panics.Panic(p)) -> kod_eprint(f"answer panicked: {p.message}\n{p.backtrace}")
    Ok(text) -> print(text)
    Err(e) -> print(e.to_str())
}
```

A `run` or `catch` can be inside another: the innermost one running takes the
panic.

## What is undone

The functions between the panic and the catch don't go on. What they held is
let go of, as when they return: their variables and the values they were
working on are freed, and the tasks they spawned are cancelled and waited for.
A `mut` parameter keeps what it was last changed to, and a module-level
variable whose initializer panicked is worked out again at its next use.

Nothing else is undone:

- What they had already changed in values that outlive them (a shared struct's
  fields, module variables, variables the body captured) stays changed, so a
  change made in several steps may be half made.
- A file, socket or child process one of them had open stays open, and a
  `tasks.Mutex` one held stays locked. Open what must be closed outside the
  catch.

## Tasks

A task [belongs](tasks.md) to the function that spawned it, and so does its
panic. When that function runs under a catch, a panic in its task doesn't end
the program: it panics the function, with the task's message and backtrace, at
its next wait (the one it is in, if it's waiting), or when it returns, waiting
for its tasks. The function's other tasks are cancelled, and the catch around
the function takes the panic. `task.wait()` on a task that panicked panics too.

<!-- kod:
import "panics"
import "tasks"
func part(anon n: int64) -> int64 {
    return 100 / n
}
-->
```kod
func sum_parts() -> int64 {
    let a = spawn part(5)
    let b = spawn part(0)          // panics
    return a.wait() + b.wait()
}

let p = panics.run(func() { print(sum_parts()) })
assert p is panics.Panic(_caught)
```

A generator's panic comes out where its values are received. A detached task
belongs to nothing that could take its panic, so it ends the program even when
the code that spawned it runs under a catch: a detached task catches its own.
So does a panic in a task, or a generator, started under no catch at all.

## What can't be caught

- `all tasks are asleep: deadlock`.
- A crash: a stack overflow, a full heap, or anything a wrong `unsafe` call or
  C code does.

A call from Kod through C back into Kod (a [callback](unsafe.md#callbacks))
is abandoned like the rest, but C's part of it holds on to whatever it held.

## Cost

Code pays nothing for this while it runs: each function that can hold a
reference has a list of the places in its frame that do (a program is about 2%
bigger for them), read only when a panic is caught. `run` costs about 0.1 µs
more than calling `body`, and a caught panic a few microseconds: the backtrace
and each function given up is looked up in tables that grow with the program.
