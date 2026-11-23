---
icon: lucide/git-fork
---

# Concurrency (design)

Status: being built. Milestone 1 of step 1 is in: `spawn`, `Task[T]` and
`wait()`, and a function waiting for its tasks ([Tasks](tasks.md) describes
what works); the rest is a proposal. It describes what Kod would add for doing several things at once, in two steps, and what it promises now
so that those steps stay possible. The building blocks are Go's (tasks,
channels, `select`), used in a structured way (a task belongs to the function
that starts it), on one thread: Kod doesn't share memory between threads.

## What it is for

Programs that wait: an HTTP server answering several clients, a client
fetching several URLs at once, a language server that stays responsive while
it checks a file, a tool that runs subprocesses and reads their output as it
comes. These need **concurrency**: many things in progress, each spending most
of its time waiting for I/O.

Using several cores for one computation, **parallelism**, is a second and
smaller need. Today processes cover it: `kod test` and the test runner run
files in parallel, and `testing.run` forks.

Not a goal: threads sharing objects, locks around shared data, or an `async`
keyword.

## What the runtime decides already

Four facts of today's runtime rule out the usual answer, threads that share
memory:

- **A count that reaches zero frees the object at once.** If threads shared
  objects, one could read a reference out of a field while another stores
  over it and releases the old object, freeing it before the reader retains
  it: a use-after-free from ordinary code, which Kod has none of outside
  `unsafe`. Copy-on-write has the same gap: an array whose count is 1, in a
  field two threads reach, is changed in place while the other reads it. Go
  is spared this because its garbage collector frees nothing still
  reachable. Atomic counts don't close the gap, and they are not the cost
  they are often said to be: with `stadd` and `ldaddal` they measured 0%
  compiling `codegen.kod`, +1% on trees and +2% on words (cycles,
  2026-11-23), as long as one core owns each object. An object many cores
  retain at once would move its count's cache line between them on every
  retain and release.
