/* Reference counting: the heap behind every value Kod allocates. docs/memory-layout.md
 * has the rules generated code follows.
 *
 * Counted objects live in one reserved range, so "is this counted" is a range
 * check on the address, and string literals, vtables and arena memory need no
 * header. The 8 bytes before an object hold a 32-bit count, then a size class
 * and a 24-bit mask of the 8-byte slots that hold references. Bit 22 of the mask
 * marks an array and bit 21 an array whose elements are references. Bit 23 marks an
 * object with references past slot 20: the last word of its block points at a
 * descriptor of them.
 *
 * Build with -DRC_POISON to overwrite freed memory and never reuse it, and to
 * fill memory the caller said it would fill, so a use after free shows up as
 * wrong output or a crash. -DRC_STATS adds counts, printed at exit if KOD_RC_STATS is set. */
#include <stdint.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <sys/mman.h>

#define RC_BASE 0x300000000000ULL
#define RC_SIZE (1ULL << 36)
#define RC_SMALL 64 /* classes 0..63: (i+1)*16 bytes; then powers of two from 2 KB */

typedef struct { uint32_t count; uint32_t info; } RcHdr;

static char *rc_cur, *rc_end;
__attribute__((used)) void *rc_free_lists[128];
#ifdef RC_POISON
static int64_t rc_poisoned;
#endif
#ifdef RC_STATS
static int64_t rc_n_alloc, rc_n_free, rc_live, rc_peak;
#endif

static inline int rc_is_counted(const void *p) {
    return ((uint64_t)p >> 36) == (RC_BASE >> 36);
}

static inline int64_t rc_class_size(int cls) {
    return cls < RC_SMALL ? (int64_t)(cls + 1) * 16 : (int64_t)2048 << (cls - RC_SMALL);
}

#ifdef RC_STATS
static void rc_report(void) {
    if (getenv("KOD_RC_STATS")) {
        fprintf(stderr, "rc: allocs %lld frees %lld live %lld peak %lld bytes, heap used %lld\n",
                (long long)rc_n_alloc, (long long)rc_n_free, (long long)rc_live, (long long)rc_peak,
                (long long)(rc_cur - (char *)RC_BASE));
    }
}
#endif

/* Takes a block the free lists don't have from the reserved range, whose memory
 * the OS gives zeroed. */
__attribute__((noinline)) static void *rc_alloc_fresh(int cls, int64_t mask) {
    if (!rc_cur) {
        void *m = mmap((void *)RC_BASE, RC_SIZE, PROT_READ | PROT_WRITE,
                       MAP_ANON | MAP_PRIVATE | MAP_FIXED | MAP_NORESERVE, -1, 0);
        if (m != (void *)RC_BASE) {
            fprintf(stderr, "rc: can't reserve the counted heap\n");
            abort();
        }
        rc_cur = (char *)RC_BASE;
        rc_end = rc_cur + RC_SIZE;
#ifdef RC_STATS
        atexit(rc_report);
#endif
    }
    int64_t bytes = rc_class_size(cls);
    if (rc_cur + bytes > rc_end) {
        fprintf(stderr, "rc: the counted heap is full\n");
        abort();
    }
    RcHdr *h = (RcHdr *)rc_cur;
    rc_cur += bytes;
    h->count = 1;
    h->info = (uint32_t)cls | ((uint32_t)mask << 8);
    return h + 1;
}

__attribute__((noinline)) static int rc_big_class(int64_t total) {
    int cls = RC_SMALL;
    while (rc_class_size(cls) < total) cls++;
    return cls;
}

/* An object whose memory the caller fills: its bytes are whatever they were. */
void *rc_alloc_raw(int64_t size, int64_t mask) {
    int64_t total = size + 8;
    int cls = total <= 1024 ? (int)((total - 1) >> 4) : rc_big_class(total);
#ifdef RC_STATS
    rc_n_alloc++;
    rc_live += rc_class_size(cls);
    if (rc_live > rc_peak) rc_peak = rc_live;
#endif
    RcHdr *h = (RcHdr *)rc_free_lists[cls];
    if (!h) {
        void *p = rc_alloc_fresh(cls, mask);
#ifdef RC_POISON
        memset(p, 0xDD, (size_t)size);
#endif
        return p;
    }
    rc_free_lists[cls] = *(void **)(h + 1);
    h->count = 1;
    h->info = (uint32_t)cls | ((uint32_t)mask << 8);
    return h + 1;
}

