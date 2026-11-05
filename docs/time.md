---
icon: lucide/timer
---

# Time

`stdlib/time.kod` has two clocks, a `Duration` type, `sleep`, and a `Time` type
for timestamps.

```kod
import "time"
import "time" { Duration }

let started = time.monotonic_ns()
time.sleep(Duration(ms: 250))
let took = Duration(ns: time.monotonic_ns() - started)
print(took.to_str())                       // 250.31ms
```

## Clocks

| Function | Returns |
|---|---|
| `monotonic_ns()` | nanoseconds from an unspecified origin that never go backwards; only differences mean anything. Use it to time things. |
| `unix_ns()` | nanoseconds since 1970-01-01 UTC by the wall clock. It can jump if the system clock is adjusted, so it is not for measuring elapsed time. |

Both are plain `int64`, which holds about 292 years of nanoseconds.

## Duration

A `Duration` is a length of time, kept as nanoseconds in an `int64` (`ns`).
Make one by naming the units you want; they add up, and each defaults to 0:

```kod
Duration(seconds: 5)
Duration(ms: 250)
Duration(minutes: 1, seconds: 30)
Duration()                       // zero
```

The units are `hours`, `minutes`, `seconds`, `ms`, `us` and `ns`, and labels go in
that order, largest first, as in `Duration(seconds: 1, ms: 500)`. `Duration` is
a struct with a [custom constructor](structs.md#custom-constructors), so
`Duration(...)` is the only way to build one from units, and the units are
labels, not types: `Duration(seconds: 90)` and `Duration(minutes: 1, seconds: 30)`
are equal.

### Arithmetic and comparison

`Duration` defines the [operators](structs.md#operators):

```kod
let a = Duration(seconds: 2)
let b = Duration(ms: 500)
a + b                  // 2.5s
a - b                  // 1.5s
a * 3                  // 6s
3 * a                  // 6s
a / 4                  // 500ms
-a                     // -2s
a > b                  // true
a == Duration(ms: 2000)   // true
```

A duration times or divided by an `int64` is a duration, and `Duration` has
no `Duration * Duration` or `Duration / Duration`: use `a.ns / b.ns` for a
ratio.

### Methods

| Method | Meaning |
|---|---|
| `as_ms()` | the whole milliseconds in it, truncated toward zero |
| `as_seconds()` | the whole seconds in it, truncated toward zero |
| `as_hours()` | the whole hours in it, truncated toward zero |
| `as_days()` | the whole 24-hour days in it, truncated toward zero |
| `ceil_ms()` | milliseconds, rounded up for a positive duration, so that a short timeout never becomes 0 (which most timeouts treat as none) |
| `to_str()` | a short reading, such as `1h2m3s`, `1.5s`, `250ms`, `12.5us`, `40ns` or `0s` |

`to_str` writes hours and minutes only when the duration has them (a duration of
an hour or more always shows minutes and seconds, as in `1h0m0s`), seconds with
a fraction when it has one, and below a second the largest unit that keeps the
number at 1 or more. A negative duration starts with `-`.

## Sleeping

```kod
func sleep(anon d: Duration) -> none
```

waits at least `d`, to the resolution of the system clock, and a signal doesn't
cut it short. A zero or negative duration returns at once.

## Timestamps

A `Time` is a moment: whole `seconds` since 1970-01-01 UTC, negative before it,
and `nanos` from 0 to 999999999 on top. It has no time zone of its own, and
reads as UTC.

```kod
import "time"

let created = time.parse("2026-01-02T03:04:05+01:00")? or time.now()
print(created.to_str())                       // 2026-01-02T02:04:05Z
print(created.utc().year)                     // 2026
print((time.now() - created).as_days())       // how many days ago
```

| Function | Returns |
|---|---|
| `now()` | the wall clock's time |
| `parse(s)` | the `Time` of an RFC 3339 timestamp, or `none` if `s` isn't one |
| `parse_date(s)` | midnight UTC of a `YYYY-MM-DD` date, or `none` if `s` isn't one |

`parse` takes what APIs send: `2026-01-02T03:04:05Z`, with a fraction of a second
as in `05.25Z`, and an offset as in `05+01:00`. A `t` and a `z` may be lowercase,
as RFC 3339 allows. Digits past nanoseconds are dropped. It checks the calendar, so
`2026-02-29` is `none`. A leap second, `:60`, is read as the first second after it,
since a `Time` has no way to hold one.

| Method | Meaning |
|---|---|
| `t + d` | the `Time` a `Duration` later |
| `a - b` | the `Duration` from `b` to `a`, which wraps past about 292 years, as a `Duration` does |
| `a == b`, `a < b` and the like | whether they're the same moment, or which comes first |
| `utc()` | a `Utc` with `year`, `month` (1 to 12), `day`, `hour`, `minute` and `second` |
| `to_str()` | RFC 3339 in UTC, with a fraction only if there is one, as in `2026-01-02T02:04:05.25Z` |

## Durations in other modules

The timeouts and deadlines of [`net/tcp`, `net/tls`](io.md#tcp) and the
[HTTP client](http.md) are `Duration`s: `Client(deadline: Duration(seconds: 15))`.