- **The allocator's free lists are one global** (`rc_free_lists` in
  `stdlib/rc.c`), and the stdlib keeps state in module variables
  (`posix._read_buf`, `time._ts`, `testing`'s counters).
- **Arrays, `Map`s and plain structs are values** with copy-on-write: one can
  be handed to other code without being shared.
- **`shared struct` marks every type that is shared by reference**, so the
  compiler can tell a value that holds one from one that doesn't.

The first two say: never let two threads reach one object. The last two say
Kod is well placed to live with that.

## Step 1: tasks on one thread

A **task** is a call running on a stack of its own. All tasks run on the
program's one thread, one at a time; a task runs until it would wait, then the
next ready one runs. Nothing is shared between threads, so there are no data
races, and reference counts, the allocator and module variables stay as they
are.

The building blocks are Go's: tasks, channels, `select`. How they are used is
structured, as in Kotlin, Swift and Trio: a task belongs to the function that
started it, gives back its result, and is cancelled when that function gives
up on it. That takes the place of Go's `WaitGroup`, `errgroup` and `Context`,
and no task is left running by mistake.

### `spawn`, and a task's result

<!-- no-check -->
```kod
let user = spawn fetch_user(id)          // Task[User or Error]
let orders = spawn fetch_orders(id)
show(try user.wait(), try orders.wait())
```

`spawn` takes a call: the function and its arguments are evaluated where it
is, and the call then runs as a new task. It gives a `Task[T]`, `T` the call's
result, and `wait()` gives that result once the task has ended, so `try`,
`must` and `? or default` work on it as on the call. A call that gives back
`none` can be spawned as a statement; one that gives back a value has its
task kept, as any value must be (`let _t = spawn f()` to drop it on purpose).

### Tasks belong to the function that starts them

A function doesn't return while a task it spawned is running: at its end it
waits for each one it hasn't waited for. When the function leaves early, by
`return`, `throw` or a `try` that passes an error up, the tasks it hasn't
waited for are **cancelled** first. A cancelled task carries on until it next
waits, and that wait gives an `IoError` of kind `.Cancelled`, which `try`
passes up as any error, so it ends; what such a task gave back is dropped.

It is the function a task belongs to, not the block it was spawned in: a
loop that spawns a task each time leaves them running until the function
ends, unless it waits for them. That is simpler to follow than a wait at the
end of every block (as Kotlin's `coroutineScope` has).

<!-- no-check -->
```kod
func dashboard(anon id: int64) -> Page or Error {
    let user = spawn fetch_user(id)
    let orders = spawn fetch_orders(id)
    return Page(user: try user.wait(), orders: try orders.wait())
}   // when fetch_user fails, fetch_orders is cancelled, not left running
```

A `Task` can't leave the function that spawned it: it can't be returned,
stored in a field, an array or a variable outside it, or captured by a
closure that outlives it. It can be passed to functions that the spawning one
calls.

A task that should outlive its function, such as a server's connection
handler, is started with `spawn detached`: it gives no `Task`, nothing waits
for it, and it runs until its call returns or the program ends.

<!-- no-check -->
```kod
for true {
    let conn = try listener.accept()
    spawn detached serve(conn)
}
```

`main` is a function like any other: it waits for its tasks before the
program ends; detached ones end with the program.

### Timeouts

`tasks.within(d, f)` runs `f` and gives back what it gives back, or a
`Timeout` error after `d`, when it cancels `f` and the tasks `f` started:

<!-- no-check -->
```kod
let page = try tasks.within(Duration(s: 5), func() -> Page or Error {
    return dashboard(id)
})
```

### Channels

`Channel[T]` is a builtin type, like `Map`: it needs no import, since `spawn`,
`select` and `for v in ch` are part of the language too, as `chan` is in Go.

<!-- no-check -->
```kod
let jobs = Channel[str]()                 // unbuffered: a send waits for a receive
let results = Channel[int64](capacity: 8) // buffered: a send waits only when full
jobs.send("a.txt")
let n = results.receive()                 // int64?: none once closed and drained
jobs.close()
for job in jobs {                         // receives until the channel is closed
    work(job)
}
```

A channel carries any value, shared structs included: everything is on one
thread. Sending on a closed channel, or closing one twice, panics, as in Go.
A wait on a channel is a wait like any other: cancelling a task that waits in
`send` or `receive` ends that wait with `.Cancelled`.

### `select`

Waiting on whichever of several channel operations is ready first needs
syntax, and takes the shape of `match`:

<!-- no-check -->
```kod
select {
    receive(results) is r -> total += r
    send(jobs, next) -> sent += 1
    after(Duration(s: 5)) -> throw Timeout()
    else -> idle()
}
```

`receive(ch) is v` binds what was received (and takes the arm with `none` once
the channel is closed), `send(ch, v)` takes the arm once the value is taken,
`after(d)` once `d` has passed, and `else` at once when no other is ready.
When several are ready, one is picked at random, as in Go, so none starves.

### Generators

A function with `yield` in it is a generator: it gives back a `Channel[T]`,
and calling it starts its body as a task, which each `yield v` sends `v` on:

<!-- no-check -->
```kod
func lines(anon r: Reader) -> Channel[str] {
    for not r.at_end() {
        yield r.read_line()
    }
}

for line in lines(conn) {
    handle(line)
}
```

The channel is unbuffered, so the body runs only as far ahead as the reader
reads, and it is closed when the body ends. The task belongs to the caller,
not to the generator, which returns at once: a caller that stops reading
early cancels it when it returns, as with any task. `yield` is allowed only
in a function that gives back a `Channel`, and a generator's `return` takes
no value.

### Actors

A task that owns some state and serves messages needs nothing new; an enum
with payloads says what it can be asked:

<!-- no-check -->
```kod
type Msg = enum {
    Add(n: int64)
    Total(reply: Channel[int64])
}

func counter(anon inbox: Channel[Msg]) -> none {
    mut n = 0
    for msg in inbox {
        match msg {
            .Add(k) -> n += k
            .Total(reply) -> reply.send(n)
        }
    }
}
```

Only `counter` touches `n`, so nothing guards it.

### Helpers

In `tasks`, written with the above:

- `tasks.all(fs)` runs calls together and gives back their results in order,
  or the first error, cancelling the rest;
- `tasks.first(fs)` gives back the first to succeed and cancels the others;
- `xs.map_concurrently(f, limit: n)` maps over an array with at most `n`
  calls running at once;
- `tasks.Mutex`, for logic that holds a value across a wait (below);
- `tasks.give_way()` lets the other tasks run.

Outside tasks nothing changes: a program that never spawns one runs exactly
as today.

### When a task gives way

At the points where it would wait:

- reading or writing a descriptor that isn't ready (`posix.Fd`, `tcp`,
  `tls`, and so `http`, `stream` and `jsonrpc` above them), accepting,
  connecting;
- waiting for a child process (`process.Child.wait`);
- sleeping (`time.sleep`), sending, receiving, `select`, waiting for a
  task (`wait()`, and the wait at a function's end);
- `tasks.give_way()`.

These are also where cancellation reaches a task.

A task that runs long without waiting is preempted (below).
Waiting works the same through every layer, because the stack is the task's
own: when SecureTransport, in C, calls Kod's read callback and the socket has
nothing yet, the callback gives way with the C frames still on the task's
stack, and carries on when data comes. Stackless designs (`async`/`await`)
cannot do that, and would also split every function into the kinds that may
wait and those that may not.

When no task can run and none waits for anything that can come (a
descriptor, a timer, a child), the program panics with
`all tasks are asleep: deadlock`, as Go does, instead of hanging.

### Preemption

A task that runs long without waiting is also made to give way, as in Go, so
one busy loop can't keep the others waiting. The compiler puts a check at the
top of every loop iteration: a load from a **polling page**, the JVM's way,
with no branch. While more than one task is ready, a timer makes that page
unreadable every 10 ms; the next check then faults, and the fault handler
sends the task into the scheduler from there. The point is a known one, the
top of a loop: no reference count is half changed, and a stub that keeps
every register makes the switch, so the loop goes on as it was once the task
runs again. The handler tells the page from a real fault by its address, and
makes it readable again.

Measured on the benchmarks (cycles, 2026-11-23; the experiment is kept out of
the tree), against no check, and against a flag that each iteration loads
and branches on:

| check at each loop iteration | qsort | sieve | loop | words | trees | fib |
|---|---|---|---|---|---|---|
| load a flag, branch if set | +17% | +11% | +5% | 0% | 0% | +1% |
| load from the polling page | 0% | +9% | 0% | 0% | 0% | +2% |

The branch is what costs, in tight loops; what a check stops the optimiser
doing (reusing a load or hoisting it out of a loop, which it must not do
across a point where another task may run) cost nothing measurable. A tight
loop of stores, as sieve's, still pays for the load.

The check is in every loop of every program, since a module is compiled
without knowing whether the program starts tasks; a program that never does
pays for it too, and it is the one thing step 1 costs such a program. Code
that loops by recursion, without a loop, needs the check at function entry
as well, which is yet to be measured.

### The runtime

- **A task's stack** is reserved with `mmap` (8 MB of address space, as the
  main thread has, with a guard page below it). Pages are committed as they
  are touched, so a task that uses 20 KB costs 20 KB, and thousands fit, the
  way Go's small growing stacks do. Overflowing hits the guard page, as on
  the main stack.
- **Switching** saves the registers a call keeps (`x19`–`x28`, `fp`, `lr`,
  `sp`, `d8`–`d15`) and loads the next task's: a few dozen instructions in a
  naked function in the runtime, like the reference-count stubs.
- **The scheduler** keeps a queue of ready tasks. When it is empty it waits
  in `kevent` for whatever the waiting tasks wait on: a descriptor to become
  readable or writable, a timer, a child process to exit
  (`EVFILT_READ`/`WRITE`/`TIMER`/`PROC`).
- **Descriptors** a task uses are set non-blocking; a read that would block
  (`EAGAIN`) registers with `kevent` and gives way. While no task has been
  started the calls block as today; checking which applies is one load and
  branch per call.
- **`spawn`** compiles to a closure over the evaluated arguments, handed to the
  runtime with a fresh stack; the task ends when the call returns, and keeps
  what it gave back for `wait()`.
- **Belonging to a function**: a function that spawns gets a list of its
  tasks in its frame, and its exits (each `return`, and the paths `throw` and
  `try` take) wait for the list, cancelling first when the exit is early.
  Cancelling sets a flag on the task and wakes it if it waits; each wait
  point checks the flag. A function that spawns nothing pays nothing.
- **The compiler** checks that a `Task` doesn't leave its function, as it
  checks other uses of a local.
- **Backtraces** walk the frame chain of the task that panicked, which ends
  at its entry function. A panic ends the program, as now (and as in Go),
  wherever it happens.
- **Module variables**: a lazy initializer may now give way halfway (it reads
  a file, say). Another task that reads the variable meanwhile waits for it,
  instead of starting a second initialization.

### Limits of step 1

- **One core.** Tasks interleave; they don't run at the same time. Step 2 is
  the way to several cores.
- **DNS**: `getaddrinfo` has no non-blocking form here, so a lookup holds up
  every task until it returns. Later, a C helper thread could make the call
  and wake the task; it touches no Kod object, so it needs no changes to
  reference counting.
- **Regular files** are always "ready" to `kevent`; reading a large file
  blocks the thread while it does, which is short.
- **Interleaving still happens** where a task gives way: code that checks a
  shared value, waits, then acts on it can see it change in between. No data
  races, but logic races are still possible, as in Go; `tasks.Mutex` covers
  the cases that hold a value across a wait.

## Step 2: workers that share nothing

Here Kod departs from Go. Go runs goroutines on every core over one shared
heap. For Kod that would take one of three things: data races that may
free memory still in use, which gives up memory safety in racy programs (as
C++ and Swift 5 do); a compile-time proof that there are none (Swift 6's
actors and `Sendable`, Rust's `Send` and `Sync`), the largest language
change of the three; or frees delayed until every thread has moved on, with
each read of a shared field retaining through an increment-if-not-zero, a
cost on every such read. None is worth it yet, so Kod doesn't share memory
between threads.

For parallelism inside one process, later: a **worker** is a thread with its
own heap, free lists and module variables, running its own tasks. Workers
exchange values only through channels made for it, and only values that
contain no `shared struct`, closure or interface (which could hold one): those
are copied into the receiving worker's heap. Reference counts stay
non-atomic, because no object is reachable from two threads; the copy is the
price, paid only for what is sent. This is the model of Erlang processes and
Dart isolates.

Step 2 reuses step 1's channels and scheduler; what it adds is per-thread
runtime state and the check of what may be sent. It is a sketch, to be
designed when there is a program that needs it.

## What holds from now on

- **No object is shared between threads**, in either step, so a program
  without `unsafe` has no use-after-free. That also lets reference counts
  stay non-atomic, though they could be made atomic for little.
- **`spawn`, `select` and `yield` become keywords** when step 1 lands
  (`detached` is one only after `spawn`). No code in the repository uses
  `select` or `yield` as a name. `process.spawn`, a shorthand for
  `process.start(argv, stdin: .Null, stdout: .Null, stderr: .Null)` and its
  pid, is gone already.
- **`IoKind` gains `.Cancelled`**, the error a cancelled task's wait gives.
- **`Channel` joins the builtin type names** that only the builtins may
  declare (`Map`, `Option`, `Error`, ...); no code in the repository has a
  type of that name.
- **New mutable module state in the stdlib** is a cost for step 2; keep it to
  what a worker could have its own copy of.
- **Blocking calls go through a few low-level functions** (`posix.Fd.read`
  and `write`, `tcp`'s accept and connect, the TLS callbacks,
  `process.wait_status`, `time.sleep`): step 1 changes those, not their
  callers, so new I/O code should build on them rather than call `libc`
  directly.

## Building it

Each step lands with its tests, and the first is measured: the cost of a
switch, and that a program without tasks is no slower than the loop checks
make it.

1. Stacks, switching and `tasks.give_way` in the runtime; `spawn`, `Task[T]`
   and `wait()`, and the wait at a function's end. Tests of order, of deep
   recursion inside a task, and of a function not returning before its
   tasks.
2. `Channel[T]`, `close`, `for v in ch`, and deadlock detection.
3. `kevent`: descriptors, timers and child processes; `posix.Fd`, `tcp`,
   `process` and `time.sleep` give way inside a task.
4. Cancellation: early exits cancel, `.Cancelled` at every wait point,
   `spawn detached`, `tasks.within`; the check that a `Task` stays in its
   function.
5. `select`, generators and `yield`, `tasks.all`, `tasks.first`,
   `map_concurrently`, `tasks.Mutex`.
6. TLS and HTTP inside tasks; a demo that fetches several URLs at once, and
   a small concurrent HTTP server.
7. Backtraces, and lazily initialized module variables, across tasks.

Preemption comes after them: the loop checks, the polling page and its timer,
the fault handler, and the check at function entry, measured before it goes in.