void *rc_alloc(int64_t size, int64_t mask) {
    uint64_t *w = (uint64_t *)rc_alloc_raw(size, mask);
    /* Mostly a few words, and a call to memset would cost more. */
    for (int64_t i = 0; i < (size + 7) >> 3; i++) {
        w[i] = 0;
        __asm__ volatile("" : : : "memory");
    }
    return w;
}

#define RC_BIG_BIT (1u << 23)

/* An object with references past slot 20. `desc` is a count of words, then that many
 * words of bits, one bit per 8-byte slot. */
void *rc_alloc_big(int64_t size, const int64_t *desc) {
    void *p = rc_alloc(size + 8, RC_BIG_BIT);
    RcHdr *h = (RcHdr *)p - 1;
    *(const int64_t **)((char *)h + rc_class_size((int)(h->info & 0xff)) - 8) = desc;
    return p;
}

/* Frees p, whose count reached 0, and whatever only it kept alive. Iterative:
 * a long list must not take the C stack with it. The pending list links
 * through the count word, as an offset (0 ends it: the first header in the
 * heap is never on the list twice, and offset 0 is reserved by a dummy). */
void rc_free_object(void *p) {
    RcHdr *pending = (RcHdr *)p - 1;
    pending->count = 0;
    while (pending) {
        RcHdr *h = pending;
        pending = h->count ? (RcHdr *)((char *)RC_BASE + ((uint64_t)h->count << 4)) : NULL;
        void **slots = (void **)(h + 1);
        uint32_t mask = h->info >> 8;
        if (mask & RC_BIG_BIT) {
            const int64_t *desc =
                *(const int64_t **)((char *)h + rc_class_size((int)(h->info & 0xff)) - 8);
            for (int64_t w = 0; w < desc[0]; w++) {
                uint64_t bits = (uint64_t)desc[w + 1];
                for (int i = 0; bits; i++, bits >>= 1) {
                    if (!(bits & 1)) continue;
                    void *c = slots[w * 64 + i];
                    if (!rc_is_counted(c)) continue;
                    RcHdr *ch = (RcHdr *)c - 1;
                    if (--ch->count == 0) {
                        ch->count = pending ? (uint32_t)(((char *)pending - (char *)RC_BASE) >> 4) : 0;
                        pending = ch;
                    }
                }
            }
            mask = 0;
        } else if (mask & (1u << 22)) {
            /* An array: { ptr, len, cap }. Its buffer has one owner. */
            void **buf = (void **)slots[0];
            if ((mask & (1u << 21)) && buf) {
                int64_t n = (int64_t)slots[1];
                for (int64_t i = 0; i < n; i++) {
                    void *c = buf[i];
                    if (!rc_is_counted(c)) continue;
                    RcHdr *ch = (RcHdr *)c - 1;
                    if (--ch->count == 0) {
                        ch->count = pending ? (uint32_t)(((char *)pending - (char *)RC_BASE) >> 4) : 0;
                        pending = ch;
                    }
                }
            }
            if (rc_is_counted(buf)) {
                RcHdr *bh = (RcHdr *)buf - 1;
                if (--bh->count == 0) {
                    bh->count = pending ? (uint32_t)(((char *)pending - (char *)RC_BASE) >> 4) : 0;
                    pending = bh;
                }
            }
            mask = 0;
        }
        for (int i = 0; mask; i++, mask >>= 1) {
            if (!(mask & 1)) continue;
            void *c = slots[i];
            if (!rc_is_counted(c)) continue;
            RcHdr *ch = (RcHdr *)c - 1;
            if (--ch->count == 0) {
                ch->count = pending ? (uint32_t)(((char *)pending - (char *)RC_BASE) >> 4) : 0;
                pending = ch;
            }
        }
        int cls = (int)(h->info & 0xff);
#ifdef RC_STATS
        rc_n_free++;
        rc_live -= rc_class_size(cls);
#endif
#ifdef RC_POISON
        /* Never reused, and any later read sees rubbish. */
        memset(h + 1, 0xDD, (size_t)rc_class_size(cls) - 8);
        rc_poisoned += rc_class_size(cls);
#else
        *(void **)(h + 1) = rc_free_lists[cls];
        rc_free_lists[cls] = h;
#endif
    }
}

