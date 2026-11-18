---
icon: lucide/gauge
---

# Profiling

`stdlib/kod/profiling.kod` is a sampling profiler for finding where a program
spends its time. It stops the program at a fixed interval of CPU time, notes
where it was, and at the end prints which functions it was caught in most:

```kod
import "kod/profiling"

func main() -> int64 {
    profiling.start(interval_us: 1000)      // a sample every 1 ms of CPU time
    run_the_slow_part()
    profiling.stop()
    profiling.report()
    return 0
}
```

```
profile: 412 samples
  64%  264 samples  parse_line (app.kod:52)
  20%  84 samples  checksum (app.kod:107)
  8%  35 samples  <unresolved>
  7%  29 samples  parse_line (app.kod:49)
```

Each row is a place the program was caught: the function, the line in it, and
the share of samples taken there. A function busy on several lines has a row
for each. `<unresolved>` gathers the samples taken outside Kod code, in the C
runtime or the system's libraries.

| Function | Meaning |
|----------|---------|
| `start(interval_us:)` | empty the samples and take one every `interval_us` microseconds of the program's CPU time; time spent waiting, sleeping or reading doesn't count |
| `stop()` | take no more; the samples stay |
| `report()` | print the summary above |
| `n_samples()` | how many samples there are |
| `depth(sample)` | how many addresses sample `sample` has, 0 for one there isn't |
| `frame(sample, at:)` | address `at` of the sample: 0 is where the program was, then the return addresses up the stack, its callers; 0 past the end |

## Reading it

- **Self time only.** A sample counts toward the function the program was in,
  not the ones that called it. A function that only calls slow ones shows
  little; to find its callers, look at the sample's other frames with
  `frame` and resolve them with `kod/inspect`, which gives `none` for an
  address outside Kod code, such as `main`'s caller:

  ```kod
  import "kod/inspect"

  for i in 0..profiling.n_samples() {
      if inspect.resolve(addr: profiling.frame(i, at: 1)) is Some(f) {
          print(f.name)                     // who called the function sampled
      }
  }
  ```

- **Inlined functions.** A small function the compiler compiles into its
  caller shows as the caller.
- **The interval.** 1 ms suits a run of a few seconds. A shorter one finds
  more in a short run, and costs a little more while the program runs.
- **Up to 4096 samples**, each of up to 32 addresses. Past that, `start`'s
  timer keeps running but no more samples are kept, so the summary covers
  the beginning of a long run: start it just before the part to measure.

For a whole program, macOS's own `sample` command (`sample <pid> 5`) needs no
change to it, and reports call trees as well.

The handler that takes the samples is a Kod function the system calls on
`SIGPROF` (see [Callbacks](unsafe.md#callbacks)); it only reads registers and
memory and stores addresses, so it is safe to run at any point in the program.
