// The C side of inflate.kod: decompression with the system's zlib. A call
// returns the output, or an empty string after leaving a status for
// kod_inflate_status: 0 ok, 1 invalid data (message in kod_inflate_message),
// 2 output over the limit, 3 out of memory.
#include "kod_rt.h"

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <zlib.h>

static int64_t g_status;
static char g_message[128];

int64_t kod_inflate_status(void) { return g_status; }

KodStr *kod_inflate_message(void) {
    return kod_str_from_bytes(g_message, (int64_t)strlen(g_message));
}

static KodStr *failed(int64_t status, const char *message) {
    g_status = status;
    snprintf(g_message, sizeof g_message, "%s", message ? message : "");
    return kod_str_new(0);
}

// mode: 0 gzip (members one after another), 1 zlib, 2 raw deflate. The result
// may have at most `max_output` bytes (not negative). The buffer never grows
// past one byte more than that, so an overrun is seen as soon as it happens.
KodStr *kod_inflate(KodStr *input, int64_t mode, int64_t max_output) {
    z_stream zs;
    memset(&zs, 0, sizeof zs);
    int window = mode == 0 ? 15 + 16 : (mode == 1 ? 15 : -15);
    if (inflateInit2(&zs, window) != Z_OK) return failed(3, "out of memory");

    size_t limit = (size_t)max_output;
    size_t cap = limit < 4096 ? limit + 1 : 4096;
    size_t len = 0;
    unsigned char *out = (unsigned char *)malloc(cap);
    if (!out) {
        inflateEnd(&zs);
        return failed(3, "out of memory");
    }
    zs.next_in = (Bytef *)input->buf;
    zs.avail_in = (uInt)input->len;

    int ended = 0;
    for (;;) {
        if (len == cap) {
            size_t grown = cap * 2;
            if (grown > limit + 1) grown = limit + 1;
            unsigned char *bigger = grown > cap ? (unsigned char *)realloc(out, grown) : NULL;
            if (!bigger) {
                free(out);
                inflateEnd(&zs);
                return grown > cap ? failed(3, "out of memory") : failed(2, "output too large");
            }
            out = bigger;
            cap = grown;
        }
        size_t room = cap - len;
        zs.next_out = out + len;
        zs.avail_out = (uInt)(room > (1u << 30) ? (1u << 30) : room);
        uInt before = zs.avail_out;
        int rc = inflate(&zs, Z_NO_FLUSH);
        len += before - zs.avail_out;
        if (len > limit) {
            free(out);
            inflateEnd(&zs);
            return failed(2, "output too large");
        }
        if (rc == Z_STREAM_END) {
            if (mode == 0 && zs.avail_in > 0) {
                if (inflateReset(&zs) != Z_OK) {
                    free(out);
                    inflateEnd(&zs);
                    return failed(1, "bad stream state");
                }
                continue;
            }
            ended = 1;
            break;
        }
        if (rc == Z_BUF_ERROR && zs.avail_in == 0) break;
        if (rc != Z_OK && rc != Z_BUF_ERROR) {
            const char *msg = rc == Z_MEM_ERROR ? "out of memory" : (zs.msg ? zs.msg : "invalid data");
            free(out);
            inflateEnd(&zs);
            return failed(rc == Z_MEM_ERROR ? 3 : 1, msg);
        }
    }
    inflateEnd(&zs);
    if (!ended) {
        free(out);
        return failed(1, "truncated");
    }
    KodStr *result = kod_str_from_bytes((const char *)out, (int64_t)len);
    free(out);
    g_status = 0;
    return result;
}
