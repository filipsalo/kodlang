#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <unistd.h>

#include "kod_rt.h"

#if defined(__ARM_FEATURE_CRC32)
#include <arm_acle.h>
#endif


// Defined in stdlib/kod/inspect.kod. Both panic handlers call it
// inline with `__builtin_frame_address(0)` (NOT through a wrapper —
// see the longer note where the asm-label declaration lives).
extern void kod_inspect_print_backtrace_from(int64_t fp)
    __asm__("$kod$inspect$print_backtrace_from");

// KodStr and KodArray, the layout of a Kod `str` and `[T]`, are in kod_rt.h,
// which C files that Kod modules name include too.

// Allocate a fresh KodStr plus a `len`-byte NUL-terminated buffer in
// a single allocation. Caller fills `buf` before returning.
static KodStr *kod_str_alloc(int64_t len) {
    return kod_str_new(len);
}

// Build a KodStr from a NUL-terminated C string (e.g. argv[i]). Copies
// the bytes; cheap enough for the rare libc-boundary case.
KodStr *kod_str_from_cstr(const char *cstr) {
    int64_t len = (int64_t)strlen(cstr);
    KodStr *s = kod_str_alloc(len);
    memcpy(s->buf, cstr, len);
    return s;
}

// Empty Kod string with the right header layout.
static KodStr *kod_empty_str(void) {
    return kod_str_alloc(0);
}

// Called by `must expr` when the expression evaluates to an error.
// `msg` is the result of calling the error's to_str method. Stdout is
// flushed first, so what the program printed comes out before the message
// when both end up in one pipe or log.
void kod_panic(KodStr *msg) {
    fflush(stdout);
    fwrite("panic: ", 1, 7, stderr);
    fwrite(msg->buf, 1, msg->len, stderr);
    fputc('\n', stderr);
    kod_inspect_print_backtrace_from(
        (int64_t)(uintptr_t)__builtin_frame_address(0));
    exit(1);
}

// Backtrace generation lives in kod (stdlib/kod/inspect.kod) — the
// C runtime keeps just the primitives the kod walker needs (raw
// memory reads, c-string lift, section-bounds accessors) plus a
// small wrapper that captures the panic-handler's own fp and hands
// it to the kod entry point.

// Mach-O linker-synthesised bounds for the per-function symbol
// rows the codegen emits via emit_symtab_entry.
extern const char kod_symtab_section_start[]
    __asm__("section$start$__DATA$__kod_symtab");
extern const char kod_symtab_section_end[]
    __asm__("section$end$__DATA$__kod_symtab");

int64_t _inspect_read_i64(int64_t addr) { return *(int64_t *)addr; }
int64_t _inspect_read_i32(int64_t addr) { return *(int32_t *)addr; }
// Used by `inspect.print_backtrace()` (the user-facing zero-arg
// form): __builtin_frame_address(1) is the caller's fp. The kod
// caller's frame is what we want to start walking from — so the
// trace's first row is the user function that called print_backtrace,
// not inspect.print_backtrace itself. `noinline` keeps the wrapper
// frame distinct so fa(1) does the right thing.
__attribute__((noinline)) int64_t _inspect_caller_fp(void) {
    return (int64_t)(uintptr_t)__builtin_frame_address(1);
}
KodStr *_inspect_cstr_to_str(int64_t addr) {
    return kod_str_from_cstr((const char *)addr);
}
int64_t _inspect_symtab_start(void) {
    return (int64_t)(uintptr_t)kod_symtab_section_start;
}
int64_t _inspect_symtab_end(void) {
    return (int64_t)(uintptr_t)kod_symtab_section_end;
}

// Called by the codegen's array-indexing bounds check on a miss.
// Negative indices are already normalised (idx += len) before this
// runs, so any out-of-range value here is genuinely out of bounds.
void kod_index_oob(int64_t idx, int64_t len) {
    fflush(stdout);
    fprintf(stderr,
            "panic: index %lld out of bounds for array of length %lld\n",
            (long long)idx, (long long)len);
    kod_inspect_print_backtrace_from(
        (int64_t)(uintptr_t)__builtin_frame_address(0));
    exit(1);
}

void kod_div_zero(void) {
    fflush(stdout);
    fprintf(stderr, "panic: integer division by zero\n");
    kod_inspect_print_backtrace_from(
        (int64_t)(uintptr_t)__builtin_frame_address(0));
    exit(1);
}

// Print to stderr without exiting. Used by the codegen to surface
// user-facing errors (unknown method, etc.) while continuing to
// scan the rest of the module for additional errors.
void kod_eprint(KodStr *msg) {
    fwrite(msg->buf, 1, msg->len, stderr);
    fputc('\n', stderr);
}

