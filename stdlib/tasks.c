/* The stacks and switches behind stdlib/tasks.kod (docs/tasks.md): each task
 * runs on a stack of its own, and a switch saves the registers a call keeps
 * and loads another task's. Which task runs next is the Kod side's choice. */

#include <errno.h>
#include <pthread.h>
#include <signal.h>
#include <stdint.h>
#include <stdlib.h>
#include <sys/event.h>
#include <sys/mman.h>
#include <sys/ucontext.h>
#include <time.h>
#include <unistd.h>

/* A task's stack: as much as the first thread has, reserved as address space,
 * with a guard page below it that an overflow faults on. */
#define KOD_TASK_STACK (8 * 1024 * 1024)

/* Saved registers: x19..x28, fp, lr, sp, d8..d15; and the innermost catch. */
#define KOD_TASK_CTX_WORDS 22

/* Stacks of tasks that have ended, kept for the next ones: mapping a stack and
 * touching its first pages costs more than the rest of starting a task. */
#define KOD_TASK_STACKS_KEPT 64
#define KOD_TASK_STACK_HOT (256 * 1024)
static int64_t kod_stacks_kept[KOD_TASK_STACKS_KEPT];
static int kod_stacks_kept_n = 0;

/* The base of a new stack (its guard page), or 0 when there is no room. */
int64_t kod_task_stack_new(void) {
    if (kod_stacks_kept_n > 0) return kod_stacks_kept[--kod_stacks_kept_n];
    size_t page = (size_t)getpagesize();
    void *base = mmap(NULL, KOD_TASK_STACK + page, PROT_READ | PROT_WRITE, MAP_PRIVATE | MAP_ANON, -1, 0);
    if (base == MAP_FAILED) return 0;
    mprotect(base, page, PROT_NONE);
    return (int64_t)base;
}

void kod_task_stack_free(int64_t base) {
    if (base == 0) return;
    if (kod_stacks_kept_n < KOD_TASK_STACKS_KEPT) {
        /* Its top pages are what most tasks use. When the task went deeper (the
         * page below them is in memory), the memory of the rest goes back to the
         * system. */
        size_t page = (size_t)getpagesize();
        char *below = (char *)base + page + KOD_TASK_STACK - KOD_TASK_STACK_HOT - page;
        char resident = 0;
        if (mincore(below, page, &resident) == 0 && (resident & MINCORE_INCORE)) {
            madvise((void *)(base + (int64_t)page), KOD_TASK_STACK - KOD_TASK_STACK_HOT, MADV_FREE);
        }
        kod_stacks_kept[kod_stacks_kept_n++] = base;
        return;
    }
    munmap((void *)base, KOD_TASK_STACK + (size_t)getpagesize());
}

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

