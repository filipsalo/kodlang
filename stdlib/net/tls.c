// The C side of tls.kod: a client TLS session over a connected descriptor,
// using SecureTransport. A call returns its result, or -1 after leaving a
// status for kod_tls_status: 1 an OS error (the number is in
// kod_io_set_errno's slot), 2 a TLS failure described by kod_tls_message.
#include "kod_rt.h"

#include <errno.h>
#include <stdio.h>
#include <string.h>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/time.h>
#include <unistd.h>

#include <CoreFoundation/CoreFoundation.h>
#include <Security/Security.h>
#include <Security/SecureTransport.h>

#pragma clang diagnostic ignored "-Wdeprecated-declarations"

static int64_t g_status;
static char g_message[512];

int64_t kod_tls_status(void) { return g_status; }

KodStr *kod_tls_message(void) {
    return kod_str_from_bytes(g_message, (int64_t)strlen(g_message));
}

typedef struct {
    int fd;
    int io_errno; // the errno behind the last callback failure, if any
    int timed_out;
    int clean_eof; // the peer closed between two records
} Conn;

static int64_t os_failure(int err) {
    g_status = 1;
    kod_io_set_errno(err);
    return -1;
}

static int64_t tls_failure(const char *what, OSStatus code) {
    g_status = 2;
    CFStringRef text = SecCopyErrorMessageString(code, NULL);
    if (text && CFStringGetCString(text, g_message, sizeof g_message, kCFStringEncodingUTF8)) {
        // keep the text from the framework
    } else {
        snprintf(g_message, sizeof g_message, "%s (OSStatus %d)", what, (int)code);
    }
    if (text) CFRelease(text);
    return -1;
}

static int64_t tls_failure_text(const char *text) {
    g_status = 2;
    snprintf(g_message, sizeof g_message, "%s", text);
    return -1;
}

static OSStatus read_cb(SSLConnectionRef ref, void *data, size_t *len) {
    Conn *c = (Conn *)ref;
    size_t want = *len, got = 0;
    while (got < want) {
        ssize_t n = read(c->fd, (char *)data + got, want - got);
        if (n > 0) {
            got += (size_t)n;
        } else if (n == 0) {
            if (got == 0) c->clean_eof = 1;
            *len = got;
            return errSSLClosedGraceful;
        } else if (errno == EINTR) {
            continue;
        } else {
            *len = got;
            if (errno == EAGAIN) {
                c->timed_out = 1;
                return errSSLWouldBlock;
            }
            c->io_errno = errno;
            return errSecIO;
        }
    }
    *len = got;
    return noErr;
}

static OSStatus write_cb(SSLConnectionRef ref, const void *data, size_t *len) {
    Conn *c = (Conn *)ref;
    size_t want = *len, put = 0;
    while (put < want) {
        ssize_t n = write(c->fd, (const char *)data + put, want - put);
        if (n > 0) {
            put += (size_t)n;
        } else if (n < 0 && errno == EINTR) {
            continue;
        } else {
            *len = put;
            if (n < 0 && errno == EAGAIN) {
                c->timed_out = 1;
                return errSSLWouldBlock;
            }
            c->io_errno = n < 0 ? errno : EPIPE;
            return errSecIO;
        }
    }
    *len = put;
    return noErr;
}

typedef struct {
    SSLContextRef ctx;
    Conn conn;
    int eof; // the stream has ended; reads return nothing
} Session;

// Turn a failed SecureTransport call into the status for Kod.
static int64_t failed(Session *s, OSStatus st, const char *what) {
    if (s->conn.timed_out) {
        s->conn.timed_out = 0;
        return os_failure(EAGAIN);
    }
    if (st == errSecIO && s->conn.io_errno != 0) {
        int err = s->conn.io_errno;
        s->conn.io_errno = 0;
        return os_failure(err);
    }
    if (st == errSSLClosedGraceful || st == errSSLClosedNoNotify || st == errSSLClosedAbort) {
        return tls_failure_text("connection closed");
    }
    return tls_failure(what, st);
}

// The certificates in the PEM file at `path`, or NULL with the failure set.
static CFArrayRef load_certificates(const char *path) {
    FILE *fp = fopen(path, "rb");
    if (!fp) {
        os_failure(errno);
        return NULL;
    }
    fseek(fp, 0, SEEK_END);
    long size = ftell(fp);
    fseek(fp, 0, SEEK_SET);
    if (size < 0 || size > (16 << 20)) {
        fclose(fp);
        tls_failure_text("trust file is too large");
        return NULL;
    }
    UInt8 *bytes = (UInt8 *)malloc((size_t)size + 1);
    size_t got = bytes ? fread(bytes, 1, (size_t)size, fp) : 0;
    fclose(fp);
    if (!bytes || got != (size_t)size) {
        free(bytes);
        os_failure(EIO);
        return NULL;
    }
    CFDataRef data = CFDataCreate(NULL, bytes, (CFIndex)size);
    free(bytes);
    SecExternalFormat format = kSecFormatPEMSequence;
    SecExternalItemType type = kSecItemTypeCertificate;
    CFArrayRef items = NULL;
    OSStatus st = SecItemImport(data, NULL, &format, &type, 0, NULL, NULL, &items);
    CFRelease(data);
    if (st != errSecSuccess || !items || CFArrayGetCount(items) == 0) {
        if (items) CFRelease(items);
        tls_failure_text("trust file holds no certificate");
        return NULL;
    }
    return items;
}