// Kod-side `puts` extern — len-aware, won't fool itself on embedded
// NULs. Trailing newline matches libc puts.
int64_t kod_puts(KodStr *s) {
    fwrite(s->buf, 1, s->len, stdout);
    fputc('\n', stdout);
    return 0;
}


// The builtin `fail`. The test runner is Kod (stdlib/testing.kod), and a test
// program's `_main` defines this to call it; anywhere else there is no test to
// fail, so it panics like `assert` outside a test.
__attribute__((weak)) void kod_test_fail(KodStr *msg) {
    kod_panic(msg);
}

static int64_t clamp_slice(int64_t len, int64_t *start, int64_t end) {
    if (*start < 0) *start = 0;
    if (*start > len) *start = len;
    if (end > len) end = len;
    return end > *start ? end - *start : 0;
}

KodStr *kod_str_slice(KodStr *s, int64_t start, int64_t end) {
    int64_t len = clamp_slice(s->len, &start, end);
    KodStr *out = kod_str_alloc(len);
    memcpy(out->buf, s->buf + start, len);
    return out;
}

KodStr *kod_str_concat(KodStr *a, KodStr *b) {
    KodStr *out = kod_str_alloc(a->len + b->len);
    memcpy(out->buf, a->buf, a->len);
    memcpy(out->buf + a->len, b->buf, b->len);
    return out;
}

// Lexicographic compare on the byte buffers, with length-difference
// tiebreaker (matches memcmp / strcmp semantics). Replaces the
// previous direct `_strcmp` call inside compile_str_eq, which would
// have read past struct headers under the new layout.
int64_t kod_str_cmp(KodStr *a, KodStr *b) {
    int64_t min_len = a->len < b->len ? a->len : b->len;
    int rc = memcmp(a->buf, b->buf, (size_t)min_len);
    if (rc != 0) return rc;
    return a->len - b->len;
}

// A growable byte buffer behind the stdlib `StrBuilder` and the str methods
// that build strings. Kod holds it as an int64 handle. The buffer doubles
// when full, so n appended bytes cost
// O(n) and leave under 2n bytes of abandoned buffers behind.
typedef struct {
    char *buf;
    int64_t len;
    int64_t cap;
} KodStrBuilder;

int64_t kod_sb_new(void) {
    KodStrBuilder *sb = (KodStrBuilder *)rc_alloc(sizeof(KodStrBuilder), 1);
    sb->cap = 32;
    sb->len = 0;
    sb->buf = (char *)rc_alloc_raw(sb->cap, 0);
    return (int64_t)sb;
}

static void kod_sb_reserve(KodStrBuilder *sb, int64_t extra) {
    if (extra > INT64_MAX / 4 - sb->len) {
        kod_panic(kod_str_from_cstr("string builder is too large"));
    }
    int64_t need = sb->len + extra;
    if (need <= sb->cap) return;
    int64_t new_cap = sb->cap;
    while (new_cap < need) new_cap *= 2;
    char *new_buf = (char *)rc_alloc_raw(new_cap, 0);
    memcpy(new_buf, sb->buf, (size_t)sb->len);
    rc_release_c(sb->buf);
    sb->buf = new_buf;
    sb->cap = new_cap;
}

void kod_sb_append(int64_t handle, KodStr *s) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    kod_sb_reserve(sb, s->len);
    memcpy(sb->buf + sb->len, s->buf, (size_t)s->len);
    sb->len += s->len;
}

void kod_sb_append_byte(int64_t handle, int64_t b) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    kod_sb_reserve(sb, 1);
    sb->buf[sb->len++] = (char)(b & 0xff);
}

int64_t kod_sb_len(int64_t handle) {
    return ((KodStrBuilder *)handle)->len;
}

void kod_sb_clear(int64_t handle) {
    ((KodStrBuilder *)handle)->len = 0;
}

KodStr *kod_sb_to_str(int64_t handle) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    return kod_str_from_bytes(sb->buf, sb->len);
}

// CRC-32 (the gzip polynomial) of n bytes, continuing from `crc`, the
// running state without gzip's final xor. Eight bytes per instruction where
// the CPU has the CRC instructions, a byte at a time otherwise.
static uint32_t kod_crc32_run(uint32_t crc, const unsigned char *p, int64_t n) {
#if defined(__ARM_FEATURE_CRC32)
    for (; n >= 8; p += 8, n -= 8) {
        uint64_t w;
        memcpy(&w, p, 8);
        crc = __crc32d(crc, w);
    }
    for (; n > 0; p++, n--) crc = __crc32b(crc, *p);
#else
    for (; n > 0; p++, n--) {
        crc ^= *p;
        for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
    }
#endif
    return crc;
}

