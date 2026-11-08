// Apple gates `ucontext_t` behind _XOPEN_SOURCE (the POSIX-deprecated
// API set) — needed by the sampling profiler's SIGPROF handler in
// kod_prof_handler. _DARWIN_C_SOURCE re-enables the BSD extensions
// (CLOCK_MONOTONIC_RAW, environ, etc.) that _XOPEN_SOURCE would
// otherwise shadow.
#define _XOPEN_SOURCE 700
#define _DARWIN_C_SOURCE

#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <ucontext.h>
#include <unistd.h>

#include "kod_rt.h"

extern char **environ;

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

// Reopen stdout against `path`, so subsequent prints go to the file.
// Used by sh_kodc to capture codegen output to a .s file in a single
// process (rather than parent-captured stdout). Returns 0 on success,
// -1 on failure.
int64_t redirect_stdout(KodStr *path) {
    if (!freopen(path->buf, "w", stdout)) return -1;
    return 0;
}

// Flush stdout. Needed after a `redirect_stdout` block to make sure
// the on-disk file is complete before another process reads it.
void flush_stdout(void) {
    fflush(stdout);
}

// Write `content` to `path`, replacing the file if it exists. Parent
// directory must already exist. Returns 0 on success, -1 on any failure
// (open or write). Mirrors read_file's bare naming convention.
int64_t write_file(KodStr *path, KodStr *content) {
    FILE *fp = fopen(path->buf, "wb");
    if (!fp) return -1;
    size_t written = fwrite(content->buf, 1, (size_t)content->len, fp);
    fclose(fp);
    return written == (size_t)content->len ? 0 : -1;
}

int64_t kod_is_file(KodStr *path) {
    struct stat st;
    return stat(path->buf, &st) == 0 && S_ISREG(st.st_mode);
}

