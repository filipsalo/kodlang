#include <fcntl.h>
#include <poll.h>
#include <spawn.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/wait.h>
#include <time.h>
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
/* `start_ns` captures the first reset's timestamp so the summary can
 * report total wall time; `case_start_ns` is refreshed on every reset
 * and consumed by the matching report call to print a per-test
 * duration. Negative means "not yet set". */
static int64_t g_kod_test_start_ns = -1;
static int64_t g_kod_test_case_start_ns = -1;

int64_t kod_monotonic_ns(void);

void kod_test_reset(void) {
    int64_t now = kod_monotonic_ns();
    if (g_kod_test_start_ns < 0) {
        g_kod_test_start_ns = now;
    }
    g_kod_test_case_start_ns = now;
    g_kod_test_failed = 0;
}

void kod_test_fail(KodStr *msg) {
    g_kod_test_failed = 1;
    /* 6-space indent: 2 for the per-module nesting, 4 more so failure
     * messages clearly belong to the test rather than the group. */
    fwrite("      ", 1, 6, stderr);
    fwrite(msg->buf, 1, msg->len, stderr);
    fputc('\n', stderr);
}

/* Called once at the top of each module's `__run_tests` dispatcher
 * (the codegen emits the call with the module's source path). Prints
 * the path on its own line so subsequent per-test `ok` / `FAIL`
 * lines (indented by `kod_test_report`) read as a group. Separates
 * groups with a blank line; the first group prints without one. */
static int g_kod_test_group_seen = 0;
void kod_test_module_begin(KodStr *path) {
    if (g_kod_test_group_seen) {
        fputc('\n', stdout);
    }
    g_kod_test_group_seen = 1;
    fwrite(path->buf, 1, path->len, stdout);
    fputc('\n', stdout);
}

/* Format `ns` in (ns / μs / ms / s) with 3 significant figures, e.g.:
 *   0 ns             → "<1 ns"      (below clock resolution — two
 *                                    consecutive monotonic reads
 *                                    landed in the same ns slot, so
 *                                    the actual value is > 0 but under
 *                                    one ns of measurable difference;
 *                                    we count in whole ns, so there's
 *                                    no sub-ns precision to report)
 *   873 ns           → "873 ns"
 *   1234 ns          → "1.23 μs"
 *   45678 ns         → "45.7 μs"
 *   123456 ns        → "123 μs"
 *   1234567 ns       → "1.23 ms"
 *   12345678 ns      → "12.3 ms"
 *   1234567890 ns    → "1.23 s"
 *
 * Keeps numbers readable across the wide range a test suite spans —
 * tens of nanoseconds for trivial assertions, seconds for the
 * compile-heavy tests. Used by both `kod_test_report` (per-test) and
 * `kod_test_summary` (total).
 */
static void format_duration(int64_t ns, char *out, size_t out_size) {
    if (ns == 0) {
        snprintf(out, out_size, "<1 ns");
        return;
    }
    double v;
    const char *unit;
    if (ns < 1000)              { v = (double)ns;                unit = "ns"; }
    else if (ns < 1000000)      { v = (double)ns / 1000.0;       unit = "μs"; }
    else if (ns < 1000000000)   { v = (double)ns / 1000000.0;    unit = "ms"; }
    else                        { v = (double)ns / 1000000000.0; unit = "s";  }
    const char *fmt = v < 10  ? "%.2f %s"
                    : v < 100 ? "%.1f %s"
                    :           "%.0f %s";
    snprintf(out, out_size, fmt, v, unit);
}

void kod_test_report(KodStr *name) {
    g_kod_test_total++;
    /* Two-space indent so the per-test lines visibly nest under the
     * module-path header from `kod_test_module_begin`. */
    if (g_kod_test_failed) {
        g_kod_test_failures++;
        fwrite("  FAIL ", 1, 7, stdout);
    } else {
        fwrite("  ok   ", 1, 7, stdout);
    }
    fwrite(name->buf, 1, name->len, stdout);
    char dur[32];
    format_duration(kod_monotonic_ns() - g_kod_test_case_start_ns, dur, sizeof dur);
    printf(" (%s)\n", dur);
}

int64_t kod_test_summary(void) {
    int64_t elapsed_ns = 0;
    if (g_kod_test_start_ns >= 0) {
        elapsed_ns = kod_monotonic_ns() - g_kod_test_start_ns;
    }
    char dur[32];
    format_duration(elapsed_ns, dur, sizeof dur);
    printf("\n%d/%d passed in %s\n",
           g_kod_test_total - g_kod_test_failures, g_kod_test_total, dur);
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

/* ── LSP state surviving arena_reset ──────────────────────────────────
 *
 * The LSP recompiles between debounced didChange bursts and would
 * otherwise leak the previous compile's tokens / AST / codegen state
 * into the arena forever — every edit adds tens of MB. To keep memory
 * bounded the LSP calls `arena_reset` before each compile, but its
 * own per-document state (open document texts, the active URI, the
 * cached compile pointer) lives here in C-owned memory so it survives
 * the reset. Getters copy bytes back into a fresh arena KodStr.
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
/* Cached compile result. The pointer lives in the arena, so we null
 * it out at the start of `arena_reset` — anything that wants it must
 * grab it before triggering a reset. */
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
 * match the last successful compile *and* the cached cg pointer is
 * still valid (no `arena_reset` since); `lsp_cache_get_cg` then returns
 * the cg. The split keeps the Kod-side simple — calling a Codegen
 * field through an extern that might return null is awkward, so the
 * caller is expected to check `lsp_cache_lookup` first.
 *
 * The cg pointer is into the arena, so it's only valid until the
 * next `arena_reset` — which nulls it via `lsp_cache_invalidate`. */
int64_t lsp_cache_lookup(KodStr *uri, KodStr *text) {
    if (!g_lsp_cached_cg) return 0;
    if (!lsp_bytes_eq(g_lsp_cached_uri, g_lsp_cached_uri_len, uri->buf, uri->len)) return 0;
    if (!lsp_bytes_eq(g_lsp_cached_text, g_lsp_cached_text_len, text->buf, text->len)) return 0;
    return 1;
}

void *lsp_cache_get_cg(void) {
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
    g_lsp_cached_cg = cg;
}

/* Called by the LSP just before `arena_reset` to clear the dangling
 * arena pointer in the cache. The uri/text byte buffers are malloc'd
 * and stay valid — only the cg pointer is invalidated. */
void lsp_cache_invalidate(void) {
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

int64_t kod_unix_ns(void) {
    struct timespec ts;
    clock_gettime(CLOCK_REALTIME, &ts);
    return (int64_t)ts.tv_sec * 1000000000 + (int64_t)ts.tv_nsec;
}
