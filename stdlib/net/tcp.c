// The C side of tcp.kod: sockets as plain descriptors. A failure returns -1
// with the OS error number in kod_io_set_errno, or, when a name does not
// resolve, with the resolver's message kept for kod_tcp_gai_message.
#include "kod_rt.h"

#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <netdb.h>
#include <netinet/in.h>
#include <netinet/tcp.h>
#include <poll.h>
#include <stdio.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

static char g_gai_message[256];

KodStr *kod_tcp_gai_message(void) {
    return kod_str_from_bytes(g_gai_message, (int64_t)strlen(g_gai_message));
}

static int64_t fail(int err) {
    kod_io_set_errno(err);
    return -1;
}

// Resolve `host`:`port`; NULL with the error recorded if that fails.
static struct addrinfo *resolve(const char *host, int64_t port, int family, int passive) {
    struct addrinfo hints;
    memset(&hints, 0, sizeof hints);
    hints.ai_family = family;
    hints.ai_socktype = SOCK_STREAM;
    if (passive) hints.ai_flags = AI_PASSIVE;
    char service[16];
    snprintf(service, sizeof service, "%lld", (long long)port);
    struct addrinfo *list = NULL;
    g_gai_message[0] = '\0';
    int rc = getaddrinfo(host, service, &hints, &list);
    if (rc != 0) {
        if (rc == EAI_SYSTEM) {
            fail(errno);
        } else {
            snprintf(g_gai_message, sizeof g_gai_message, "%s", gai_strerror(rc));
            kod_io_set_errno(0);
        }
        return NULL;
    }
    return list;
}

static int new_socket(const struct addrinfo *ai) {
    int fd = socket(ai->ai_family, ai->ai_socktype, ai->ai_protocol);
    if (fd < 0) return -1;
    int one = 1;
    fcntl(fd, F_SETFD, FD_CLOEXEC);
    setsockopt(fd, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
    return fd;
}

// Connect `fd` to `ai` within `timeout_ms`; 0 or an errno.
static int connect_within(int fd, const struct addrinfo *ai, int64_t timeout_ms) {
    int flags = fcntl(fd, F_GETFL, 0);
    fcntl(fd, F_SETFL, flags | O_NONBLOCK);
    int rc = connect(fd, ai->ai_addr, ai->ai_addrlen);
    if (rc < 0 && errno != EINPROGRESS && errno != EINTR) return errno;
    if (rc < 0) {
        struct pollfd p = {.fd = fd, .events = POLLOUT};
        int ready;
        do {
            ready = poll(&p, 1, timeout_ms > 2147483647 ? 2147483647 : (int)timeout_ms);
        } while (ready < 0 && errno == EINTR);
        if (ready < 0) return errno;
        if (ready == 0) return ETIMEDOUT;
        int err = 0;
        socklen_t n = sizeof err;
        if (getsockopt(fd, SOL_SOCKET, SO_ERROR, &err, &n) < 0) return errno;
        if (err != 0) return err;
    }
    fcntl(fd, F_SETFL, flags);
    return 0;
}

int64_t kod_tcp_connect(KodStr *host, int64_t port, int64_t timeout_ms) {
    struct addrinfo *list = resolve(host->buf, port, AF_UNSPEC, 0);
    if (!list) return -1;
    int last = ECONNREFUSED;
    for (struct addrinfo *ai = list; ai; ai = ai->ai_next) {
        int fd = new_socket(ai);
        if (fd < 0) {
            last = errno;
            continue;
        }
        int err = connect_within(fd, ai, timeout_ms);
        if (err == 0) {
            int one = 1;
            setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
            freeaddrinfo(list);
            kod_io_set_errno(0);
            return fd;
        }
        close(fd);
        last = err;
    }
    freeaddrinfo(list);
    return fail(last);
}

int64_t kod_tcp_listen(KodStr *host, int64_t port, int64_t backlog) {
    int any = host->len == 0;
    struct addrinfo *list = resolve(any ? NULL : host->buf, port, any ? AF_INET : AF_UNSPEC, 1);
    if (!list) return -1;
    int last = EADDRNOTAVAIL;
    for (struct addrinfo *ai = list; ai; ai = ai->ai_next) {
        int fd = new_socket(ai);
        if (fd < 0) {
            last = errno;
            continue;
        }
        int one = 1;
        setsockopt(fd, SOL_SOCKET, SO_REUSEADDR, &one, sizeof one);
        if (bind(fd, ai->ai_addr, ai->ai_addrlen) == 0 && listen(fd, (int)backlog) == 0) {
            freeaddrinfo(list);
            kod_io_set_errno(0);
            return fd;
        }
        last = errno;
        close(fd);
    }
    freeaddrinfo(list);
    return fail(last);
}

int64_t kod_tcp_accept(int64_t fd) {
    int c;
    do {
        c = accept((int)fd, NULL, NULL);
    } while (c < 0 && errno == EINTR);
    if (c < 0) return fail(errno);
    int one = 1;
    fcntl(c, F_SETFD, FD_CLOEXEC);
    setsockopt(c, SOL_SOCKET, SO_NOSIGPIPE, &one, sizeof one);
    setsockopt(c, IPPROTO_TCP, TCP_NODELAY, &one, sizeof one);
    kod_io_set_errno(0);
    return c;
}

int64_t kod_tcp_port(int64_t fd) {
    struct sockaddr_storage addr;
    socklen_t n = sizeof addr;
    if (getsockname((int)fd, (struct sockaddr *)&addr, &n) < 0) return fail(errno);
    kod_io_set_errno(0);
    if (addr.ss_family == AF_INET6) return ntohs(((struct sockaddr_in6 *)&addr)->sin6_port);
    return ntohs(((struct sockaddr_in *)&addr)->sin_port);
}

int64_t kod_tcp_set_timeout(int64_t fd, int64_t ms) {
    struct timeval tv;
    tv.tv_sec = ms / 1000;
    tv.tv_usec = (ms % 1000) * 1000;
    if (setsockopt((int)fd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof tv) < 0) return fail(errno);
    if (setsockopt((int)fd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof tv) < 0) return fail(errno);
    kod_io_set_errno(0);
    return 0;
}
