/* The stacks and switches behind stdlib/tasks.kod (docs/tasks.md): each task
 * runs on a stack of its own, and a switch saves the registers a call keeps
 * and loads another task's. Which task runs next is the Kod side's choice. */

#include <stdint.h>
#include <stdlib.h>
#include <sys/mman.h>
#include <unistd.h>

/* A task's stack: as much as the first thread has, reserved as address space,
 * with a guard page below it that an overflow faults on. */
#define KOD_TASK_STACK (8 * 1024 * 1024)

/* Saved registers: x19..x28, fp, lr, sp, d8..d15. */
#define KOD_TASK_CTX_WORDS 21

/* The base of a new stack (its guard page), or 0 when there is no room. */
int64_t kod_task_stack_new(void) {
    size_t page = (size_t)getpagesize();
    void *base = mmap(NULL, KOD_TASK_STACK + page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (base == MAP_FAILED) return 0;
    mprotect(base, page, PROT_NONE);
    return (int64_t)base;
}

void kod_task_stack_free(int64_t base) {
    if (base != 0) munmap((void *)base, KOD_TASK_STACK + (size_t)getpagesize());
}

int64_t kod_task_ctx_new(void) {
    return (int64_t)calloc(KOD_TASK_CTX_WORDS, 8);
}

void kod_task_ctx_free(int64_t ctx) {
    free((void *)ctx);
}

/* The task scheduler's entry for a task's first turn (stdlib/tasks.kod). */
extern void kod_tasks_run_current(void) __asm__("$tasks$_run_current");

/* Where a new task starts: it runs the task, which switches away for good. */
static void kod_task_entry(void) {
    kod_tasks_run_current();
    __builtin_trap();
}

/* Makes `ctx` start kod_task_entry on the stack at `base`, its frame chain
 * ending there (fp 0), so backtraces stop at the task's first call. */
void kod_task_ctx_init(int64_t ctx, int64_t base) {
    uint64_t *c = (uint64_t *)ctx;
    c[10] = 0;
    c[11] = (uint64_t)kod_task_entry;
    c[12] = (uint64_t)base + (uint64_t)getpagesize() + KOD_TASK_STACK;
}

/* Saves this task's registers in `from` and goes on as the task saved in
 * `to`, returning where that one last called this (or into its entry). */
__attribute__((naked)) void kod_task_switch(int64_t from, int64_t to) {
    __asm__(
        "stp x19, x20, [x0, #0]\n"
        "stp x21, x22, [x0, #16]\n"
        "stp x23, x24, [x0, #32]\n"
        "stp x25, x26, [x0, #48]\n"
        "stp x27, x28, [x0, #64]\n"
        "stp fp, lr, [x0, #80]\n"
        "mov x9, sp\n"
        "str x9, [x0, #96]\n"
        "stp d8, d9, [x0, #104]\n"
        "stp d10, d11, [x0, #120]\n"
        "stp d12, d13, [x0, #136]\n"
        "stp d14, d15, [x0, #152]\n"
        "ldp x19, x20, [x1, #0]\n"
        "ldp x21, x22, [x1, #16]\n"
        "ldp x23, x24, [x1, #32]\n"
        "ldp x25, x26, [x1, #48]\n"
        "ldp x27, x28, [x1, #64]\n"
        "ldp fp, lr, [x1, #80]\n"
        "ldr x9, [x1, #96]\n"
        "mov sp, x9\n"
        "ldp d8, d9, [x1, #104]\n"
        "ldp d10, d11, [x1, #120]\n"
        "ldp d12, d13, [x1, #136]\n"
        "ldp d14, d15, [x1, #152]\n"
        "ret\n");
}
