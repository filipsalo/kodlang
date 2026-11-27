---
icon: lucide/regex
---

# Regular expressions

`stdlib/regex.kod` finds text by pattern. Its syntax is RE2's, which Go's
`regexp` and Rust's `regex` share, and it runs in time linear in the text
whatever the pattern: there is no backtracking, so no pattern and input make
it slow, and so no backreferences or lookaround, which need backtracking.

```kod
import "regex"

func main() -> int64 or Error {
    let date = try regex.compile("(?P<year>\\d{4})-(?P<month>\\d{2})-(?P<day>\\d{2})")
    let Some(m) = date.find("due 2026-11-27, paid later") else { return 1 }
    print(m.text())                     // 2026-11-27
    print(m.named("month")? or "")      // 11
    print(date.replace_all("2026-11-27", with: "$day/$month/$year"))   // 27/11/2026
    return 0
}
```

A Kod string drops a backslash it doesn't know (`"\d"` is `""`), so a pattern
writes each backslash twice: `"\\d+"` is the pattern `\d+`.

## Compiling

`regex.compile(pattern)` gives a `Regex`, or a `RegexError` for a pattern that
isn't one:

```kod
type RegexError = struct {
    message: str
    offset: int64    // byte offset in the pattern
}
```

Its `to_str()` is `regex: <message> at offset <offset>`, such as
`regex: missing closing ) at offset 0`. Compile a pattern once and use it many
times; a `Regex` doesn't change as it is used, so tasks can share one.

## Finding

| Method | Gives |
|--------|-------|
| `r.matches(s)` | whether the pattern matches anywhere in `s` |
| `r.find(s, from = 0)` | the first match at or after byte `from`, as a `Match?` |
| `r.find_all(s)` | every match, left to right, none overlapping, as `[Match]` |
| `r.full_match(s)` | a match of all of `s`, as a `Match?` |
| `r.replace_all(s, with: t)` | `s` with each match replaced by `t`, in which `$1` or `${1}` is group 1's text, `$name` or `${name}` a named group's, `$0` the whole match and `$$` a `$`; a name runs as far as letters, digits and `_` go, so `$1x` is the group named `1x` (none: empty) and `${1}x` is group 1 then `x` |
| `r.replace_with(s, f)` | `s` with each match `m` replaced by `f(m)`, a `func(Match) -> str` |
| `r.split(s)` | the text between matches, as `[str]` |
| `r.group_count()` | how many capturing groups the pattern has |
| `r.group_names()` | the name of each group, `""` for one without; `[0]` is the whole match's |

When several matches start at the same place, the one taken is the one a
backtracking engine would find first: alternatives are tried left to right,
`*`, `+`, `?` and `{n,m}` take as much as they can and their lazy forms (`*?`,
...) as little. `find_all`, `replace_all` and `split` go on after each match;
an empty match right after the previous one is skipped, so `a*` in `"baa"`
matches at 0 (empty), then `aa`.

A `Match` holds where it is in the text it came from:

| Field or method | Gives |
|-----------------|-------|
| `m.start`, `m.end` | the byte offsets of the whole match |
| `m.text()` | the matched text |
| `m.group(i)` | group `i`'s text, `str?`: `none` when the group took no part in the match |
| `m.named(name)` | the named group's text, `str?` |
| `m.span(i)` | group `i`'s byte offsets, `(int64, int64)?` |

Offsets are bytes, as Kod's string indexes are, and always at the start of a
character.

## Syntax

The pattern and the text are UTF-8; `.` and a class each match one character
(a code point), and a byte that isn't valid UTF-8 counts as a character of
its own that only `.` and negated classes match.

| Pattern | Matches |
|---------|---------|
| `x` | the character `x` |
| `.` | any character but `\n`; any with the `s` flag |
| `[abc]`, `[a-z]`, `[^a-z]` | one of the characters, one in the range, one not in it; `\d`, `\w`, `\s` and the escapes below work inside |
| `\d`, `\w`, `\s` | an ASCII digit; letter, digit or `_`; whitespace (` `, `\t`, `\n`, `\v`, `\f`, `\r`) |
| `\D`, `\W`, `\S` | any character the lower-case one doesn't match |
| `\n`, `\t`, `\r`, `\f`, `\v`, `\0` | newline, tab, return, form feed, vertical tab, NUL |
| `\x41`, `\x{263a}` | the character with that code point |
| `\.`, `\\`, `\(` ... | the punctuation character itself |
| `xy` | `x` then `y` |
| <code>x&#124;y</code> | `x` or `y`, `x` first |
| `x*`, `x+`, `x?` | zero or more, one or more, zero or one `x`, as many as can be |
| `x{n}`, `x{n,}`, `x{n,m}` | exactly `n`, at least `n`, `n` to `m` `x`s; `n` and `m` at most 1000 |
| `x*?`, `x+?`, `x??`, `x{n,m}?` ... | the same, as few as can be |
| `(x)` | a group, which captures what it matches, numbered from 1 by its `(` |
| `(?P<name>x)`, `(?<name>x)` | a group named `name` |
| `(?:x)` | a group that doesn't capture |
| `^`, `$` | the start and end of the text; of a line with the `m` flag |
| `\A`, `\z` | the start and end of the text, always |
| `\b`, `\B` | an ASCII word boundary, and anywhere else |
| `(?flags)`, `(?flags:x)` | flags from here to the end of the group, or for `x` only: `i` case-insensitive, `m` multi-line, `s` `.` matches `\n`, and `-` before those to turn off |

The `i` flag folds ASCII letters only (`(?i)é` doesn't match `É`). There are no
Unicode classes (`\p{L}`), backreferences or lookaround.

## Speed

Matching keeps every way the pattern could still match as it reads the text,
each step at most once per character (a Pike VM), so the time is linear in
the text times the pattern's size: `(a|aa)*b` on 40 `a`s, which a
backtracking engine would take hours over, takes a millisecond. A pattern
that starts with a literal string skips ahead with a search for it.

Finding `\w+@\w+\.com` 13,000 times in a megabyte takes about 75 ms, and
`(a|b)*c` 26,000 times about 100 ms; Go's `regexp` takes 32 and 35.

`stdlib/regex_test.kod` checks the matches, groups, replacements and splits
of some 1,200 cases against what Go's `regexp` gives
(`stdlib/testdata/regex_cases.go` writes them).
