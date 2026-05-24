#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;

void *arena_alloc(int64_t size);

// A Kod `str` value is a pointer to one of these. `buf` points at a
// byte buffer of `len` bytes plus an explicit NUL terminator (kept
// for cheap libc interop — pass `buf` directly into puts/fopen-style
// APIs). All str-handling externs return / accept `KodStr *`; the
// codegen passes the struct pointer in `x0` without unwrapping.
typedef struct {
    char *buf;
    int64_t len;
} KodStr;

// Allocate a fresh KodStr plus a `len`-byte NUL-terminated buffer in
// a single arena allocation. Caller fills `buf` before returning.
static KodStr *kod_str_alloc(int64_t len) {
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
// `msg` is the result of calling the error's to_str method.
void kod_panic(KodStr *msg) {
    fwrite("panic: ", 1, 7, stderr);
    fwrite(msg->buf, 1, msg->len, stderr);
    fputc('\n', stderr);
    exit(1);
}

// Called by the codegen's array-indexing bounds check on a miss.
// Negative indices are already normalised (idx += len) before this
// runs, so any out-of-range value here is genuinely out of bounds.
void kod_index_oob(int64_t idx, int64_t len) {
    fprintf(stderr,
            "panic: index %lld out of bounds for array of length %lld\n",
            (long long)idx, (long long)len);
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


// Test framework state. The per-module `__run_tests` dispatcher emitted
// by the codegen calls kod_test_reset before each test, the test body
// calls kod_test_fail (from `testing.fail(msg)`) on a failure, and the
// dispatcher calls kod_test_report afterwards to print the outcome and
// roll into the aggregate counters. kod_test_summary is called once at
// the very end; its return value (number of failures) is what the
// process exits with.
static int g_kod_test_failed;
static int g_kod_test_total;
static int g_kod_test_failures;

void kod_test_reset(void) { g_kod_test_failed = 0; }

void kod_test_fail(KodStr *msg) {
    g_kod_test_failed = 1;
    fwrite("    ", 1, 4, stderr);
    fwrite(msg->buf, 1, msg->len, stderr);
    fputc('\n', stderr);
}

void kod_test_report(KodStr *name) {
    g_kod_test_total++;
    if (g_kod_test_failed) {
        g_kod_test_failures++;
        fwrite("FAIL ", 1, 5, stdout);
    } else {
        fwrite("ok   ", 1, 5, stdout);
    }
    fwrite(name->buf, 1, name->len, stdout);
    fputc('\n', stdout);
}

int64_t kod_test_summary(void) {
    printf("\n%d/%d passed\n",
           g_kod_test_total - g_kod_test_failures, g_kod_test_total);
    return g_kod_test_failures > 0 ? 1 : 0;
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

KodStr *read_file(KodStr *path) {
    FILE *fp = fopen(path->buf, "rb");
    if (!fp) return kod_empty_str();
    fseek(fp, 0, SEEK_END);
    int64_t size = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    KodStr *s = kod_str_alloc(size);
    fread(s->buf, 1, size, fp);
    fclose(fp);
    return s;
}

KodStr *kod_str_slice(KodStr *s, int64_t start, int64_t end) {
    int64_t len = end - start;
    if (len < 0) len = 0;
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

typedef struct {
    void *ptr;
    int64_t len;
    int64_t cap;
} KodArray;

// {status, stdout_buf, stderr_buf} matches the Kod-side `ProcessResult`
// struct's field order (each slot 8 bytes). The two `*` slots hold
// Kod `str` values (i.e. pointers to KodStr structs).
typedef struct {
    int64_t status;
    KodStr *stdout_buf;
    KodStr *stderr_buf;
} KodProcessResult;

// Append `n` bytes from `src` onto a growable arena-backed buffer.
// Updates *buf, *len, *cap; arena-allocates fresh storage when the
// current capacity isn't enough. Returns the (possibly-new) buffer ptr.
static char *append_to_buf(char *buf, int64_t *len, int64_t *cap,
                           const char *src, int64_t n) {
    if (*len + n > *cap) {
        int64_t new_cap = *cap;
        while (new_cap < *len + n) new_cap *= 2;
        char *new_buf = (char *)arena_alloc(new_cap + 1);
        memcpy(new_buf, buf, *len);
        buf = new_buf;
        *cap = new_cap;
    }
    memcpy(buf + *len, src, n);
    *len += n;
    return buf;
}

// Spawn `argv[0]` with `argv` (NULL-terminated rebuilt from the Kod
// `[str]`), capture stdout and stderr concurrently (via poll to avoid
// the obvious deadlock where one pipe fills while we're blocked on the
// other), wait, and return {status, stdout, stderr}. On spawn failure
// status is -1 and the buffers are empty. Allocates the result and
// both buffers in the arena.
KodProcessResult *kod_run_process(KodArray *argv_arr) {
    int64_t argc = argv_arr->len;
    char **argv = (char **)arena_alloc((argc + 1) * sizeof(char *));
    KodStr **kod_argv = (KodStr **)argv_arr->ptr;
    // argv passed to posix_spawnp wants NUL-terminated C strings, not
    // KodStr — pull the underlying `buf` field out of each entry.
    for (int64_t i = 0; i < argc; i++) argv[i] = kod_argv[i]->buf;
    argv[argc] = NULL;

    KodProcessResult *result =
        (KodProcessResult *)arena_alloc(sizeof(KodProcessResult));

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
    char *out_buf = (char *)arena_alloc(out_cap + 1);
    char *err_buf = (char *)arena_alloc(err_cap + 1);

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

    int status;
    waitpid(pid, &status, 0);
    int exit_status = WIFEXITED(status) ? WEXITSTATUS(status) : -1;

    result->status = exit_status;
    result->stdout_buf = out_str;
    result->stderr_buf = err_str;
    return result;
}

// Append rhs to lhs, mutating lhs in place when its `cap` is large enough
// and reallocating with exponential growth otherwise. Returns lhs.
//
// Intentional aliasing-semantics change versus the original "always-fresh
// hdr" behavior: callers like `xs += [x]` now observe amortized O(1) per
// append (was O(n), so O(n²) over a build loop). `let b = a; a += [x]`
// will now also append to `b` — but no in-tree caller relied on the old
// copy-on-concat semantics, and pytest + the Kod test suites all pass.
void *kod_array_concat(void *lhs_raw, void *rhs_raw) {
    KodArray *lhs = (KodArray *)lhs_raw;
    KodArray *rhs = (KodArray *)rhs_raw;
    int64_t total = lhs->len + rhs->len;
    if (lhs->cap < total) {
        int64_t new_cap = lhs->cap > 0 ? lhs->cap : 4;
        while (new_cap < total) new_cap *= 2;
        int64_t *buf = (int64_t *)arena_alloc(new_cap * 8);
        int64_t *sl = (int64_t *)lhs->ptr;
        for (int64_t i = 0; i < lhs->len; i++) buf[i] = sl[i];
        lhs->ptr = buf;
        lhs->cap = new_cap;
    }
    int64_t *dst = (int64_t *)lhs->ptr;
    int64_t *sr = (int64_t *)rhs->ptr;
    for (int64_t i = 0; i < rhs->len; i++) dst[lhs->len + i] = sr[i];
    lhs->len = total;
    return lhs;
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
    char *scratch = (char *)arena_alloc(cap);
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
            char *new_buf = (char *)arena_alloc(new_cap);
            for (int64_t i = 0; i < len; i++) new_buf[i] = scratch[i];
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
    return s;
}

// Write `s` to stdout verbatim — no trailing newline, no flush. Use
// for output where you control framing (e.g. LSP messages where the
// `\n` puts/print appends would split the next message's headers).
void write_stdout(KodStr *s) {
    fwrite(s->buf, 1, (size_t)s->len, stdout);
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