// Adler-32 of n bytes, continuing from `sum` (b << 16 | a). 5552 bytes is
// the most that can be added before the sums could overflow 32 bits.
static uint32_t kod_adler32_run(uint32_t sum, const unsigned char *p, int64_t n) {
    uint32_t a = sum & 0xffff, b = sum >> 16;
    while (n > 0) {
        int64_t chunk = n < 5552 ? n : 5552;
        n -= chunk;
        for (; chunk > 0; p++, chunk--) {
            a += *p;
            b += a;
        }
        a %= 65521;
        b %= 65521;
    }
    return (b << 16) | a;
}

// The range start..end clamped to a buffer of `len` bytes.
static int64_t kod_clamp_range(int64_t len, int64_t *start, int64_t end) {
    if (*start < 0) *start = 0;
    if (end > len) end = len;
    return end > *start ? end - *start : 0;
}

int64_t kod_crc32_bytes(int64_t crc, KodStr *b, int64_t start, int64_t end) {
    int64_t n = kod_clamp_range(b->len, &start, end);
    return kod_crc32_run((uint32_t)crc, (const unsigned char *)b->buf + start, n);
}

int64_t kod_crc32_sb(int64_t crc, int64_t handle, int64_t start, int64_t end) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    int64_t n = kod_clamp_range(sb->len, &start, end);
    return kod_crc32_run((uint32_t)crc, (const unsigned char *)sb->buf + start, n);
}

int64_t kod_adler32_sb(int64_t sum, int64_t handle, int64_t start, int64_t end) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    int64_t n = kod_clamp_range(sb->len, &start, end);
    return kod_adler32_run((uint32_t)sum, (const unsigned char *)sb->buf + start, n);
}

// stdlib/unsafe.kod; its loads, stores, c_int and refs are compiler intrinsics.
// A `bytes` holding a copy of the `n` bytes at `addr`.
KodStr *kod_unsafe_copy_out(int64_t addr, int64_t n) {
    return kod_str_from_bytes((const char *)addr, n < 0 ? 0 : n);
}

// File descriptor I/O for stdlib/posix.kod. The calls return their result and
// leave the reason for a failure in `kod_io_errno()` (0 after a success),
// which Kod reads straight after. Interrupted calls are retried here.
static int64_t g_io_errno;

int64_t kod_io_errno(void) { return g_io_errno; }

void kod_io_set_errno(int64_t err) { g_io_errno = err; }

// Append rhs to lhs, mutating lhs in place when its `cap` is large enough
// and reallocating with exponential growth otherwise. Returns lhs.
//
// Intentional aliasing-semantics change versus the original "always-fresh
// hdr" behavior: callers like `xs += [x]` now observe amortized O(1) per
// append (was O(n), so O(n²) over a build loop). `let b = a; a += [x]`
// will now also append to `b` — but no in-tree caller relied on the old
// copy-on-concat semantics, and pytest + the Kod test suites all pass.
// Slice copy: returns a fresh array with elements [start, end). Every
// element in a Kod array is 8 bytes (pointer-or-int64), so a flat
// memcpy is enough — no per-element rewrap needed. Negative `end - start`
// clamps to a zero-length slice. Explicit range checking is the caller's
// job (the codegen could emit a `len` check; today we don't).
// Pack a Kod `[int64]` (one byte per element, low 8 bits) into a fresh
// Kod bytes buffer of the same length. Useful for builders that
// accumulate bytes as int64s and emit binary output in one shot —
// avoids the quadratic-time pattern of repeatedly concatenating
// one-character buffers.
KodStr *kod_bytes_from_array(void *arr_raw) {
    KodArray *arr = (KodArray *)arr_raw;
    int64_t len = arr->len;
    KodStr *s = kod_str_alloc(len);
    int64_t *src = (int64_t *)arr->ptr;
    for (int64_t i = 0; i < len; i++) {
        s->buf[i] = (char)(src[i] & 0xff);
    }
    return s;
}

// `str` and `bytes` share the same runtime representation (a `KodStr *`);
// these casts are zero-copy. The type system uses them to mark the
// boundary between text and raw-byte handling.
KodStr *kod_str_to_bytes(void *s) { rc_retain_c(s); return (KodStr *)s; }
KodStr *kod_bytes_to_str(void *b) { rc_retain_c(b); return (KodStr *)b; }

// Only reached through a function value: codegen compiles a direct call to
// a bounds check and one load. Out of range panics with the first missing
// byte's index, as the compiled check does.
int64_t kod_bytes_le64(KodStr *b, int64_t at) {
    if (at < 0 || at >= b->len) kod_index_oob(at, b->len);
    if (b->len - at < 8) kod_index_oob(b->len, b->len);
    uint64_t v;
    memcpy(&v, b->buf + at, 8);
    return (int64_t)v;
}

