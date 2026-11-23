---
icon: lucide/git-branch
---

# Tasks

A **task** is a call that runs on a stack of its own, taking turns with the
others on the program's one thread: one runs until it waits or gives way,
then the next ready one runs. Nothing is shared between threads, so there are
no data races. [Concurrency (design)](concurrency.md) is the plan this is the
start of; what is below is what is built.

<!-- kod:
func fetch_user(anon id: int64) -> str {
    return f"user {id}"
}
func fetch_orders(anon id: int64) -> int64 {
    return id * 2
}
-->
```kod
import "tasks"

let user = tasks.start(func() -> str { return fetch_user(7) })
let orders = tasks.start(func() -> int64 { return fetch_orders(7) })
print(user.wait())      // user 7
print(orders.wait())    // 14
```

| | |
|---|---|
| `tasks.start(body: func() -> T) -> Task[T]` | runs `body` as a new task, which starts the next time this one waits or gives way |
| `tasks.start_none(body: func() -> none) -> NoneTask` | the same for a body that gives back nothing; its `wait()` gives back nothing too |
| `task.wait() -> T` | what `body` gave back, once the task has ended; until then this task waits |
| `tasks.give_way()` | lets the tasks that are ready run, then goes on |

A task's result can be waited for any number of times, by any task. Tasks run
in the order they became ready: a new one after those already waiting to run,
and one that gives way after the others.

Waiting for a task that can't end, because every task is waiting (a task
waiting for itself, say), stops the program:
`panic: all tasks are asleep: deadlock`.

A program that ends ends its tasks too, finished or not. A panic in a task
stops the program, as anywhere.

Each task has 8 MB of stack, as the program's first thread has, reserved as
address space and used only as far as the task goes, with a guard page below
it: a recursion too deep for it stops the program, as on the first thread.

## What isn't built yet

The `spawn` syntax, a function waiting for its tasks at its end, cancellation,
channels, `select`, generators, and tasks waiting for I/O instead of blocking
the thread: these come in that order, as
[Concurrency (design)](concurrency.md#building-it) lays out. Until the I/O
part lands, reading a socket or sleeping holds up every task.
