---
icon: lucide/git-branch
---

# Tasks

A **task** is a call that runs on a stack of its own, taking turns with the
others on the program's one thread: one runs until it waits or gives way,
then the next ready one runs. Nothing is shared between threads, so there are
no data races. [Concurrency (design)](concurrency.md) is the plan this is the
start of; what is below is what is built.

## `spawn`

<!-- kod:
func fetch_user(anon id: int64) -> str {
    return f"user {id}"
}
func fetch_orders(anon id: int64) -> int64 {
    return id * 2
}
-->
```kod
let user = spawn fetch_user(7)        // tasks.Task[str]
let orders = spawn fetch_orders(7)    // tasks.Task[int64]
print(user.wait())                    // user 7
print(orders.wait())                  // 14
```

`spawn` takes a call. The arguments are evaluated where `spawn` is, and the
call then runs as a new task, which starts the next time the spawning one
waits or gives way. For a call that gives back a value, `spawn` gives a
`tasks.Task[T]`, and `task.wait()` gives that value once the task has ended;
until then the waiting task waits. A result can be waited for any number of
times, by any task. A call that gives back nothing is spawned as a statement:
`spawn log(line)`.

The function, method or function value called is any a call can name:
`spawn fetch(url)`, `spawn conn.serve(req)`, `spawn handler(event)`, with
labels and defaults as in the call. A receiver or function value is the one
the name holds where `spawn` is. A `mut` argument can't be passed: the task
runs after the spawning function has gone on.

`spawn` needs no import; a module that uses it imports `tasks` on its own, and
naming the type in an annotation (`tasks.Task[int64]`) needs `import "tasks"`.

## Tasks belong to the function that spawns them

A function doesn't return while a task it spawned is running: where it
returns, by `return`, by `throw` or through a `try`, it first waits for each
of its tasks that hasn't ended. So no task is left running by mistake, and
`main` waits for its tasks before the program ends.

<!-- kod:
func fetch(anon url: str) -> none {
}
-->
```kod
func fetch_all(anon urls: [str]) -> none {
    for url in urls {
        spawn fetch(url)
    }
}   // returns once every fetch has ended
```

## Cancellation

A function that returns an error, by `throw` or through a `try`, **cancels**
the tasks it spawned that haven't ended before it waits for them; one that
returns anything else just waits. A cancelled task goes on until it next
waits, and that wait gives up:

- reading, writing, accepting, connecting and waiting for a child fail with an
  `IoError` of kind `.Cancelled`, which `try` passes up, so the task's own
  tasks are cancelled in turn;
- a sleep ends at once, a `receive` gives `none` and a `send` isn't made;
- `task.wait()` and `tasks.give_way()` go on as usual: they can't fail.

A loop whose only waits are such ends by asking: `tasks.cancelled()` is
whether the running task is cancelled.

`task.cancel()` cancels a task directly, unless it has ended; `task.wait()`
then gives what the task gave back after giving up, an error from its wait
for a fallible one. A task that never waits can't be cancelled, and nothing
cancels a detached task.

`tasks.within(d, body)` runs `body` as a task for at most `d`: it gives what
`body` gives back, or an `IoError` of kind `.TimedOut` once `d` has passed, when
the task is cancelled and waited for.

<!-- kod:
import "tasks"
import "time" { Duration }
func fetch_page() -> str {
    return "page"
}
-->
```kod
let page = tasks.within(Duration(seconds: 5), func() -> str { return fetch_page() })
```

A task that should outlive its function is started with `spawn detached`: it
gives no `Task`, nothing waits for it, and it runs until its call returns or
the program ends.

<!-- kod:
func serve(anon n: int64) -> none {
}
let n = 1
-->
```kod
spawn detached serve(n)
```

## Channels

A `tasks.Channel[T]` carries values from tasks that send them to tasks that
receive them, in the order they were sent:

<!-- kod:
import "tasks"
func produce(anon out: tasks.Channel[int64]) -> none {
    for i in 0..3 {
        out.send(i)
    }
    out.close()
}
-->
```kod
let numbers = tasks.Channel[int64]()             // unbuffered
spawn produce(numbers)
for n in numbers {                                // until it is closed
    print(n)
}
```

