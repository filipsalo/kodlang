---
icon: lucide/dice-5
---

# Simulation

A bug between tasks often shows up once in a hundred runs, and only when the
machine is busy. `stdlib/sim.kod` runs a test's body many times, each under a
simulation decided by a seed: which ready task runs next, how much of a write
goes at once, and what the clock says. A run that fails says its seed, and the
same seed gives the same run again, every time, so the bug can be looked at
until it is understood.

```kod
import "net/tcp"
import "sim"

func echo(anon l: tcp.Listener) -> none {
    let conn = must l.accept()
    let got = must conn.read(100)
    must conn.write_all(got)
    must conn.close()
}

test "an echo server, simulated" {
    sim.run(count: 100, body: func() {
        let l = must tcp.listen("127.0.0.1", port: 7000)
        spawn echo(l)
        let c = must tcp.connect("127.0.0.1", port: 7000)
        must c.write_str("hi")
        assert kod_bytes_to_str(must c.read(100)) == "hi"
        must c.close()
        must l.close()
    })
}
```

| Function | Does |
|----------|------|
| `sim.run(count: 100, from: 0, start: none, body: f, restart: none, disk_faults: false)` | runs `f`, a `func() -> none`, under the seeds `from` to `from + count - 1`, one after another; when one fails it panics, saying the seed and the panic it had. With `restart:`, a second `func() -> none`, each run [crashes](#crashes) and `restart` runs after; with `disk_faults: true`, the disk [fails](#disk-faults) under some seeds |
| `sim.replay(seed, start: none, body: f, restart: none, disk_faults: false)` | runs `f` under `seed` alone, letting its panic through as it is: for looking at a failure `run` found |
| `sim.crashed()` | in `restart`: whether the crash stopped the body before it ended |
| `sim.faulted()` | whether the disk has failed a call in this run |
| `sim.simulating()` | whether code runs under a simulation |
| `sim.seed()` | the seed of the run under way |
| `sim.digest()` | a number standing for every choice the last run made; two runs with one seed give the same |

`KOD_SIM_SEEDS=n` in the environment makes every `sim.run` take `n` seeds, for
a longer hunt now and then.

## What is simulated

- **Which task runs.** When several tasks are ready, the seed picks one; a task
  that reads or writes a connection may give way to another first. Under half
  the seeds the pick goes by priority instead, as in PCT (probabilistic
  concurrency testing): each task has one the seed draws, the highest ready
  one runs, and a task that is preempted drops below all the others. So one
  task can run on while another, ready, waits its turn, as on a busy
  machine.
- **Where a task is preempted.** As outside a simulation, a task that runs
  without waiting gives way at the top of a loop iteration or a function call
  ([Preemption](tasks.md#preemption)), but after a number of those that the
  seed draws each time, as likely a handful as thousands, rather than every
  10 ms. A check that comes right after a store to what other tasks can
  reach preempts sooner: under some seeds the first such check, under others
  one of the next hundred. What counts is a module-level variable, and a
  field of a `shared struct` that was handed to another task: passed to a
  function `spawn` runs, or captured by one, or sent on a channel, or
  reachable from such a value. A struct a task made and kept to itself
  doesn't count, and only the last store before a check is looked at (with
  eight marks, one per store site in turn, instead of one, the seeds that
  find the TLS bug below were the same 52). So a race between two tasks that
  read and write the same data without waiting in between shows up under
  some seed too, and that
  seed preempts at the same places again. The store itself is never cut in
  two, and nothing is preempted where it couldn't be outside a simulation.
- **Time.** `time.monotonic_ns()`, `time.unix_ns()` and `time.now()` read a
  clock that stands still while tasks run, its calendar starting at `start`
  (a `time.Time`), or 2026-01-01 00:00:00 UTC. A test that checks a
  certificate made today passes `start: time.now()`, taken before the run, so
  that the certificate is in date; the run is then the same for that start. When every task waits and one of them waits for a time (`time.sleep`, a
  timeout), the clock jumps to the earliest such time. A test of a 30-second
  timeout takes no time at all.
- **The network.** `tcp.listen` and `tcp.connect` to `127.0.0.1` or `localhost`
  make connections within the program, on any port, whatever is running on the
  machine. Each connection is a pair of Unix-domain sockets, with small
  buffers, so a write of a few kilobytes waits for the other end to read; a
  write goes in pieces of a size the seed picks. Connecting to a port nothing
  listens on is `ConnectionRefused`; to another host, an error.
- **The disk.** Files and directories a run makes, writes, renames or removes
  are the simulation's, in memory, and gone when the run ends; a path the
  run hasn't changed is read from the real disk, so a test can read its
  certificates and data files. What `posix` and `io` do with files is
  simulated: opening, reading, writing, syncing, renaming, listing, `stat`.
  Without `restart:` nothing is lost; with it, see [Crashes](#crashes).
- **Randomness.** `crypto/random` gives bytes that come from the seed, so the
  keys and nonces a run makes, and the work done with them, are the same
  each time.
- **Deadlock.** When every task waits and nothing it waits for can come, the
  run fails with `simulation: every task waits, and nothing can wake one`,
  where outside a simulation the program would hang.

## Crashes

With `restart:`, the seed picks a point where the machine loses its power:
before one of the body's changes to the disk (a write, a sync, a new file, a
rename, a removal), under some seeds one of the first few, under others one
of the first thousands, and under a quarter of them none, so that the body
ends first. Every task stops there, never to run again, and the disk loses
what wasn't on it yet:

- **Data.** What was written to a file since its last `sync` is lost, or
  kept, in pieces of 512 bytes: under some seeds all of it is lost, under
  others none of it (the program crashed, not the machine), and under the
  rest some pieces and not others, whatever order they were written in. A
  piece kept past the file's synced end leaves zeros before it where a piece
  was lost. A `truncate` since the sync is kept or lost as a piece is.
- **Names.** Files and directories made, renamed and removed since the last
  `sync_dir` are kept in the order they were made: all of those up to a
  point the seed picks, and none after. A `sync_dir` keeps every change made
  before it, in any directory, as a journaling file system does. `f.sync()`
  keeps a new file's contents but not its name.

Then `restart` runs, as the program would when the machine came back: what
the crash left on the disk, a new network with no connection open, and the
clock where it was. Values in memory, such as one the body and `restart`
both capture, are kept, which is how a test says what the body was told was
kept; what a module-level variable holds, the program's own included, is too,
which a real restart wouldn't keep.

```kod
import "posix"
import "posix" { Fd }
import "sim"

// Appends `line`, and is done once it is on the disk.
func log(anon f: Fd, anon line: str) -> none or Error {
    try f.write_all(kod_str_to_bytes(line + "\n"))
    try f.sync()
}

type Kept = shared struct {
    lines: [str] = []
}

test "a log keeps what it said it kept" {
    let kept = Kept()
    sim.run(count: 100, body: func() {
        kept.lines = []
        must posix.make_dir("db")
        must posix.sync_dir(".")
        let f = must posix.open_rw("db/log")
        must posix.sync_dir("db")
        for i in 0..20 {
            must log(f, f"line {i}")
            kept.lines += [f"line {i}"]
        }
    }, restart: func() {
        // Before its first line, the log may not be there at all.
        if len(kept.lines) == 0 {
            return
        }
        let text = kod_bytes_to_str(must (must posix.open_rw("db/log")).read_all())
        for line in kept.lines {
            assert text.contains(line + "\n")
        }
    })
}
```

Without the `f.sync()`, or without either `sync_dir`, some seeds lose a line
the body was told was kept, and the run fails, naming its seed. Of 200
seeds, 115 find a missing `f.sync()` there and 72 the missing `sync_dir`s;
replacing a file by a rename, 77 find a missing sync of the new file and 98
a missing `sync_dir` after the rename.

The tasks a crash stops never let go of what they held: a few kilobytes a
run stay allocated until the program ends. A body the crash stops may have
failed for it, so how it ended doesn't matter: `restart` runs either way.
Under a simulation, renaming a directory that is on the real disk fails with
`InvalidInput`.

## Disk faults

With `disk_faults: true`, under three seeds in four the disk fails once, or
fills up, at a point the seed picks:

- **A full disk.** From one of the body's writes on, the disk has no more
  room than its files then take: a write that would make them longer
  writes what fits and fails with `StorageFull` once nothing does, and so
  does a `truncate` that lengthens a file. Removing or cutting short a file
  makes room again.
- **A write that fails.** One write fails with an I/O error (`EIO`, kind
  `Other`), having written nothing.
- **A sync that fails.** One `f.sync()` fails with an I/O error, and what
  was written to the file since its last sync never reaches the disk: the
  program still reads it back, but the next `sync` doesn't write it and a
  crash loses it, as on Linux, where a sync that failed has given up on the
  pages it was to write. A program that tries the sync again and takes its
  success as the data's is wrong; one that stops, or writes it all again,
  is right.
- **A read that fails.** One read fails with an I/O error.

Which call fails is counted among those of its kind: one of the first few
under some seeds, one of the first hundreds under others, in the body; a
fault the body doesn't come to doesn't come in `restart`, though a disk the
body filled is still full there.

A program may well stop when its disk fails, as a database should when a
sync fails. With `restart:`, a body that ends with a panic after a fault
isn't a failure: the power is cut there, as if it had crashed, and
`restart` checks what is left. Without `restart:` it is, and the body has to
cope with the error itself.

```kod
import "posix"
import "posix" { Fd }
import "sim"

type Kept = shared struct {
    lines: [str] = []
}

// Appends `line`, and is done once it is on the disk; a sync that fails
// stops the program, since what it was to write may be gone.
func log(anon f: Fd, anon line: str) -> none or Error {
    try f.write_all(kod_str_to_bytes(line + "\n"))
    if f.sync() is Err(e) {
        panic(f"the log can't be kept: {e.to_str()}")
    }
}

test "a log keeps what it said it kept, whatever the disk does" {
    let kept = Kept()
    sim.run(count: 100, body: func() {
        kept.lines = []
        let f = must posix.create("log")
        must f.sync()
        must posix.sync_dir(".")
        for i in 0..20 {
            // A full disk or a write that fails: the line isn't kept.
            if log(f, f"line {i}") is Ok(_) {
                kept.lines += [f"line {i}"]
            }
        }
    }, restart: func() {
        if len(kept.lines) == 0 {
            return
        }
        let text = kod_bytes_to_str(must (must posix.open_read("log")).read_all())
        for line in kept.lines {
            assert text.contains(line + "\n")
        }
    }, disk_faults: true)
}
```

Had `log` tried the sync again, a seed whose sync fails would find a line
missing that the body was told was kept: 13 seeds of 200 do (a quarter of
the faults are syncs, and the failing one has to be among the log's 21).

## What isn't

Child processes, `posix.poll` and the standard streams are the real ones,
and so is a file opened only for reading that the run hasn't changed; a body
that waits for those, or for another program, isn't repeatable. The
simulated disk fails a call only as [Disk faults](#disk-faults) says: one
fault a run, and never a slow disk or a sync that silently does nothing.
Tasks must not outlive the body: those it spawned are waited for when it
ends, as at any function's end.

With a bug fixed on 2026-11-27 put back (a TLS reader that sent records a
writer had queued but not yet sent, while the writer had been preempted
between the two), 52 of 200 seeds of a connection writing and reading at
once deadlock. The window is a few checks among hundreds of thousands: none
of 200 seeds found it without the preemption after stores, nor without
priorities, and 32 did while stores to every shared struct counted.

A seed gives the same run whether `run` comes to it after other seeds or
`replay` runs it alone, as long as the body doesn't depend on what earlier
runs left behind: a cache the program fills, say, makes the run that fills it
do more work, so it is preempted at other places. A module-level variable is
the exception: the work its initializer does isn't counted, so it doesn't
matter which run worked it out.
