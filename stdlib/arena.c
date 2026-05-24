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

/* Free every block. Caller is responsible for ensuring no live Kod-side
 * pointers reference arena-allocated data — anything previously returned
 * by `arena_alloc` is dangling once this returns. Used by the LSP to
 * recover the parse-tree / codegen memory of the previous compile
 * before starting a new one. */
void arena_reset(void) {
    Block *b = current_block;
    while (b) {
        Block *next = b->next;
        free(b);
        b = next;
    }
    current_block = NULL;
}