| | |
|---|---|
| `tasks.Channel[T](capacity: n)` | a channel that holds up to `n` values no task has received yet; `n` is 0 when left out |
| `ch.send(value)` | adds `value`; waits while `capacity` values sent before it haven't been received, so with 0 until a task receives this one |
| `ch.send_now(value) -> bool` | adds `value` if the channel is open and fewer than `capacity` values are waiting to be received, without waiting; whether it did |
| `ch.receive() -> T?` | the next value; waits while there is none, and gives `none` once the channel is closed and every value has been received |
| `ch.close()` | no more values will come: those waiting to receive get `none` once the rest are received |
| `for v in ch` | receives each value until the channel is closed and empty |

Sending on a closed channel, or closing one twice, panics, as in Go; so does a
send still waiting when its channel is closed. A channel can carry any value,
shared structs too: every task is on the one thread. A channel of an
optional type can't tell `none` sent from closed, as `T?` of an optional is
that optional.

## `select`

`select` waits for whichever of several channel operations can go first:

<!-- kod:
import "tasks"
import "time" { Duration }
let results = tasks.Channel[int64](capacity: 1)
let jobs = tasks.Channel[str](capacity: 1)
let next = "job"
mut total: int64 = 0
mut sent: int64 = 0
-->
```kod
select {
    receive(results) is r -> total += r? or 0
    send(jobs, next) -> sent += 1
    after(Duration(seconds: 5)) -> print("nothing for 5 s")
    else -> print("nothing ready")
}
```

Each channel and each value to send is evaluated first, in order. Then the
arm whose operation can go at once runs, picked at random among those that
can, so that none is passed over for good:

- `receive(ch) is v` when `ch` has a value or is closed: `v` is what
  `ch.receive()` gives, a `T?` that is `none` once the channel is closed and
  empty; `receive(ch)` drops it;
- `send(ch, value)` when `ch` can take the value without the sender waiting
  for long (it has room, or a task is waiting to receive), or is closed, when
  the send panics;
- `after(d)` once `d` has passed and nothing else has gone;
- `else` at once, when nothing else can go.

Without `else`, `select` waits until an arm can go. A cancelled task's
`select` takes its first `receive` arm (with `none` if nothing is there), or
its first `after`, or `else`.

## Generators

A function with `yield` in it is a **generator**: it gives back a
`tasks.Channel[T]` at once and runs its body as a task, which each
`yield value` sends on:

<!-- kod:
import "tasks"
-->
```kod
func countdown(anon n: int64) -> tasks.Channel[int64] {
    for i in 0..n {
        yield n - i
    }
}

for k in countdown(3) {
    print(k)                 // 3, 2, 1
}
```

The channel is unbuffered, so the body runs only as far ahead as the reader
reads, and it is closed when the body ends, by its last line or a `return`,
which takes no value. `yield` goes in a named function or method that gives
back a `tasks.Channel[T]`, not in a function literal.

The body runs while something holds the channel. Once nothing does, say a
`for` over it stopped early and the channel was let go, the body ends at its
`yield`, as at a `return` there: the channel isn't closed, nothing being left
to read it. A body already waiting in a `yield` when that happens ends when
the next generator starts. A cancelled body's `yield` ends it too. Like a
`spawn detached` task, the body belongs to no function, so nothing waits for
it.

<!-- kod:
import "tasks"
func countdown(anon n: int64) -> tasks.Channel[int64] {
    for i in 0..n {
        yield n - i
    }
}
-->
```kod
for k in countdown(1000000) {
    if k < 999998 {
        break                // countdown's body ends at its next `yield`
    }
}
```

## Helpers

| | |
|---|---|
| `tasks.all(fs: [func() -> T or Error]) -> [T] or Error` | runs each call as a task and gives back their results in order, or the first error to come, after cancelling the others |
| `tasks.first(fs: [func() -> T or Error]) -> T or Error` | runs each as a task and gives back the first result that isn't an error, cancelling the others, or the last error when all fail |
| `tasks.map_concurrently(xs: [T], f: func(T) -> U, limit: int64) -> [U]` | `f` of each of `xs`, in order, with at most `limit` calls running at a time |
| `tasks.Mutex()` | `lock()` waits until no other task holds it, `unlock()` lets the next one have it |

