// The C side of tests/link/zlib_crc.kod: zlib's CRC-32 of a Kod str.
#include "kod_rt.h"

#include <zlib.h>

int64_t kod_zlib_crc32(KodStr *s) {
    uLong crc = crc32(0L, Z_NULL, 0);
    crc = crc32(crc, (const Bytef *)s->buf, (uInt)s->len);
    return (int64_t)crc;
}