/* Makes `ctx` start kod_task_entry on the stack at `base`. */
void kod_task_ctx_init(int64_t ctx, int64_t base) {
    uint64_t *c = (uint64_t *)ctx;
    c[10] = 0;
    c[11] = (uint64_t)kod_task_entry;
    c[12] = (uint64_t)base + (uint64_t)getpagesize() + KOD_TASK_STACK;
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

/* Waiting for events: one kqueue for the program, each registration one-shot,
 * its udata the key the scheduler finds the waiting task by. */
static int kod_kq = -1;
static struct kevent kod_events[64];
/* Registrations of descriptors that go along with the next wait, so that most cost
 * no call of their own. One that kevent doesn't take comes back as an event. */
static struct kevent kod_changes[64];
static int kod_changes_n = 0;

extern int kod_wait_file;

/* The keys last registered for each descriptor, to read it and to write to it:
 * who may wait for it. */
static int64_t *kod_fd_keys = NULL;
static int64_t kod_fd_keys_n = 0;

/* The key for reading (0) or writing (1) the descriptor, which is forgotten, as is
 * a registration still to be made; 0 for none. */
int64_t kod_task_fd_key(int64_t fd, int64_t writes) {
    int kept = 0;
    for (int i = 0; i < kod_changes_n; i++) {
        struct kevent *ev = &kod_changes[i];
        if ((int64_t)ev->ident == fd && ev->filter == (writes ? EVFILT_WRITE : EVFILT_READ)) continue;
        kod_changes[kept++] = *ev;
    }
    kod_changes_n = kept;
    int64_t at = 2 * fd + writes;
    if (fd < 0 || at >= kod_fd_keys_n) return 0;
    int64_t key = kod_fd_keys[at];
    kod_fd_keys[at] = 0;
    return key;
}

static void kod_fd_keys_set(int64_t fd, int64_t writes, int64_t key) {
    int64_t at = 2 * fd + writes;
    if (fd < 0) return;
    if (at >= kod_fd_keys_n) {
        int64_t n = 2 * at + 128;
        int64_t *grown = realloc(kod_fd_keys, (size_t)n * sizeof *grown);
        if (!grown) return;
        for (int64_t i = kod_fd_keys_n; i < n; i++) grown[i] = 0;
        kod_fd_keys = grown;
        kod_fd_keys_n = n;
    }
    kod_fd_keys[at] = key;
}

/* Registers `filter` on `ident` (a timer is named by `key`, as its ident is
 * free); -1 when it can't come, as for a child that has already exited or a
 * file. Whether a descriptor's can is only known at the next wait
 * (kod_task_kq_failed). */
int64_t kod_task_kq_add(int64_t ident, int64_t filter, int64_t data, int64_t key) {
    if ((filter == EVFILT_READ || filter == EVFILT_WRITE) && kod_wait_file) return -1;
    if (kod_kq < 0) kod_kq = kqueue();
    if (kod_kq < 0) return -1;
    uint32_t fflags = 0;
    if (filter == EVFILT_PROC) fflags = NOTE_EXIT;
    if (filter == EVFILT_TIMER) {
        fflags = NOTE_NSECONDS;
        ident = key;
    }
    struct kevent ev, out;
    EV_SET(&ev, (uintptr_t)ident, (int16_t)filter, EV_ADD | EV_ONESHOT | EV_RECEIPT, fflags, data, (void *)key);
    if (filter == EVFILT_READ || filter == EVFILT_WRITE) {
        /* In place of one that a cancelled task left: made later, that would undo this. */
        int at = 0;
        while (at < kod_changes_n && (kod_changes[at].ident != ev.ident || kod_changes[at].filter != ev.filter)) at++;
        if (at < 64) {
            kod_changes[at] = ev;
            kod_changes[at].flags = EV_ADD | EV_ONESHOT;
            if (at == kod_changes_n) kod_changes_n++;
            kod_fd_keys_set(ident, filter == EVFILT_WRITE, key);
            return 0;
        }
    }
    int n;
    do {
        n = kevent(kod_kq, &ev, 1, &out, 1, NULL);
    } while (n < 0 && errno == EINTR);
    if (n < 0) return -1;
    if (n == 1 && (out.flags & EV_ERROR) && out.data != 0) return -1;
    if (filter == EVFILT_READ || filter == EVFILT_WRITE) kod_fd_keys_set(ident, filter == EVFILT_WRITE, key);
    return 0;
}

/* Takes back a timer that has yet to come. */
void kod_task_kq_drop_timer(int64_t key) {
    struct kevent ev;
    EV_SET(&ev, (uintptr_t)key, EVFILT_TIMER, EV_DELETE, 0, 0, NULL);
    kevent(kod_kq, &ev, 1, NULL, 0, NULL);
}

/* Waits for events, until one comes when `block`, else not at all: how many
 * came; kod_task_kq_key gives each one's key. */
int64_t kod_task_kq_wait(int64_t block) {
    if (kod_kq < 0) return 0;
    struct timespec zero = {0, 0};
    int n;
    do {
        n = kevent(kod_kq, kod_changes, kod_changes_n, kod_events, 64, block ? NULL : &zero);
        /* Whatever it returns, it has been through them all. */
        kod_changes_n = 0;
    } while (n < 0 && errno == EINTR);
    return n < 0 ? 0 : n;
}

int64_t kod_task_kq_key(int64_t i) {
    return (int64_t)kod_events[i].udata;
}

/* Whether event `i` says that its registration wasn't taken. */
int64_t kod_task_kq_failed(int64_t i) {
    return (kod_events[i].flags & EV_ERROR) != 0;
}

int64_t kod_task_kq_data(int64_t i) {
    return (int64_t)kod_events[i].data;
}

/* What kod_wait_room answers (runtime.c), for the task that goes on. */
extern int64_t kod_room;
void kod_task_set_room(int64_t room) {
    kod_room = room;
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
static void kod_poll_due(void);

void kod_task_hook(void) {
    kod_preempt_start();
    kod_poll_hook = kod_poll_due;
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
 * kod_poll_flag, which each loop iteration checks (runtime.c, kod_poll_stub).
 * Code compiled before that check, the snapshot's, loads from the polling page
 * instead, which the ticker makes unreadable: the fault handler makes it
 * readable again and has the task go on in kod_preempt_stub, past the load,
 * which keeps every register while the task gives way. */
#define KOD_POLL_PAGE 16384
#define KOD_PREEMPT_US 10000
/* Where the task goes on once it has given way: set by the fault handler,
 * read by kod_preempt_stub before anything can fault again. */
uint64_t kod_preempt_resume = 0;

extern char kod_poll_page[KOD_POLL_PAGE];
extern int64_t kod_poll_flag;
extern int64_t kod_poll_sim;
/* Set while a panic's backtrace is being kept (runtime.c). */
extern int kod_no_preempt;
static struct sigaction kod_old_segv, kod_old_bus;

static void *kod_ticker(void *arg) {
    (void)arg;
    for (;;) {
        usleep(KOD_PREEMPT_US);
        /* The page first: a task that sees the flag makes the page readable
         * again (kod_poll_due), which must not come before this. */
        mprotect(kod_poll_page, KOD_POLL_PAGE, PROT_NONE);
        kod_poll_flag = 1;
    }
    return NULL;
}

/* The running task gives way (stdlib/tasks.kod). */
extern void kod_tasks_preempt(void) __asm__("$tasks$_preempt");

/* Entered in place of the instruction after the faulting load. Below the
 * task's red zone, it keeps kod_preempt_resume, the address to go on at; it
 * saves what a call may change (x0-x17, lr, the flags, all of q0-q31 and the
 * FP status), makes a frame record whose return address is that address, so a
 * backtrace from inside reads as the loop's, calls kod_tasks_preempt, and
 * restores them. Only x16 differs after: it held the polling page's address,
 * which nothing reads again. */
__attribute__((naked)) static void kod_preempt_stub(void) {
    __asm__(
        "sub sp, sp, #144\n"
        "adrp x16, _kod_preempt_resume@PAGE\n"
        "ldr x16, [x16, _kod_preempt_resume@PAGEOFF]\n"
        "str x16, [sp]\n"
        "sub sp, sp, #688\n"
        "stp x0, x1, [sp, #0]\n"
        "stp x2, x3, [sp, #16]\n"
        "stp x4, x5, [sp, #32]\n"
        "stp x6, x7, [sp, #48]\n"
        "stp x8, x9, [sp, #64]\n"
        "stp x10, x11, [sp, #80]\n"
        "stp x12, x13, [sp, #96]\n"
        "stp x14, x15, [sp, #112]\n"
        "str x17, [sp, #128]\n"
        "mrs x9, nzcv\n"
        "mrs x10, fpsr\n"
        "stp x9, x10, [sp, #136]\n"
        "str x30, [sp, #152]\n"
        "stp q0, q1, [sp, #160]\n"
        "stp q2, q3, [sp, #192]\n"
        "stp q4, q5, [sp, #224]\n"
        "stp q6, q7, [sp, #256]\n"
        "stp q8, q9, [sp, #288]\n"
        "stp q10, q11, [sp, #320]\n"
        "stp q12, q13, [sp, #352]\n"
        "stp q14, q15, [sp, #384]\n"
        "stp q16, q17, [sp, #416]\n"
        "stp q18, q19, [sp, #448]\n"
        "stp q20, q21, [sp, #480]\n"
        "stp q22, q23, [sp, #512]\n"
        "stp q24, q25, [sp, #544]\n"
        "stp q26, q27, [sp, #576]\n"
        "stp q28, q29, [sp, #608]\n"
        "stp q30, q31, [sp, #640]\n"
        /* The frame record: the task's fp, and where it goes on. */
        "ldr x9, [sp, #688]\n"
        "add x10, sp, #672\n"
        "stp x29, x9, [x10]\n"
        "mov x29, x10\n"
        "bl \"$tasks$_preempt\"\n"
        "ldr x29, [sp, #672]\n"
        "ldp q30, q31, [sp, #640]\n"
        "ldp q28, q29, [sp, #608]\n"
        "ldp q26, q27, [sp, #576]\n"
        "ldp q24, q25, [sp, #544]\n"
        "ldp q22, q23, [sp, #512]\n"
        "ldp q20, q21, [sp, #480]\n"
        "ldp q18, q19, [sp, #448]\n"
        "ldp q16, q17, [sp, #416]\n"
        "ldp q14, q15, [sp, #384]\n"
        "ldp q12, q13, [sp, #352]\n"
        "ldp q10, q11, [sp, #320]\n"
        "ldp q8, q9, [sp, #288]\n"
        "ldp q6, q7, [sp, #256]\n"
        "ldp q4, q5, [sp, #224]\n"
        "ldp q2, q3, [sp, #192]\n"
        "ldp q0, q1, [sp, #160]\n"
        "ldr x30, [sp, #152]\n"
        "ldp x9, x10, [sp, #136]\n"
        "msr nzcv, x9\n"
        "msr fpsr, x10\n"
        "ldr x17, [sp, #128]\n"
        "ldp x14, x15, [sp, #112]\n"
        "ldp x12, x13, [sp, #96]\n"
        "ldp x10, x11, [sp, #80]\n"
        "ldp x8, x9, [sp, #64]\n"
        "ldp x6, x7, [sp, #48]\n"
        "ldp x4, x5, [sp, #32]\n"
        "ldp x2, x3, [sp, #16]\n"
        "ldp x0, x1, [sp, #0]\n"
        "add sp, sp, #688\n"
        "ldr x16, [sp]\n"
        "add sp, sp, #144\n"
        "br x16\n");
}

/* The ticker's flag has had a task give way: the page it made unreadable
 * at the same time is readable again, or the next check of code compiled
 * before the flag (the snapshot's) would have the task give way again at
 * once. Likewise a fault on the page clears the flag. */
static void kod_poll_due(void) {
    if (!kod_poll_sim) mprotect(kod_poll_page, KOD_POLL_PAGE, PROT_READ | PROT_WRITE);
    kod_tasks_poll_due();
}

/* A fault on the polling page sends the task into kod_preempt_stub; any
 * other goes to what was there before, by default ending the program. */
static void kod_poll_fault(int sig, siginfo_t *info, void *context) {
    char *at = (char *)info->si_addr;
    if (at >= kod_poll_page && at < kod_poll_page + KOD_POLL_PAGE) {
        mprotect(kod_poll_page, KOD_POLL_PAGE, PROT_READ | PROT_WRITE);
        if (!kod_poll_sim) kod_poll_flag = 0;
        if (kod_no_preempt) return;
        /* The signal's frame is below the task's sp: nothing is written there. */
        _STRUCT_ARM_THREAD_STATE64 *ts = &((ucontext_t *)context)->uc_mcontext->__ss;
        kod_preempt_resume = ts->__pc + 4;
        ts->__pc = (uint64_t)kod_preempt_stub;
        return;
    }
    sigaction(SIGSEGV, &kod_old_segv, NULL);
    sigaction(SIGBUS, &kod_old_bus, NULL);
}

/* A child made by fork has no ticker: its loops go on undisturbed. */
static void kod_preempt_forked(void) {
    if (!kod_poll_sim) kod_poll_flag = 0;
    mprotect(kod_poll_page, KOD_POLL_PAGE, PROT_READ | PROT_WRITE);
}

static void kod_preempt_start(void) {
    pthread_atfork(NULL, NULL, kod_preempt_forked);
    struct sigaction sa;
    sa.sa_sigaction = kod_poll_fault;
    sigemptyset(&sa.sa_mask);
    sa.sa_flags = SA_SIGINFO;
    sigaction(SIGSEGV, &sa, &kod_old_segv);
    sigaction(SIGBUS, &sa, &kod_old_bus);
    pthread_t ticker;
    pthread_attr_t attr;
    pthread_attr_init(&attr);
    pthread_attr_setdetachstate(&attr, PTHREAD_CREATE_DETACHED);
    pthread_create(&ticker, &attr, kod_ticker, NULL);
    pthread_attr_destroy(&attr);
}