// With a trust file the handshake stops after the server's certificates
// arrive, and they are checked against only those anchors.
static int64_t check_trust(Session *s, CFArrayRef anchors) {
    SecTrustRef trust = NULL;
    OSStatus st = SSLCopyPeerTrust(s->ctx, &trust);
    if (st != errSecSuccess || !trust) return tls_failure("no server certificate", st);
    SecTrustSetAnchorCertificates(trust, anchors);
    SecTrustSetAnchorCertificatesOnly(trust, true);
    CFErrorRef error = NULL;
    bool ok = SecTrustEvaluateWithError(trust, &error);
    int64_t rc = 0;
    if (!ok) {
        rc = tls_failure_text("certificate is not trusted");
        if (error) {
            CFStringRef text = CFErrorCopyDescription(error);
            if (text) {
                CFStringGetCString(text, g_message, sizeof g_message, kCFStringEncodingUTF8);
                CFRelease(text);
            }
        }
    }
    if (error) CFRelease(error);
    CFRelease(trust);
    return rc;
}

// Handshake on `fd` for `host`. Returns a session handle, or -1.
int64_t kod_tls_open(int64_t fd, KodStr *host, KodStr *trust_file) {
    CFArrayRef anchors = NULL;
    if (trust_file->len > 0) {
        anchors = load_certificates(trust_file->buf);
        if (!anchors) return -1;
    }
    Session *s = (Session *)calloc(1, sizeof(Session));
    if (!s) {
        if (anchors) CFRelease(anchors);
        return os_failure(ENOMEM);
    }
    s->conn.fd = (int)fd;
    s->ctx = SSLCreateContext(NULL, kSSLClientSide, kSSLStreamType);
    OSStatus st = s->ctx ? noErr : errSecAllocate;
    if (st == noErr) st = SSLSetIOFuncs(s->ctx, read_cb, write_cb);
    if (st == noErr) st = SSLSetConnection(s->ctx, &s->conn);
    if (st == noErr) st = SSLSetProtocolVersionMin(s->ctx, kTLSProtocol12);
    if (st == noErr) st = SSLSetPeerDomainName(s->ctx, host->buf, (size_t)host->len);
    if (st == noErr && anchors) st = SSLSetSessionOption(s->ctx, kSSLSessionOptionBreakOnServerAuth, true);
    int64_t rc = 0;
    if (st != noErr) {
        rc = tls_failure("could not set up the session", st);
    } else {
        for (;;) {
            st = SSLHandshake(s->ctx);
            if (st == errSSLServerAuthCompleted) {
                rc = check_trust(s, anchors);
                if (rc < 0) break;
                continue;
            }
            if (st != noErr) rc = failed(s, st, "TLS handshake failed");
            break;
        }
    }
    if (anchors) CFRelease(anchors);
    if (rc < 0) {
        CFRelease(s->ctx);
        free(s);
        return -1;
    }
    g_status = 0;
    return (int64_t)s;
}

// At most `max` bytes (never more than 64 KiB); empty at the end of the stream.
// SSLRead gets one byte first, so it returns as soon as a record is in; the
// rest of what it has decrypted is then taken without waiting. A peer that
// closes right after its last record, without a close notice, makes SSLRead
// fail although the data is buffered, so the buffer is drained before the
// error counts. A close between records is the end of the stream.
KodStr *kod_tls_read(int64_t handle, int64_t max) {
    Session *s = (Session *)handle;
    char chunk[65536];
    g_status = 0;
    if (max > (int64_t)sizeof chunk) max = (int64_t)sizeof chunk;
    if (max <= 0 || s->eof) return kod_str_new(0);
    size_t got = 0;
    OSStatus st = SSLRead(s->ctx, chunk, 1, &got);
    size_t buffered = 0;
    SSLGetBufferedReadSize(s->ctx, &buffered);
    int closed = st == errSSLClosedGraceful || st == errSSLClosedNoNotify || st == errSSLClosedAbort;
    if (got + buffered > 0) {
        size_t room = (size_t)max - got;
        size_t ask = buffered < room ? buffered : room;
        size_t more = 0;
        if (ask > 0 && SSLRead(s->ctx, chunk + got, ask, &more) == noErr) got += more;
        if (closed) s->eof = 1;
        return kod_str_from_bytes(chunk, (int64_t)got);
    }
    if (st == errSSLClosedGraceful || st == errSSLClosedNoNotify ||
        (st == errSSLClosedAbort && s->conn.clean_eof)) {
        s->eof = 1;
        return kod_str_new(0);
    }
    if (st == errSSLClosedAbort) {
        tls_failure_text("connection closed in the middle of a record");
        return kod_str_new(0);
    }
    failed(s, st, "TLS read failed");
    return kod_str_new(0);
}

// Bytes written (all of `data`), or -1.
int64_t kod_tls_write(int64_t handle, KodStr *data) {
    Session *s = (Session *)handle;
    g_status = 0;
    if (data->len == 0) return 0;
    size_t done = 0;
    OSStatus st = SSLWrite(s->ctx, data->buf, (size_t)data->len, &done);
    if (st != noErr) return failed(s, st, "TLS write failed");
    return (int64_t)done;
}

// Send the close notice and free the session. The descriptor stays open.
void kod_tls_close(int64_t handle) {
    Session *s = (Session *)handle;
    SSLClose(s->ctx);
    CFRelease(s->ctx);
    free(s);
}