A `Mutex` is for a value that must not change between being read and written
back: across a wait, or across a loop iteration or a call, where a task may be
[preempted](#preemption).

## Waiting for I/O

A task that would wait for the outside world lets the others run meanwhile:

- `time.sleep(d)`;
- reading and writing a `posix.Fd`, and so a socket, a pipe to a child or
  anything [streams](io.md) are built on, including TLS and HTTP;
- `tcp` accepting and connecting;
- waiting for a child process (`process.Child.wait`).

While the others have nothing to do either, the program waits for the first
of those events (`kevent`). A program with one task just blocks there, as
without tasks.

Still holding up every task: `posix.poll`, `io.read_stdin_line` and the rest
of `io`'s standard input (read through C's buffered `FILE`), looking up a
host name (`getaddrinfo` has no form that doesn't block), and reading a
regular file, which is ready at once. Two tasks waiting to read one
descriptor at the same time aren't supported.

Timeouts hold in a task as without tasks: `tcp.connect`'s, and a socket's
own (`tcp.set_timeout`, and so the HTTP client's), which ends a read or write
that waits too long with `.TimedOut`. [HTTP](http.md#requests-at-the-same-time)
has requests made at the same time, and a server that serves each connection
in a task.

## Signals

`signals.listen` gives the signals that come to the program on a channel,
instead of what they would do by themselves, such as end it:

<!-- kod:
func reload() -> none {
}
-->
```kod
import "process" { Signal }
import "signals"

func reload_on_hup() -> none or Error {
    let sigs = try signals.listen([.Hup])
    for _sig in sigs.channel {
        reload()
    }
}
```

| Name | Meaning |
|------|---------|
| `signals.listen(sigs)` | a `Signals or Error` for a list of [`process.Signal`](builtins.md); `.Kill` is an `InvalidInput` error |
| `s.channel` | a `Channel[Signal]` of those that have come |
| `s.stop()` | ends it: closes the channel, and the signals do again what they did before |

When several listen for a signal, each gets it, and it does what it did before
again once the last has stopped. A signal that comes while 16 wait to be
received is dropped. A signal the program was started to ignore, as by `nohup`,
is given too. While something listens, waiting isn't a
[deadlock](#preemption): a signal may come.

A task doesn't have to wait for one to come: a busy loop is preempted for it,
but a call that holds up every task (as [above](#waiting-for-io)) delays it.
Programs started with `process` don't inherit any of it.

## Giving way

`tasks.give_way()` lets the tasks that are ready run, then goes on. Tasks run
in the order they became ready: a new one after those already waiting to run,
and one that gives way after the others. A task gives way where it waits,
and where it is preempted.

## Preemption

A task that runs for a while without waiting is made to give way, so one
busy loop doesn't keep the others waiting: about every 10 ms, the running
task gives way at the top of its next loop iteration or function call, as if
it called `tasks.give_way()` there.

<!-- kod:
import "tasks"
func work(anon n: int64) -> int64 {
    return n
}
-->
```kod
func crunch() -> int64 {
    mut sum: int64 = 0
    for i in 0..1000000000 {     // runs for seconds
        sum += i % 7
    }
    return sum
}

let busy = spawn crunch()
let quick = spawn work(1)
print(quick.wait())              // doesn't wait for crunch to end
```

So between two iterations of a loop, and as a function is called, other tasks
may have run, as across a wait: a value read from a shared struct before may
have changed since. Nothing else is interrupted: only those two are places
where a task is preempted, so no reference count or array is left half
changed.

Every loop and function has the check, a load from a page the program makes unreadable
when it is time ([Concurrency (design)](concurrency.md#preemption)); it costs
a few percent in
the tightest loops, and a program that never starts a task pays that too.
A child process made by `fork` (as `testing.run` does) isn't preempted.

Waiting that can't end, because every task is waiting (for a task, a channel
or a send to be received; a task waiting for itself, say), stops the program:
`panic: all tasks are asleep: deadlock`. A panic in a task stops the program,
as anywhere, unless the function it belongs to runs under a
[catch](panics.md#tasks). Its backtrace is the task's own calls, from the call `spawn`
made (`spawn fetch`), then under `spawned at:` the calls the spawning task was
in when it spawned it, and so on up to the program's first task.

A module-level variable is worked out at its first use, as without tasks
(see [Module-level variables](types.md#module-level-variables)). When its initializer waits and another task
uses the variable meanwhile, that task waits for the value rather than work
it out again.

Each task has 8 MB of stack, as the program's first thread has, reserved as
address space and used only as far as the task goes, with a guard page below
it: a recursion too deep for it stops the program, as on the first thread. A
switch from one task to another costs about 50 ns, and starting a task about
1 µs: the stacks of tasks that have ended are kept for new ones.

## What isn't built yet

Tasks run on one thread; using several cores is
[step 2](concurrency.md#building-it).