// Read until EOF: fseek/ftell can't size pipes and FIFOs.
KodStr *read_file(KodStr *path) {
    FILE *fp = fopen(path->buf, "rb");
    if (!fp) return kod_empty_str();
    size_t cap = 64 * 1024;
    size_t len = 0;
    char *buf = (char *)malloc(cap);
    while (buf) {
        len += fread(buf + len, 1, cap - len, fp);
        if (len < cap) break;
        cap *= 2;
        char *grown = (char *)realloc(buf, cap);
        if (!grown) free(buf);
        buf = grown;
    }
    int failed = !buf || ferror(fp);
    fclose(fp);
    if (failed) {
        free(buf);
        return kod_empty_str();
    }
    KodStr *s = kod_str_alloc((int64_t)len);
    memcpy(s->buf, buf, len);
    free(buf);
    return s;
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

// File descriptor I/O for stdlib/posix.kod. The calls return their result and
// leave the reason for a failure in `kod_io_errno()` (0 after a success),
// which Kod reads straight after. Interrupted calls are retried here.
static int64_t g_io_errno;

int64_t kod_io_errno(void) { return g_io_errno; }

void kod_io_set_errno(int64_t err) { g_io_errno = err; }

// mode: 0 read, 1 create or truncate for writing, 2 create or append.
int64_t kod_fd_open(KodStr *path, int64_t mode) {
    int flags = O_RDONLY;
    if (mode == 1) flags = O_WRONLY | O_CREAT | O_TRUNC;
    if (mode == 2) flags = O_WRONLY | O_CREAT | O_APPEND;
    int fd;
    do {
        fd = open(path->buf, flags | O_CLOEXEC, 0644);
    } while (fd < 0 && errno == EINTR);
    g_io_errno = fd < 0 ? errno : 0;
    return fd;
}

// At most `max` bytes (and never more than 64 KiB) from `fd`; empty at the
// end of the stream, and on failure, which sets the errno.
KodStr *kod_fd_read(int64_t fd, int64_t max) {
    char chunk[65536];
    if (max > (int64_t)sizeof chunk) max = (int64_t)sizeof chunk;
    g_io_errno = 0;
    if (max <= 0) return kod_str_new(0);
    ssize_t n;
    do {
        n = read((int)fd, chunk, (size_t)max);
    } while (n < 0 && errno == EINTR);
    if (n < 0) {
        g_io_errno = errno;
        return kod_str_new(0);
    }
    return kod_str_from_bytes(chunk, n);
}

// Bytes written, or -1 with the errno set.
int64_t kod_fd_write(int64_t fd, KodStr *data) {
    g_io_errno = 0;
    if (data->len == 0) return 0;
    ssize_t n;
    do {
        n = write((int)fd, data->buf, (size_t)data->len);
    } while (n < 0 && errno == EINTR);
    if (n < 0) {
        g_io_errno = errno;
        return -1;
    }
    return n;
}

int64_t kod_fd_close(int64_t fd) {
    int rc = close((int)fd);
    g_io_errno = rc < 0 ? errno : 0;
    return rc;
}

KodStr *kod_errno_message(int64_t err) {
    return kod_str_from_cstr(strerror((int)err));
}

// The position in stdlib/stream.kod's IoKind that an OS error number maps to.
int64_t kod_errno_kind(int64_t err) {
    switch (err) {
    case ENOENT: return 0;
    case EACCES: case EPERM: return 1;
    case EEXIST: case EADDRINUSE: return 2;
    case EINVAL: case EBADF: case EISDIR: case ENOTDIR: return 3;
    case EAGAIN: case ETIMEDOUT: return 5;
    case ECONNREFUSED: return 6;
    case ECONNRESET: return 7;
    case EPIPE: return 8;
    default: return 10;
    }
}

// Environment variables for stdlib/env.kod. The Kod side has already refused
// names that are empty or hold `=` or a NUL byte, and values with a NUL byte.
int64_t kod_env_has(KodStr *name) {
    return getenv(name->buf) != NULL;
}

KodStr *kod_env_get(KodStr *name) {
    const char *value = getenv(name->buf);
    return kod_str_from_cstr(value ? value : "");
}

int64_t kod_env_set(KodStr *name, KodStr *value) {
    return setenv(name->buf, value->buf, 1) == 0 ? 0 : -1;
}

void kod_env_unset(KodStr *name) {
    unsetenv(name->buf);
}

// {status, stdout_buf, stderr_buf} matches the Kod-side `ProcessResult`
// struct's field order (each slot 8 bytes). The two `*` slots hold
// Kod `str` values (i.e. pointers to KodStr structs).
typedef struct {
    int64_t status;
    KodStr *stdout_buf;
    KodStr *stderr_buf;
} KodProcessResult;

// Append `n` bytes from `src` onto a growable buffer.
// Updates *buf, *len, *cap; allocates fresh storage when the
// current capacity isn't enough. Returns the (possibly-new) buffer ptr.
static char *append_to_buf(char *buf, int64_t *len, int64_t *cap,
                           const char *src, int64_t n) {
    if (*len + n > *cap) {
        int64_t new_cap = *cap;
        while (new_cap < *len + n) new_cap *= 2;
        char *new_buf = (char *)rc_alloc_raw(new_cap + 1, 0);
        memcpy(new_buf, buf, *len);
        rc_release_c(buf);
        buf = new_buf;
        *cap = new_cap;
    }
    memcpy(buf + *len, src, n);
    *len += n;
    return buf;
}

// The NULL-terminated C `argv` for a Kod `[str]`, for the caller to release. What
// posix_spawnp and execvp want is NUL-terminated C strings, not KodStr —
// pull the underlying `buf` field out of each entry.
static char **c_argv(KodArray *argv_arr) {
    int64_t argc = argv_arr->len;
    char **argv = (char **)rc_alloc_raw((argc + 1) * sizeof(char *), 0);
    KodStr **kod_argv = (KodStr **)argv_arr->ptr;
    for (int64_t i = 0; i < argc; i++) argv[i] = kod_argv[i]->buf;
    argv[argc] = NULL;
    return argv;
}

// Spawn `argv[0]` with `argv` (NULL-terminated rebuilt from the Kod
// `[str]`), capture stdout and stderr concurrently (via poll to avoid
// the obvious deadlock where one pipe fills while we're blocked on the
// other), wait, and return {status, stdout, stderr}. On spawn failure
// status is -1 and the buffers are empty.
KodProcessResult *kod_run_process(KodArray *argv_arr) {
    char **argv = c_argv(argv_arr);

    KodProcessResult *result =
        (KodProcessResult *)rc_alloc(sizeof(KodProcessResult), 6); // the two strs

    int out_pipe[2], err_pipe[2];
    if (pipe(out_pipe) != 0 || pipe(err_pipe) != 0) {
        result->status = -1;
        result->stdout_buf = kod_empty_str();
        result->stderr_buf = kod_empty_str();
        return result;
    }

    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addclose(&actions, out_pipe[0]);
    posix_spawn_file_actions_adddup2(&actions, out_pipe[1], 1);
    posix_spawn_file_actions_addclose(&actions, out_pipe[1]);
    posix_spawn_file_actions_addclose(&actions, err_pipe[0]);
    posix_spawn_file_actions_adddup2(&actions, err_pipe[1], 2);
    posix_spawn_file_actions_addclose(&actions, err_pipe[1]);

    pid_t pid;
    int rc = posix_spawnp(&pid, argv[0], &actions, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&actions);
    close(out_pipe[1]);
    close(err_pipe[1]);

    if (rc != 0) {
        close(out_pipe[0]);
        close(err_pipe[0]);
        result->status = -1;
        result->stdout_buf = kod_empty_str();
        result->stderr_buf = kod_empty_str();
        return result;
    }

    struct pollfd pfds[2];
    pfds[0].fd = out_pipe[0];
    pfds[0].events = POLLIN;
    pfds[1].fd = err_pipe[0];
    pfds[1].events = POLLIN;

    int64_t out_cap = 256, out_len = 0;
    int64_t err_cap = 256, err_len = 0;
    char *out_buf = (char *)rc_alloc_raw(out_cap + 1, 0);
    char *err_buf = (char *)rc_alloc_raw(err_cap + 1, 0);

    int open_count = 2;
    while (open_count > 0) {
        int n = poll(pfds, 2, -1);
        if (n < 0) break;
        for (int i = 0; i < 2; i++) {
            if (pfds[i].fd < 0) continue;
            if (!(pfds[i].revents & (POLLIN | POLLHUP | POLLERR))) continue;
            char tmp[4096];
            ssize_t r = read(pfds[i].fd, tmp, sizeof(tmp));
            if (r <= 0) {
                close(pfds[i].fd);
                pfds[i].fd = -1;
                open_count--;
                continue;
            }
            if (i == 0) {
                out_buf = append_to_buf(out_buf, &out_len, &out_cap, tmp, r);
            } else {
                err_buf = append_to_buf(err_buf, &err_len, &err_cap, tmp, r);
            }
        }
    }
    // Copy the raw capture buffers into properly-headed Kod strings.
    // append_to_buf grows storage without leaving room for a KodStr
    // header, so we can't hand the raw buffers back as Kod strs.
    KodStr *out_str = kod_str_alloc(out_len);
    memcpy(out_str->buf, out_buf, out_len);
    KodStr *err_str = kod_str_alloc(err_len);
    memcpy(err_str->buf, err_buf, err_len);
    rc_release_c(out_buf);
    rc_release_c(err_buf);
    rc_release_c(argv);

    int status;
    waitpid(pid, &status, 0);
    int exit_status = WIFEXITED(status) ? WEXITSTATUS(status) : -1;

    result->status = exit_status;
    result->stdout_buf = out_str;
    result->stderr_buf = err_str;
    return result;
}

// Start `argv[0]` (found via PATH) with stdin, stdout and stderr on
// /dev/null and return its pid without waiting, or -1 when it could not be
// started.
int64_t kod_spawn(KodArray *argv_arr) {
    if (argv_arr->len == 0) return -1;
    char **argv = c_argv(argv_arr);
    posix_spawn_file_actions_t actions;
    posix_spawn_file_actions_init(&actions);
    posix_spawn_file_actions_addopen(&actions, 0, "/dev/null", O_RDONLY, 0);
    posix_spawn_file_actions_addopen(&actions, 1, "/dev/null", O_WRONLY, 0);
    posix_spawn_file_actions_addopen(&actions, 2, "/dev/null", O_WRONLY, 0);
    pid_t pid;
    int rc = posix_spawnp(&pid, argv[0], &actions, NULL, argv, environ);
    posix_spawn_file_actions_destroy(&actions);
    rc_release_c(argv);
    return rc == 0 ? (int64_t)pid : -1;
}

// SIGTERM a child and reap it. False when the signal could not be sent.
int64_t kod_kill(int64_t pid) {
    if (pid <= 0 || kill((pid_t)pid, SIGTERM) != 0) return 0;
    int status;
    waitpid((pid_t)pid, &status, 0);
    return 1;
}

// float64: a Kod `float64` travels as the 8 bytes of its IEEE 754 pattern in an
// ordinary integer register or slot. kod_i64_to_f64, kod_f64_to_i64,
// kod_f64_abs, floor, ceil, round, sqrt, is_nan and is_inf have no C side:
// codegen's float_intrinsic compiles a call to them to the instructions that do
// the work. Printing and reading floats is Kod (stdlib/primitives/float_text.kod).

// kod_f64_bits and kod_f64_from_bits are intrinsics too, but stdlib/primitives
// is compiled by the bootstrap snapshot, which predates them and calls these.
// Delete them once the snapshot knows the intrinsics.
int64_t kod_f64_bits(int64_t bits) { return bits; }
int64_t kod_f64_from_bits(int64_t bits) { return bits; }

// Replace this process with `argv[0]` (found via PATH) and `argv`. Buffered
// output is flushed first: the new image would never see it. Returns -1,
// and only then, when the exec failed (nothing to run, or an empty argv).
int64_t kod_exec(KodArray *argv_arr) {
    if (argv_arr->len == 0) return -1;
    char **argv = c_argv(argv_arr);
    fflush(NULL);
    execvp(argv[0], argv);
    return -1;
}

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

// Return 1 if stdin has data ready (or EOF) within `timeout_ms`, 0 on
// timeout, -1 on error. Used by the LSP loop to detect typing pauses:
// after a didChange, wait a short window for the next message; if it
// doesn't arrive, the user has paused and it's worth doing the
// expensive compile + diagnostics publish.
int64_t stdin_data_ready(int64_t timeout_ms) {
    struct pollfd pfd = { .fd = 0, .events = POLLIN };
    int n = poll(&pfd, 1, (int)timeout_ms);
    if (n < 0) {
        return -1;
    }
    return n > 0 ? 1 : 0;
}

// Read one '\n'-terminated line from stdin, NUL-terminate it, strip a
// trailing '\r' if present, and return the body. Returns an empty
// string on EOF with no bytes buffered. Used by LSP-style framing:
// callers read Content-Length headers line-by-line and then switch to
// read_stdin_exact for the body.
KodStr *read_stdin_line(void) {
    // Read into a scratch buffer first (length unknown up front), then
    // copy into a properly-headed KodStr at the end.
    int64_t cap = 64;
    int64_t len = 0;
    char *scratch = (char *)rc_alloc_raw(cap, 0);
    while (1) {
        int ch = getchar();
        if (ch == EOF) {
            break;
        }
        if (ch == '\n') {
            break;
        }
        if (len + 1 >= cap) {
            int64_t new_cap = cap * 2;
            char *new_buf = (char *)rc_alloc_raw(new_cap, 0);
            for (int64_t i = 0; i < len; i++) new_buf[i] = scratch[i];
            rc_release_c(scratch);
            scratch = new_buf;
            cap = new_cap;
        }
        scratch[len++] = (char)ch;
    }
    if (len > 0 && scratch[len - 1] == '\r') {
        len--;
    }
    KodStr *s = kod_str_alloc(len);
    memcpy(s->buf, scratch, len);
    rc_release_c(scratch);
    return s;
}

// Write `s` to stdout verbatim — no trailing newline, no flush. Use
// for output where you control framing (e.g. LSP messages where the
// `\n` puts/print appends would split the next message's headers).
void write_stdout(KodStr *s) {
    fwrite(s->buf, 1, (size_t)s->len, stdout);
}

// Same for stderr — used by the kod-side build/run driver to forward
// a child process's captured stderr without an extra newline.
void write_stderr(KodStr *s) {
    fwrite(s->buf, 1, (size_t)s->len, stderr);
}

// Read exactly `n` bytes from stdin into a fresh KodStr. On a short
// read (EOF before n bytes), the header's `len` is shrunk to match
// what was actually read — callers length-check against `n`. Used
// for LSP message bodies after Content-Length headers.
KodStr *read_stdin_exact(int64_t n) {
    KodStr *s = kod_str_alloc(n);
    int64_t got = 0;
    while (got < n) {
        size_t r = fread(s->buf + got, 1, (size_t)(n - got), stdin);
        if (r == 0) {
            break;
        }
        got += (int64_t)r;
    }
    if (got != n) {
        s->len = got;
        s->buf[got] = '\0';
    }
    return s;
}

/* ── LSP state ────────────────────────────────────────────────────────
 *
 * Open document texts, the active URI and the cached compile, in memory
 * C owns. Getters copy bytes back into a fresh KodStr.
 */

typedef struct LspDoc {
    char *uri;
    int64_t uri_len;
    char *text;
    int64_t text_len;
    struct LspDoc *next;
} LspDoc;

static LspDoc *g_lsp_docs = NULL;
static char *g_lsp_active_uri = NULL;
static int64_t g_lsp_active_uri_len = 0;
static int g_lsp_publish_pending = 0;
/* Cached compile result: this holds a reference to it. */
static void *g_lsp_cached_cg = NULL;
static char *g_lsp_cached_uri = NULL;
static int64_t g_lsp_cached_uri_len = 0;
static char *g_lsp_cached_text = NULL;
static int64_t g_lsp_cached_text_len = 0;

static int lsp_bytes_eq(const char *a, int64_t alen, const char *b, int64_t blen) {
    if (alen != blen) return 0;
    return memcmp(a, b, (size_t)alen) == 0;
}

static LspDoc *lsp_docs_find(KodStr *uri) {
    for (LspDoc *d = g_lsp_docs; d; d = d->next) {
        if (lsp_bytes_eq(d->uri, d->uri_len, uri->buf, uri->len)) {
            return d;
        }
    }
    return NULL;
}

void lsp_docs_set(KodStr *uri, KodStr *text) {
    LspDoc *d = lsp_docs_find(uri);
    if (d) {
        free(d->text);
        d->text = (char *)malloc((size_t)text->len);
        if (text->len > 0) memcpy(d->text, text->buf, (size_t)text->len);
        d->text_len = text->len;
        return;
    }
    d = (LspDoc *)malloc(sizeof(LspDoc));
    d->uri = (char *)malloc((size_t)uri->len);
    if (uri->len > 0) memcpy(d->uri, uri->buf, (size_t)uri->len);
    d->uri_len = uri->len;
    d->text = (char *)malloc((size_t)text->len);
    if (text->len > 0) memcpy(d->text, text->buf, (size_t)text->len);
    d->text_len = text->len;
    d->next = g_lsp_docs;
    g_lsp_docs = d;
}

/* Returns the empty string if the URI isn't tracked. Caller can't
 * distinguish "no entry" from "empty document"; for the LSP that's
 * fine because a closed doc is treated the same as never-opened. */
KodStr *lsp_docs_get(KodStr *uri) {
    LspDoc *d = lsp_docs_find(uri);
    if (!d) return kod_empty_str();
    KodStr *s = kod_str_alloc(d->text_len);
    if (d->text_len > 0) memcpy(s->buf, d->text, (size_t)d->text_len);
    return s;
}

void lsp_docs_remove(KodStr *uri) {
    LspDoc **slot = &g_lsp_docs;
    while (*slot) {
        if (lsp_bytes_eq((*slot)->uri, (*slot)->uri_len, uri->buf, uri->len)) {
            LspDoc *dead = *slot;
            *slot = dead->next;
            free(dead->uri);
            free(dead->text);
            free(dead);
            return;
        }
        slot = &(*slot)->next;
    }
}

void lsp_set_active_uri(KodStr *uri) {
    free(g_lsp_active_uri);
    g_lsp_active_uri = (char *)malloc((size_t)uri->len);
    if (uri->len > 0) memcpy(g_lsp_active_uri, uri->buf, (size_t)uri->len);
    g_lsp_active_uri_len = uri->len;
}

KodStr *lsp_get_active_uri(void) {
    KodStr *s = kod_str_alloc(g_lsp_active_uri_len);
    if (g_lsp_active_uri_len > 0) {
        memcpy(s->buf, g_lsp_active_uri, (size_t)g_lsp_active_uri_len);
    }
    return s;
}

int64_t lsp_get_publish_pending(void) { return g_lsp_publish_pending; }
void lsp_set_publish_pending(int64_t v) { g_lsp_publish_pending = v ? 1 : 0; }

/* Cache lookup, two-step. `lsp_cache_lookup` returns 1 when (uri, text)
 * match the last successful compile; `lsp_cache_get_cg` then returns
 * the cg. The split keeps the Kod-side simple — calling a Codegen
 * field through an extern that might return null is awkward, so the
 * caller is expected to check `lsp_cache_lookup` first. */
int64_t lsp_cache_lookup(KodStr *uri, KodStr *text) {
    if (!g_lsp_cached_cg) return 0;
    if (!lsp_bytes_eq(g_lsp_cached_uri, g_lsp_cached_uri_len, uri->buf, uri->len)) return 0;
    if (!lsp_bytes_eq(g_lsp_cached_text, g_lsp_cached_text_len, text->buf, text->len)) return 0;
    return 1;
}

void *lsp_cache_get_cg(void) {
    rc_retain_c(g_lsp_cached_cg);
    return g_lsp_cached_cg;
}

void lsp_cache_store(KodStr *uri, KodStr *text, void *cg) {
    free(g_lsp_cached_uri);
    g_lsp_cached_uri = (char *)malloc((size_t)uri->len);
    if (uri->len > 0) memcpy(g_lsp_cached_uri, uri->buf, (size_t)uri->len);
    g_lsp_cached_uri_len = uri->len;
    free(g_lsp_cached_text);
    g_lsp_cached_text = (char *)malloc((size_t)text->len);
    if (text->len > 0) memcpy(g_lsp_cached_text, text->buf, (size_t)text->len);
    g_lsp_cached_text_len = text->len;
    rc_retain_c(cg);
    rc_release_c(g_lsp_cached_cg);
    g_lsp_cached_cg = cg;
}

/* Drops the cached compile. The uri/text byte buffers stay. */
void lsp_cache_invalidate(void) {
    rc_release_c(g_lsp_cached_cg);
    g_lsp_cached_cg = NULL;
}

/* ── Time ─────────────────────────────────────────────────────────────
 *
 * Two primitives: a monotonic clock (origin is unspecified — only
 * differences are meaningful, but it never goes backwards) and a
 * wall clock (nanoseconds since the Unix epoch). Both return int64
 * to avoid carrying a time-struct around at the language level;
 * users do the arithmetic. Sufficient for ~292 years of nanoseconds,
 * comfortably past any test-runner timing or "is this stale?" use.
 */
int64_t kod_monotonic_ns(void) {
    // CLOCK_MONOTONIC_RAW, not CLOCK_MONOTONIC: the latter is only 1 µs
    // granular on macOS (clock_getres reports 1000 ns), so durations
    // came out as whole microseconds with three trailing zeros. The RAW
    // clock is backed by the hardware timebase (~41 ns/tick on Apple
    // silicon), giving honest sub-µs resolution. RAW also skips NTP
    // slewing, which is what we want for measuring elapsed time anyway.
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC_RAW, &ts);
    return (int64_t)ts.tv_sec * 1000000000 + (int64_t)ts.tv_nsec;
}

