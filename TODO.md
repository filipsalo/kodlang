# TODO

For very-specific locations, prefer a `TODO:` comment in the code
over a line here. This file collects work that doesn't have a single
pinpoint location, or where the locus might move.

## Parser

- [ ] The parser's `expect()` records a `ParseError`, advances past the bad token and
      keeps going, so one mistake can report several errors. Could do error recovery /
      synchronization next.

## Build process

- [ ] Track which module-level names are actually accessed and skip
      compiling unreachable functions.