#define RC_ARRAY_BIT (1ULL << 22)
#define RC_REFS_BIT (1ULL << 21)
static inline int rc_arr_counted(const void *p) { return ((uint64_t)p >> 36) == 0x300; }
static inline int rc_arr_refs(const void *a) {
    return rc_arr_counted(a) && ((((uint32_t *)a)[-1] >> 8) & RC_REFS_BIT);
}
static inline void rc_arr_set_refs(void *a) {
    if (rc_arr_counted(a)) ((uint32_t *)a)[-1] |= (uint32_t)(RC_REFS_BIT << 8);
}
static KodArray *rc_arr_new(int64_t cap, int refs) {
    KodArray *out = (KodArray *)rc_alloc(sizeof(KodArray), (int64_t)(RC_ARRAY_BIT | (refs ? RC_REFS_BIT : 0)));
    out->ptr = rc_alloc_raw(cap > 0 ? cap * 8 : 8, 0);
    out->cap = cap;
    return out;
}
static void rc_arr_retain_all(void **p, int64_t n) {
    for (int64_t i = 0; i < n; i++) rc_retain_c(p[i]);
}

void *kod_array_slice(void *src_raw, int64_t start, int64_t end) {
    KodArray *src = (KodArray *)src_raw;
    int64_t len = clamp_slice(src->len, &start, end);
    int refs = rc_arr_refs(src);
    KodArray *out = rc_arr_new(len, refs);
    out->len = len;
    if (len > 0) {
        memcpy(out->ptr, (char *)src->ptr + start * 8, len * 8);
        if (refs) rc_arr_retain_all((void **)out->ptr, len);
    }
    return out;
}

void *kod_array_copy(void *src_raw) {
    return kod_array_slice(src_raw, 0, ((KodArray *)src_raw)->len);
}

void *kod_array_concat(void *lhs_raw, void *rhs_raw) {
    KodArray *lhs = (KodArray *)lhs_raw;
    KodArray *rhs = (KodArray *)rhs_raw;
    int64_t total = lhs->len + rhs->len;
    int refs = rc_arr_refs(rhs) || rc_arr_refs(lhs);
    if (lhs->cap < total) {
        int64_t new_cap = lhs->cap > 0 ? lhs->cap : 4;
        while (new_cap < total) new_cap *= 2;
        int64_t *buf = (int64_t *)rc_alloc_raw(new_cap * 8, 0);
        if (lhs->len > 0) memcpy(buf, lhs->ptr, lhs->len * 8);
        rc_release_c(lhs->ptr);
        lhs->ptr = buf;
        lhs->cap = new_cap;
    }
    int64_t rhs_len = rhs->len;
    if (rhs_len > 0) memmove((int64_t *)lhs->ptr + lhs->len, rhs->ptr, rhs_len * 8);
    if (refs) {
        rc_arr_retain_all((void **)lhs->ptr + lhs->len, rhs_len);
        if (lhs->len == 0) rc_arr_set_refs(lhs);
    }
    lhs->len = total;
    return lhs;
}

// `xs += [x]` without the one-element array: `value` goes on the end of `arr` in
// place. When `refs` is set it is a counted reference the caller has already
// retained for the array.
void *kod_array_push(void *arr_raw, int64_t value, int64_t refs) {
    KodArray *arr = (KodArray *)arr_raw;
    if (arr->cap <= arr->len) {
        int64_t new_cap = arr->cap > 0 ? arr->cap * 2 : 4;
        int64_t *buf = (int64_t *)rc_alloc_raw(new_cap * 8, 0);
        if (arr->len > 0) memcpy(buf, arr->ptr, arr->len * 8);
        rc_release_c(arr->ptr);
        arr->ptr = buf;
        arr->cap = new_cap;
    }
    ((int64_t *)arr->ptr)[arr->len] = value;
    if (refs && arr->len == 0) rc_arr_set_refs(arr);
    arr->len++;
    return arr;
}

void *kod_array_concat_new(void *lhs_raw, void *rhs_raw) {
    KodArray *lhs = (KodArray *)lhs_raw;
    KodArray *rhs = (KodArray *)rhs_raw;
    int64_t total = lhs->len + rhs->len;
    int refs = rc_arr_refs(lhs) || rc_arr_refs(rhs);
    KodArray *out = rc_arr_new(total, refs);
    out->len = total;
    if (lhs->len > 0) memcpy(out->ptr, lhs->ptr, lhs->len * 8);
    if (rhs->len > 0) memcpy((int64_t *)out->ptr + lhs->len, rhs->ptr, rhs->len * 8);
    if (refs) rc_arr_retain_all((void **)out->ptr, total);
    return out;
}