/* Resolution of CLOCK_MONOTONIC_RAW in whole ns (at least 1): about 42 ns
 * on Apple silicon (24 MHz timebase). The smallest difference two reads of
 * kod_monotonic_ns can show; the test runner reports a 0 ns duration as
 * below it. */
int64_t kod_monotonic_res_ns(void) {
    struct timespec r;
    if (clock_getres(CLOCK_MONOTONIC_RAW, &r) != 0) {
        return 1;
    }
    int64_t ns = (int64_t)r.tv_sec * 1000000000 + r.tv_nsec;
    return ns > 0 ? ns : 1;
}

int64_t kod_unix_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)ts.tv_sec * 1000000000 + (int64_t)ts.tv_nsec;
}

// Sleep for `ns` nanoseconds; a signal doesn't end it early. Zero or less returns at once.
void kod_sleep_ns(int64_t ns) {
    if (ns <= 0) {
        return;
    }
    struct timespec ts;
    ts.tv_sec = ns / 1000000000;
    ts.tv_nsec = ns % 1000000000;
    while (nanosleep(&ts, &ts) != 0 && errno == EINTR) {
    }
}

// ── Sampling profiler ─────────────────────────────────────────────────
//
// SIGPROF-driven sampler: every `interval_us` of CPU time the kernel
// delivers SIGPROF and the handler records the call stack (return
// addresses) into a fixed buffer. `stdlib/kod/profiling.kod` exposes
// start/stop/report; aggregation + name resolution happen in kod after
// sampling stops, so the signal handler stays async-signal-safe (no
// allocation, no libc calls, just memory reads + counter increments).
//
// Sample storage is a flat 2D array `[KOD_PROF_MAX_SAMPLES *
// KOD_PROF_MAX_FRAMES]` of return addresses, plus a parallel array of
// per-sample depths. Each handler entry walks at most KOD_PROF_MAX_FRAMES
// frames; entries past the limit truncate (we lose the bottom of deep
// stacks but never over-run). When the sample buffer fills, further
// handler entries no-op — the report shows what we captured.
//
// The captured chain is `[PC, lr_of_F, lr_of_caller(F), ...]`. The
// first entry is the program counter at signal time (interrupted
// instruction); the rest come from walking fp[8] / fp[0] off the
// ucontext-supplied fp register, same shape as inspect's panic walker.