void rc_retain_c(void *p) {
    if (rc_is_counted(p)) ((RcHdr *)p - 1)->count++;
}

void rc_release_c(void *p) {
    if (rc_is_counted(p) && --((RcHdr *)p - 1)->count == 0) rc_free_object(p);
}

/* Called from generated code with the object in x17: everything but x16, x17
 * and lr survives, so a release can sit anywhere in an expression. */
__attribute__((naked)) void rc_free_stub(void) {
    __asm__(
        "stp x0, x1, [sp, #-16]!\n"
        "stp x2, x3, [sp, #-16]!\n"
        "stp x4, x5, [sp, #-16]!\n"
        "stp x6, x7, [sp, #-16]!\n"
        "stp x8, x9, [sp, #-16]!\n"
        "stp x10, x11, [sp, #-16]!\n"
        "stp x12, x13, [sp, #-16]!\n"
        "stp x14, x15, [sp, #-16]!\n"
        "stp fp, lr, [sp, #-16]!\n"
        "mov fp, sp\n"
        "mov x0, x17\n"
        "bl _rc_free_object\n"
        "ldp fp, lr, [sp], #16\n"
        "ldp x14, x15, [sp], #16\n"
        "ldp x12, x13, [sp], #16\n"
        "ldp x10, x11, [sp], #16\n"
        "ldp x8, x9, [sp], #16\n"
        "ldp x6, x7, [sp], #16\n"
        "ldp x4, x5, [sp], #16\n"
        "ldp x2, x3, [sp], #16\n"
        "ldp x0, x1, [sp], #16\n"
        "ret\n");
}

/* What generated code calls, with the object in x17. Only x16, x17 and lr
 * change, and no flags, until an object is freed. */
__attribute__((naked)) void rc_retain_stub(void) {
    __asm__(
        "lsr x16, x17, #36\n"
        "eor x16, x16, #0x300\n"
        "cbnz x16, 1f\n"
        "ldr w16, [x17, #-8]\n"
        "add w16, w16, #1\n"
        "str w16, [x17, #-8]\n"
        "1: ret\n");
}

__attribute__((naked)) void rc_release_stub(void) {
    __asm__(
        "lsr x16, x17, #36\n"
        "eor x16, x16, #0x300\n"
        "cbnz x16, 1f\n"
        "ldr w16, [x17, #-8]\n"
        "sub w16, w16, #1\n"
        "str w16, [x17, #-8]\n"
        "cbnz w16, 1f\n"
#if !defined(RC_POISON) && !defined(RC_STATS)
        /* No references inside: on to its free list, without touching the frame. */
        "ldr w16, [x17, #-4]\n"
        "stp x0, x1, [sp, #-16]!\n"
        "lsr w0, w16, #8\n"
        "cbnz w0, 2f\n"
        "adrp x0, _rc_free_lists@PAGE\n"
        "add x0, x0, _rc_free_lists@PAGEOFF\n"
        "ldr x1, [x0, x16, lsl #3]\n"
        "str x1, [x17]\n"
        "sub x17, x17, #8\n"
        "str x17, [x0, x16, lsl #3]\n"
        "ldp x0, x1, [sp], #16\n"
        "ret\n"
        "2: ldp x0, x1, [sp], #16\n"
        "b _rc_free_stub\n"
#else
        "b _rc_free_stub\n"
#endif
        "1: ret\n");
}

/* Bytes in use: what the heap took from the OS, less what the free lists hold. */
int64_t rc_live_bytes(void) {
    int64_t bytes = rc_cur ? rc_cur - (char *)RC_BASE : 0;
#ifdef RC_POISON
    bytes -= rc_poisoned;
#endif
    for (int cls = 0; cls < 128; cls++) {
        for (RcHdr *h = (RcHdr *)rc_free_lists[cls]; h; h = *(RcHdr **)(h + 1)) {
            bytes -= rc_class_size(cls);
        }
    }
    return bytes;
}
