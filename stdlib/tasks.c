/* The switches behind stdlib/tasks.kod (docs/tasks.md): each task runs on a
 * stack of its own (mapped there), and a switch saves the registers a call
 * keeps and loads another task's; and the ticker thread that has a busy task
 * give way. What the scheduler waits on, and which task runs next, is the
 * Kod side's. */

#include <pthread.h>
#include <stdint.h>
#include <stdlib.h>
#include <unistd.h>

/* Saved registers: x19..x28, fp, lr, sp, d8..d15; and the innermost catch. */
#define KOD_TASK_CTX_WORDS 22

int64_t kod_task_ctx_new(void) {
    return (int64_t)calloc(KOD_TASK_CTX_WORDS, 8);
}

void kod_task_ctx_free(int64_t ctx) {
    free((void *)ctx);
}

/* Where a new task starts: it runs the task through the scheduler's entry for
 * a task's first turn (stdlib/tasks.kod), which switches away for good. The
 * frame chain ends there (fp 0), so a backtrace stops at the task's first
 * call. */
__attribute__((naked)) static void kod_task_entry(void) {
    __asm__(
        "mov fp, #0\n"
        "mov lr, #0\n"
        "bl \"$tasks$_run_current\"\n"
        "brk #1\n");
}

/* Makes `ctx` start kod_task_entry on a stack whose top is `top`. */
void kod_task_ctx_init(int64_t ctx, int64_t top) {
    uint64_t *c = (uint64_t *)ctx;
    c[10] = 0;
    c[11] = (uint64_t)kod_task_entry;
    c[12] = (uint64_t)top;
}

/* Saves this task's registers (and its innermost catch, runtime.c) in `from`
 * and goes on as the task
 * saved in `to`, returning where that one last called this (or into its
 * entry). */
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
        "adrp x9, _kod_catch_top@PAGE\n"
        "ldr x10, [x9, _kod_catch_top@PAGEOFF]\n"
        "str x10, [x0, #168]\n"
        "ldr x10, [x1, #168]\n"
        "str x10, [x9, _kod_catch_top@PAGEOFF]\n"
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

/* The task scheduler's wait (stdlib/tasks.kod), which kod_wait_event calls
 * once a task has been started. */
extern int64_t (*kod_wait_hook)(int64_t ident, int64_t filter, int64_t data);
extern int64_t kod_tasks_wait_event(int64_t ident, int64_t filter, int64_t data) __asm__("$tasks$_wait_event");

/* After a panic's backtrace, where the running task was spawned. */
extern void (*kod_backtrace_hook)(void);
extern void kod_tasks_print_spawn_trace(void) __asm__("$tasks$_print_spawn_trace");

/* A module variable another task is initializing (runtime.c, kod_var_busy). */
extern int64_t kod_task_now;
extern void (*kod_var_wait_hook)(int64_t cell);
extern void (*kod_var_wake_hook)(int64_t cell);
extern void kod_tasks_wait_var(int64_t cell) __asm__("$tasks$_wait_var");
extern void kod_tasks_wake_var(int64_t cell) __asm__("$tasks$_wake_var");

/* A caught panic abandons a function that has spawned tasks. */
extern void (*kod_unwind_group_hook)(void *group);
extern void kod_tasks_unwind_group(void *group) __asm__("$tasks$_unwind_group");

/* A descriptor is about to be closed (runtime.c). */
extern void (*kod_close_hook)(int64_t fd);
extern void kod_tasks_closing(int64_t fd) __asm__("$tasks$_closing");

static void kod_preempt_start(void);

/* A loop's check found it time to give way (runtime.c, kod_poll_stub). */
extern void (*kod_poll_hook)(void);
extern void kod_tasks_poll_due(void) __asm__("$tasks$_poll_due");

void kod_task_hook(void) {
    kod_preempt_start();
    kod_poll_hook = kod_tasks_poll_due;
    kod_unwind_group_hook = kod_tasks_unwind_group;
    kod_wait_hook = kod_tasks_wait_event;
    kod_close_hook = kod_tasks_closing;
    kod_backtrace_hook = kod_tasks_print_spawn_trace;
    kod_var_wait_hook = kod_tasks_wait_var;
    kod_var_wake_hook = kod_tasks_wake_var;
}

/* The task about to run, by its stack (0 for the program's first). */
void kod_task_set_now(int64_t stack) {
    kod_task_now = stack;
}

/* Preemption (docs/tasks.md#preemption). Every 10 ms a ticker thread sets
 * kod_poll_flag, which each loop iteration and function call checks: the check
 * calls kod_poll_stub (runtime.c), which has the task give way. */
#define KOD_PREEMPT_US 10000

extern int64_t kod_poll_flag;
extern int64_t kod_poll_sim;

static void *kod_ticker(void *arg) {
    (void)arg;
    for (;;) {
        usleep(KOD_PREEMPT_US);
        kod_poll_flag = 1;
    }
    return NULL;
}

/* A child made by fork has no ticker: its loops go on undisturbed. */
static void kod_preempt_forked(void) {
    if (!kod_poll_sim) kod_poll_flag = 0;
}

static void kod_preempt_start(void) {
    pthread_atfork(NULL, NULL, kod_preempt_forked);
    pthread_t ticker;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_create(&ticker, &attr, kod_ticker, NULL);
    pthread_attr_destroy(&attr);
}