#define KOD_PROF_MAX_FRAMES 32
// 4096 samples × 32 frames × 8 bytes = 1 MiB. At 1 ms sampling that's
// ~4 s of capture before the buffer fills.
#define KOD_PROF_MAX_SAMPLES 4096

static int64_t kod_prof_frames[KOD_PROF_MAX_SAMPLES * KOD_PROF_MAX_FRAMES];
static int32_t kod_prof_depths[KOD_PROF_MAX_SAMPLES];
static volatile int64_t kod_prof_count = 0;

static void kod_prof_handler(int sig, siginfo_t *info, void *ucontext) {
    (void)sig;
    (void)info;
    if (kod_prof_count >= KOD_PROF_MAX_SAMPLES) return;
    ucontext_t *uc = (ucontext_t *)ucontext;
    int64_t slot = kod_prof_count;
    int64_t *row = &kod_prof_frames[slot * KOD_PROF_MAX_FRAMES];
    int depth = 0;
    row[depth++] = (int64_t)(uintptr_t)uc->uc_mcontext->__ss.__pc;
    void **fp = (void **)uc->uc_mcontext->__ss.__fp;
    while (fp != NULL && depth < KOD_PROF_MAX_FRAMES) {
        void *lr = fp[1];
        if (lr == NULL) break;
        row[depth++] = (int64_t)(uintptr_t)lr;
        void *next = fp[0];
        if (next == NULL || (uintptr_t)next <= (uintptr_t)fp) break;
        fp = (void **)next;
    }
    kod_prof_depths[slot] = depth;
    kod_prof_count = slot + 1;
}

