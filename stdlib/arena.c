#include <stdint.h>
#include <stdlib.h>

#define BLOCK_SIZE (4 * 1024 * 1024) /* 4 MB */

typedef struct Block {
    char *current;
    char *end;
    struct Block *next;
} Block;

static Block *current_block = NULL;

static Block *new_block(int64_t min_size) {
    int64_t size = BLOCK_SIZE > min_size ? BLOCK_SIZE : min_size;
    Block *b = (Block *)malloc(sizeof(Block) + size);
    b->current = (char *)(b + 1);
    b->end = b->current + size;
    b->next = NULL;
    return b;
}

void *arena_alloc(int64_t size);
int64_t strlen(const char *s);

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

void *arena_alloc(int64_t size) {
    /* Align to 8 bytes */
    size = (size + 7) & ~7;
    if (current_block == NULL || current_block->current + size > current_block->end) {
        Block *b = new_block(size);
        b->next = current_block;
        current_block = b;
    }
    void *ptr = current_block->current;
    current_block->current += size;
    return ptr;
}
