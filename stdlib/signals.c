/* The signal handler behind stdlib/signals.kod (docs/tasks.md): it writes the
 * signal's number to a pipe, which a task reads. */

#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <unistd.h>

static int kod_signal_pipe[2] = {-1, -1};
/* The process the pipe belongs to: not a child made by fork, which shares it. */
static pid_t kod_signal_pid = 0;
static struct sigaction kod_signal_old[NSIG];

static void kod_signal_came(int sig) {
    int err = errno;
    if (getpid() == kod_signal_pid) {
        unsigned char number = (unsigned char)sig;
        /* A full pipe drops it: there are plenty of them to read. */
        ssize_t n = write(kod_signal_pipe[1], &number, 1);
        (void)n;
    }
    errno = err;
}

/* The descriptor to read signals' numbers from, or -1 (errno says why). */
int64_t kod_signal_open(void) {
    if (kod_signal_pid == getpid()) return kod_signal_pipe[0];
    int fds[2];
    if (pipe(fds) != 0) return -1;
    for (int i = 0; i < 2; i++) fcntl(fds[i], F_SETFD, FD_CLOEXEC);
    fcntl(fds[1], F_SETFL, O_NONBLOCK);
    kod_signal_pipe[0] = fds[0];
    kod_signal_pipe[1] = fds[1];
    kod_signal_pid = getpid();
    return fds[0];
}

/* Forgets the signals that have come and not been read. */
void kod_signal_drain(void) {
    struct pollfd p = {kod_signal_pipe[0], POLLIN, 0};
    char numbers[64];
    while (poll(&p, 1, 0) > 0 && read(kod_signal_pipe[0], numbers, sizeof numbers) > 0) {
    }
}

/* From now on `sig` goes to the pipe, until kod_signal_give_back; -1 when it
 * can't (errno says why). */
int64_t kod_signal_take(int64_t sig) {
    struct sigaction sa;
    sa.sa_handler = kod_signal_came;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_RESTART;
    return sigaction((int)sig, &sa, &kod_signal_old[sig]);
}

void kod_signal_give_back(int64_t sig) {
    sigaction((int)sig, &kod_signal_old[sig], NULL);
}
