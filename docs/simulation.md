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
| `sim.run(count: 100, from: 0, start: none, body: f)` | runs `f`, a `func() -> none`, under the seeds `from` to `from + count - 1`, one after another; when one fails it panics, saying the seed and the panic it had |
| `sim.replay(seed, start: none, body: f)` | runs `f` under `seed` alone, letting its panic through as it is: for looking at a failure `run` found |
| `sim.simulating()` | whether code runs under a simulation |
| `sim.seed()` | the seed of the run under way |
| `sim.digest()` | a number standing for every choice the last run made; two runs with one seed give the same |

`KOD_SIM_SEEDS=n` in the environment makes every `sim.run` take `n` seeds, for
a longer hunt now and then.

## What is simulated

- **Which task runs.** When several tasks are ready, the seed picks one; a task
  that reads or writes a connection may give way to another first. Tasks
  aren't preempted in the middle of a loop under a simulation, so a task runs
  until it waits or gives way.
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
- **Deadlock.** When every task waits and nothing it waits for can come, the
  run fails with `simulation: every task waits, and nothing can wake one`,
  where outside a simulation the program would hang.

## What isn't

Files, child processes, `posix.poll` and the standard streams are the real
ones, and so is what `crypto/random` gives; a body that waits for those, or
for another program, isn't repeatable. A task that loops without waiting is
never stopped. Tasks must not outlive the body: those it spawned are waited
for when it ends, as at any function's end.