void _profiling_start(int64_t interval_us) {
    kod_prof_count = 0;
    struct sigaction sa;
    memset(&sa, 0, sizeof(sa));
    sa.sa_sigaction = kod_prof_handler;
    sa.sa_flags = SA_SIGINFO | SA_RESTART;
    sigemptyset(&sa.sa_mask);
    sigaction(SIGPROF, &sa, NULL);
    struct itimerval timer;
    timer.it_value.tv_sec = interval_us / 1000000;
    timer.it_value.tv_usec = interval_us % 1000000;
    timer.it_interval = timer.it_value;
    setitimer(ITIMER_PROF, &timer, NULL);
}

void _profiling_stop(void) {
    struct itimerval timer;
    memset(&timer, 0, sizeof(timer));
    setitimer(ITIMER_PROF, &timer, NULL);
}

int64_t _profiling_n_samples(void) { return kod_prof_count; }

int64_t _profiling_sample_depth(int64_t idx) {
    if (idx < 0 || idx >= kod_prof_count) return 0;
    return kod_prof_depths[idx];
}

int64_t _profiling_sample_frame(int64_t sample_idx, int64_t frame_idx) {
    if (sample_idx < 0 || sample_idx >= kod_prof_count) return 0;
    if (frame_idx < 0 || frame_idx >= kod_prof_depths[sample_idx]) return 0;
    return kod_prof_frames[sample_idx * KOD_PROF_MAX_FRAMES + frame_idx];
}
