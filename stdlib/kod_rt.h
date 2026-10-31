// What a C file that a Kod module names with `// kod:cc` can rely on from the
// runtime (docs/modules.md, "Link inputs"). `CFLAGS` of link.cfg has
// `-I stdlib`, so `#include "kod_rt.h"` finds it. runtime.c includes it too,
// so the types here are the ones the runtime and the generated code use.
#ifndef KOD_RT_H
#define KOD_RT_H

#include <stdint.h>
#include <string.h>

// A Kod `str` value is a pointer to one of these. `buf` points at a
// byte buffer of `len` bytes plus an explicit NUL terminator (kept
// for cheap libc interop — pass `buf` directly into puts/fopen-style
// APIs). All str-handling externs return / accept `KodStr *`; the
// codegen passes the struct pointer in `x0` without unwrapping.
typedef struct {
    char *buf;
    int64_t len;
} KodStr;

// A Kod `[T]`: `ptr` points at `len` 8-byte slots, with room for `cap`.
typedef struct {
    void *ptr;
    int64_t len;
    int64_t cap;
} KodArray;

// Memory that is never freed: everything Kod allocates comes from here.
void *arena_alloc(int64_t size);

// Prints `panic: ` and the message to stderr, with a backtrace, and exits 1.
__attribute__((noreturn)) void kod_panic(KodStr *msg);

// Allocate a fresh KodStr plus a `len`-byte NUL-terminated buffer in
// a single arena allocation. Caller fills `buf` before returning.
static inline KodStr *kod_str_new(int64_t len) {
    int64_t header = (int64_t)sizeof(KodStr);
    // Keep the byte buffer 8-aligned for the simple memcpy-into-it
    // paths even though no field needs that alignment.
    int64_t total = header + len + 1;
    char *block = (char *)arena_alloc(total);
    KodStr *s = (KodStr *)block;
    s->buf = block + header;
    s->len = len;
    s->buf[len] = '\0';
    return s;
}

// A Kod `str` holding a copy of the `n` bytes at `p`, which may include NUL
// bytes (unlike a copy made with strlen).
static inline KodStr *kod_str_from_bytes(const char *p, int64_t n) {
    KodStr *s = kod_str_new(n);
    memcpy(s->buf, p, (size_t)n);
    return s;
}

#endif
