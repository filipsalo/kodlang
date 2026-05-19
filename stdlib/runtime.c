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

// Called by `must expr` when the expression evaluates to an error.
// `msg` is the result of calling the error's to_str method.
void kod_panic(const char *msg) {
    fprintf(stderr, "panic: %s\n", msg);
    exit(1);
}

// Print to stderr without exiting. Used by the codegen to surface
// user-facing errors (unknown method, etc.) while continuing to
// scan the rest of the module for additional errors.
void kod_eprint(const char *msg) {
    fprintf(stderr, "%s\n", msg);
}

char *read_file(const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) return "";
    fseek(fp, 0, SEEK_END);
    int64_t size = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    char *buf = (char *)arena_alloc(size + 1);
    fread(buf, 1, size, fp);
    buf[size] = '\0';
    fclose(fp);
    return buf;
}

char *kod_str_slice(const char *s, int64_t start, int64_t end) {
    int64_t len = end - start;
    if (len < 0) len = 0;
    char *buf = (char *)arena_alloc(len + 1);
    for (int64_t i = 0; i < len; i++) buf[i] = s[start + i];
    buf[len] = '\0';
    return buf;
}

char *kod_str_concat(const char *a, const char *b) {
    int64_t la = strlen(a);
    int64_t lb = strlen(b);
    char *buf = (char *)arena_alloc(la + lb + 1);
    for (int64_t i = 0; i < la; i++) buf[i] = a[i];
    for (int64_t i = 0; i < lb; i++) buf[la + i] = b[i];
    buf[la + lb] = '\0';
    return buf;
}

typedef struct {
    void *ptr;
    int64_t len;
    int64_t cap;
} KodArray;

// {status, stdout_buf, stderr_buf} matches the Kod-side `ProcessResult`
// struct's field order (each slot 8 bytes).
typedef struct {
    int64_t status;
    char *stdout_buf;
    char *stderr_buf;
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
    char **kod_argv = (char **)argv_arr->ptr;
    for (int64_t i = 0; i < argc; i++) argv[i] = kod_argv[i];
    argv[argc] = NULL;

    KodProcessResult *result =
        (KodProcessResult *)arena_alloc(sizeof(KodProcessResult));

    int out_pipe[2], err_pipe[2];
    if (pipe(out_pipe) != 0 || pipe(err_pipe) != 0) {
        result->status = -1;
        result->stdout_buf = (char *)arena_alloc(1);
        result->stdout_buf[0] = '\0';
        result->stderr_buf = (char *)arena_alloc(1);
        result->stderr_buf[0] = '\0';
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
        result->stdout_buf = (char *)arena_alloc(1);
        result->stdout_buf[0] = '\0';
        result->stderr_buf = (char *)arena_alloc(1);
        result->stderr_buf[0] = '\0';
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
    out_buf[out_len] = '\0';
    err_buf[err_len] = '\0';

    int status;
    waitpid(pid, &status, 0);
    int exit_status = WIFEXITED(status) ? WEXITSTATUS(status) : -1;

    result->status = exit_status;
    result->stdout_buf = out_buf;
    result->stderr_buf = err_buf;
    return result;
}

void *kod_array_concat(void *lhs_raw, void *rhs_raw) {
    KodArray *lhs = (KodArray *)lhs_raw;
    KodArray *rhs = (KodArray *)rhs_raw;
    int64_t total = lhs->len + rhs->len;
    int64_t *buf = (int64_t *)arena_alloc(total * 8);
    int64_t *sl = (int64_t *)lhs->ptr;
    int64_t *sr = (int64_t *)rhs->ptr;
    for (int64_t i = 0; i < lhs->len; i++) buf[i] = sl[i];
    for (int64_t i = 0; i < rhs->len; i++) buf[lhs->len + i] = sr[i];
    KodArray *hdr = (KodArray *)arena_alloc(sizeof(KodArray));
    hdr->ptr = buf;
    hdr->len = total;
    hdr->cap = total;
    return hdr;
}
