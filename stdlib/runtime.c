#include <errno.h>
#include <fcntl.h>
#include <math.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/sysctl.h>
#include <sys/time.h>
#include <sys/wait.h>
#include <time.h>
#include <pthread.h>
#include <setjmp.h>
#include <unistd.h>

#include "kod_rt.h"

#if defined(__ARM_FEATURE_CRC32)
#include <arm_acle.h>
#endif


// Defined in stdlib/kod/inspect.kod. Both panic handlers call it
// inline with `__builtin_frame_address(0)` (NOT through a wrapper —
// see the longer note where the asm-label declaration lives).
extern void kod_inspect_print_backtrace_from(int64_t fp)
    __asm__("$kod$inspect$print_backtrace_from");

// Preemption (docs/tasks.md#preemption): each loop iteration and function
// call loads kod_poll_flag (codegen.kod, emit_poll) and, when it is set, calls
// kod_poll_stub, which counts kod_poll_budget down and at 0 calls
// kod_poll_hook (stdlib/tasks.kod, _poll_due). Every 10 ms a thread sets the
// flag (tasks.c), and the hook clears it and gives way; a simulation
// (stdlib/sim.kod) keeps it set, so that the countdown, which the seed sets,
// counts every check, and a task gives way at the same check each time.
int64_t kod_poll_flag = 0;
int64_t kod_poll_budget = 1;
void (*kod_poll_hook)(void) = 0;
// A store to what other tasks can reach (a shared struct's field, a module
// variable) sets kod_poll_stored (codegen.kod, emit_store_mark); the next check
// that finds it set clears it and counts kod_poll_store_budget down as well,
// so that under a simulation a task is preempted more often right after it
// changed what another may read. Outside one that countdown never runs out.
int64_t kod_poll_stored = 0;
int64_t kod_poll_store_budget = (int64_t)1 << 62;
// Under a simulation: what a module variable's initializer runs isn't counted
// (kod_poll_hold), so that a seed preempts at the same checks whether or not an
// earlier run worked the variable out. How many initializers are under way, and
// the countdown the outermost one put aside.
int64_t kod_poll_sim = 0;
int64_t kod_poll_held = 0;
int64_t kod_poll_kept = 0;
int64_t kod_poll_store_kept = 0;

void kod_poll_set(int64_t flag, int64_t budget, int64_t store_budget) {
    kod_poll_flag = flag;
    kod_poll_budget = budget;
    kod_poll_store_budget = store_budget;
}

// Under a simulation, which counted objects other tasks can reach: a byte for
// each 16 bytes of the counted heap (stdlib/rc.c), set by kod_sim_reach. Address
// space only; pages are touched as objects are marked, and each run starts
// with none.
#define KOD_RC_BASE 0x300000000000ULL
#define KOD_REACH_BYTES (1ULL << 32)
uint8_t *kod_reach_map = 0;

void kod_poll_simulate(int64_t on) {
    kod_poll_sim = on;
    kod_poll_held = 0;
    // What was stored before doesn't count in the run.
    kod_poll_stored = 0;
    if (kod_reach_map) {
        munmap(kod_reach_map, KOD_REACH_BYTES);
        kod_reach_map = 0;
    }
    if (on) {
        void *m = mmap(0, KOD_REACH_BYTES, PROT_READ | PROT_WRITE, MAP_ANON | MAP_PRIVATE | MAP_NORESERVE, -1, 0);
        kod_reach_map = m == MAP_FAILED ? 0 : (uint8_t *)m;
    }
}

static inline int kod_is_counted(const void *p) {
    return ((uint64_t)p >> 36) == (KOD_RC_BASE >> 36);
}

// `p`, and every counted object it refers to, can be reached by another task
// (`spawn` hands it over): stores to them count as the simulation's (see
// kod_poll_stored). The references are the ones rc.c follows when it frees an
// object: the header's mask, an array's elements, a big object's descriptor.
void kod_sim_reach(void *p) {
    if (!kod_reach_map) return;
    int64_t cap = 1024, n = 0, seen = 0;
    void **stack = malloc((size_t)cap * sizeof(void *));
    stack[n++] = p;
    while (n > 0 && seen < 1000000) {
        void *o = stack[--n];
        if (!kod_is_counted(o)) continue;
        uint8_t *mark = kod_reach_map + (((uint64_t)o & 0xfffffffffULL) >> 4);
        if (*mark) continue;
        *mark = 1;
        seen++;
        uint32_t info = ((uint32_t *)o)[-1];
        uint32_t mask = info >> 8;
        void **slots = (void **)o;
        void *found[64];
        int64_t k = 0;
        if ((mask & (1u << 22)) && !(mask & (1u << 23))) {
            void **buf = (void **)slots[0];
            if ((mask & (1u << 21)) && buf) {
                int64_t len = (int64_t)slots[1];
                for (int64_t i = 0; i < len; i++) {
                    if (n + 1 >= cap) {
                        cap *= 2;
                        stack = realloc(stack, (size_t)cap * sizeof(void *));
                    }
                    stack[n++] = buf[i];
                }
            }
        } else if (mask & (1u << 23)) {
            int cls = (int)(info & 0x7fu);
            int64_t size = cls < 64 ? (int64_t)(cls + 1) * 16 : (int64_t)2048 << (cls - 64);
            const int64_t *desc = *(const int64_t **)((char *)o - 8 + size - 8);
            for (int64_t w = 0; w < desc[0]; w++) {
                for (uint64_t bits = (uint64_t)desc[w + 1]; bits; bits &= bits - 1) {
                    if (n + 1 >= cap) {
                        cap *= 2;
                        stack = realloc(stack, (size_t)cap * sizeof(void *));
                    }
                    stack[n++] = slots[w * 64 + __builtin_ctzll(bits)];
                }
            }
        } else {
            for (; mask; mask &= mask - 1) found[k++] = slots[__builtin_ctz(mask)];
        }
        for (int64_t i = 0; i < k; i++) {
            if (n + 1 >= cap) {
                cap *= 2;
                stack = realloc(stack, (size_t)cap * sizeof(void *));
            }
            stack[n++] = found[i];
        }
    }
    free(stack);
}

// While a panic's backtrace is kept, nothing gives way (tasks.c).
extern int kod_no_preempt;

// The countdown is out: what follows in the hook isn't counted until it sets
// another.
// Whether the countdown that ran out was the one after a store.
int64_t kod_poll_by_store = 0;

int64_t kod_poll_after_store(void) {
    return kod_poll_by_store;
}

void kod_poll_slow(void) {
    int64_t store_budget = kod_poll_store_budget;
    kod_poll_by_store = store_budget <= 0;
    kod_poll_budget = (int64_t)1 << 62;
    kod_poll_store_budget = (int64_t)1 << 62;
    if (kod_no_preempt || !kod_poll_hook) {
        kod_poll_budget = 1;
        kod_poll_store_budget = store_budget > 0 ? store_budget : 1;
        return;
    }
    kod_poll_hook();
}

// Called by a loop's check while kod_poll_flag is set. It changes x16, x17
// and lr only (regalloc.kod, keeps_regs): the countdown in those, and when it
// is out, a frame that keeps everything else around kod_poll_slow: x0-x17,
// the flags, all of q0-q31 and the FP status, below the caller's red zone,
// with a frame record whose return address is the caller's, so that a
// backtrace from inside reads as the loop's.
__attribute__((naked)) void kod_poll_stub(void) {
    __asm__(
        "adrp x16, _kod_poll_stored@PAGE\n"
        "ldr x17, [x16, _kod_poll_stored@PAGEOFF]\n"
        "cbz x17, 2f\n"
        "str xzr, [x16, _kod_poll_stored@PAGEOFF]\n"
        // A counted object counts only when another task can reach it; a
        // module variable's mark (an address outside the counted heap) always.
        "lsr x16, x17, #36\n"
        "cmp x16, #0x300\n"
        "b.ne 3f\n"
        "adrp x16, _kod_reach_map@PAGE\n"
        "ldr x16, [x16, _kod_reach_map@PAGEOFF]\n"
        "cbz x16, 2f\n"
        "and x17, x17, #0xfffffffff\n"
        "lsr x17, x17, #4\n"
        "ldrb w17, [x16, x17]\n"
        "cbz x17, 2f\n"
        "3:\n"
        "adrp x16, _kod_poll_store_budget@PAGE\n"
        "ldr x17, [x16, _kod_poll_store_budget@PAGEOFF]\n"
        "sub x17, x17, #1\n"
        "str x17, [x16, _kod_poll_store_budget@PAGEOFF]\n"
        "cbz x17, 1f\n"
        "tbnz x17, #63, 1f\n"
        "2:\n"
        "adrp x16, _kod_poll_budget@PAGE\n"
        "ldr x17, [x16, _kod_poll_budget@PAGEOFF]\n"
        "sub x17, x17, #1\n"
        "str x17, [x16, _kod_poll_budget@PAGEOFF]\n"
        "cbz x17, 1f\n"
        "tbnz x17, #63, 1f\n"
        "ret\n"
        "1:\n"
        "sub sp, sp, #144\n"
        "str x30, [sp]\n"
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
        // The frame record: the caller's fp, and where it goes on.
        "ldr x9, [sp, #688]\n"
        "add x10, sp, #672\n"
        "stp x29, x9, [x10]\n"
        "mov x29, x10\n"
        "bl _kod_poll_slow\n"
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
        "add sp, sp, #832\n"
        "ret\n");
}

// Around a module variable's initializer (codegen.kod, emit_cached_getter),
// under a simulation: the countdown is put aside, and taken up again after.
// They change x16 and x17 only.
__attribute__((naked)) void kod_poll_hold(void) {
    __asm__(
        "adrp x16, _kod_poll_sim@PAGE\n"
        "ldr x17, [x16, _kod_poll_sim@PAGEOFF]\n"
        "cbz x17, 1f\n"
        "adrp x16, _kod_poll_held@PAGE\n"
        "ldr x17, [x16, _kod_poll_held@PAGEOFF]\n"
        "add x17, x17, #1\n"
        "str x17, [x16, _kod_poll_held@PAGEOFF]\n"
        "sub x17, x17, #1\n"
        "cbnz x17, 1f\n"
        "adrp x16, _kod_poll_budget@PAGE\n"
        "ldr x17, [x16, _kod_poll_budget@PAGEOFF]\n"
        "adrp x16, _kod_poll_kept@PAGE\n"
        "str x17, [x16, _kod_poll_kept@PAGEOFF]\n"
        "adrp x16, _kod_poll_budget@PAGE\n"
        "mov x17, #0x4000000000000000\n"
        "str x17, [x16, _kod_poll_budget@PAGEOFF]\n"
        "adrp x16, _kod_poll_store_budget@PAGE\n"
        "ldr x17, [x16, _kod_poll_store_budget@PAGEOFF]\n"
        "adrp x16, _kod_poll_store_kept@PAGE\n"
        "str x17, [x16, _kod_poll_store_kept@PAGEOFF]\n"
        "adrp x16, _kod_poll_store_budget@PAGE\n"
        "mov x17, #0x4000000000000000\n"
        "str x17, [x16, _kod_poll_store_budget@PAGEOFF]\n"
        "1:\n"
        "ret\n");
}

__attribute__((naked)) void kod_poll_unhold(void) {
    __asm__(
        "adrp x16, _kod_poll_held@PAGE\n"
        "ldr x17, [x16, _kod_poll_held@PAGEOFF]\n"
        "cbz x17, 1f\n"
        "sub x17, x17, #1\n"
        "str x17, [x16, _kod_poll_held@PAGEOFF]\n"
        "cbnz x17, 1f\n"
        "adrp x16, _kod_poll_kept@PAGE\n"
        "ldr x17, [x16, _kod_poll_kept@PAGEOFF]\n"
        "adrp x16, _kod_poll_budget@PAGE\n"
        "str x17, [x16, _kod_poll_budget@PAGEOFF]\n"
        "adrp x16, _kod_poll_store_kept@PAGE\n"
        "ldr x17, [x16, _kod_poll_store_kept@PAGEOFF]\n"
        "adrp x16, _kod_poll_store_budget@PAGE\n"
        "str x17, [x16, _kod_poll_store_budget@PAGEOFF]\n"
        // What the initializer stored doesn't count either.
        "adrp x16, _kod_poll_stored@PAGE\n"
        "str xzr, [x16, _kod_poll_stored@PAGEOFF]\n"
        "1:\n"
        "ret\n");
}

// Set by stdlib/tasks.c once a task has been started: prints, after a panic's
// backtrace, where the running task was spawned.
void (*kod_backtrace_hook)(void) = 0;

// A module variable's cell is {state, value}: state 0 before its first use, 2
// while its initializer runs, with the running task's tag (kod_task_now: its
// stack, 0 for the program's first task) as the value, 3 when as well a task
// waits for it, 1 after (codegen.kod, emit_cached_getter). A use while it is 2
// or 3 calls kod_var_busy: from another task than the one running the
// initializer, it waits until that one is over, 1, and the getter looks again
// (a caught panic in it sets the state back to 0); from that one it is a cycle,
// 0, and the getter panics.
int64_t kod_task_now = 0;
void (*kod_var_wait_hook)(int64_t cell) = 0;
void (*kod_var_wake_hook)(int64_t cell) = 0;

int64_t kod_var_busy(int64_t *cell) {
    if (!kod_var_wait_hook || cell[1] == kod_task_now) return 0;
    while (cell[0] == 2 || cell[0] == 3) {
        cell[0] = 3;
        kod_var_wait_hook((int64_t)cell);
    }
    return 1;
}

// After the initializer of a cell that was 3: the tasks waiting go on.
void kod_var_wake(int64_t *cell) {
    if (kod_var_wake_hook) kod_var_wake_hook((int64_t)cell);
}

// KodStr and KodArray, the layout of a Kod `str` and `[T]`, are in kod_rt.h,
// which C files that Kod modules name include too.

// Allocate a fresh KodStr plus a `len`-byte NUL-terminated buffer in
// a single allocation. Caller fills `buf` before returning.
static KodStr *kod_str_alloc(int64_t len) {
    return kod_str_new(len);
}

// Build a KodStr from a NUL-terminated C string (e.g. argv[i]). Copies
// the bytes; cheap enough for the rare libc-boundary case.
KodStr *kod_str_from_cstr(const char *cstr) {
    int64_t len = (int64_t)strlen(cstr);
    KodStr *s = kod_str_alloc(len);
    memcpy(s->buf, cstr, len);
    return s;
}

// Empty Kod string with the right header layout.
static KodStr *kod_empty_str(void) {
    return kod_str_alloc(0);
}

// Catching a panic (docs/panics.md). kod_catch calls a function under a
// KodCatch; a panic while it runs, instead of ending the program, gives up
// what the frames between hold and goes back to it.
typedef struct KodCatch {
    struct KodCatch *prev;
    // kod_catch's own frame, where the walk over the abandoned ones ends.
    uint64_t *fp;
    KodStr *message, *backtrace;
    jmp_buf back;
} KodCatch;

// Where a map's op_index_take took a value from: its values' buffer and the
// index (codegen.kod, hold_taken).
int64_t kod_taken[2];

// The innermost catch of the running task (tasks.c switches it with the rest).
KodCatch *kod_catch_top = 0;
// While set, kod_eprint writes to kod_err_text: a backtrace is being kept.
static int kod_err_keep = 0;
static char *kod_err_text;
static size_t kod_err_len, kod_err_cap;
// A preempted task would print into it, so none is meanwhile (kod_poll_slow).
int kod_no_preempt = 0;
// The next panic ends the program even under a catch (kod_panic_uncaught).
static int kod_uncaught = 0;
// Set by stdlib/tasks.c: cancels the tasks of a TaskGroup? and waits for them.
void (*kod_unwind_group_hook)(void *group) = 0;

static void kod_err_write(const char *p, size_t n) {
    if (!kod_err_keep) {
        fwrite(p, 1, n, stderr);
        return;
    }
    if (kod_err_len + n > kod_err_cap) {
        kod_err_cap = (kod_err_len + n) * 2;
        kod_err_text = realloc(kod_err_text, kod_err_cap);
        if (!kod_err_text) abort();
    }
    memcpy(kod_err_text + kod_err_len, p, n);
    kod_err_len += n;
}

// The rows codegen emits for the functions whose frames hold references
// (emit_unwind_row): where the function starts and its last instruction, how
// many words follow, and the words, padded to 8 bytes. A word is a frame
// slot's number (the slot at fp - 8 * number) times 4, plus what it holds:
// 0 a reference; 1 a `mut` parameter, which goes back where the next word's
// slot says; 2 a TaskGroup?, as 0 but its tasks are cancelled first; 3 the
// buffer a map's value was taken out of while it is changed, where it goes back:
// the next words' slots hold its index there and the value. A count of
// KOD_UNWIND_VAR is a module variable's getter, with its cell's address next.
#define KOD_UNWIND_VAR 0x40000000u
extern const char kod_unwind_start[] __asm__("section$start$__DATA$__kod_unwind");
extern const char kod_unwind_end[] __asm__("section$end$__DATA$__kod_unwind");

static const uint64_t *kod_unwind_row(uint64_t pc) {
    const char *at = kod_unwind_start;
    while (at < kod_unwind_end) {
        const uint64_t *row = (const uint64_t *)at;
        if (pc > row[0] && pc <= row[1]) return row;
        uint32_t n = *(const uint32_t *)(row + 2);
        at += n == KOD_UNWIND_VAR ? 32 : (20 + 4 * (size_t)n + 7) / 8 * 8;
    }
    return 0;
}

void kod_var_wake(int64_t *cell);

static void kod_unwind_frame(uint64_t *fp, uint64_t pc) {
    const uint64_t *row = kod_unwind_row(pc);
    if (!row) return;
    const uint32_t *w = (const uint32_t *)(row + 2);
    uint32_t n = *w++;
    if (n == KOD_UNWIND_VAR) {
        // Its initializer is run again at the next use.
        int64_t *cell = *(int64_t **)(w + 1);
        int64_t state = cell[0];
        if (state == 2 || state == 3) {
            cell[0] = 0;
            cell[1] = 0;
            // What kod_poll_hold put aside for it.
            if (kod_poll_held > 0 && --kod_poll_held == 0) {
                kod_poll_budget = kod_poll_kept;
                kod_poll_store_budget = kod_poll_store_kept;
                kod_poll_stored = 0;
            }
            if (state == 3) kod_var_wake(cell);
        }
        return;
    }
    // A function's tasks end before it gives up what they may use.
    for (uint32_t i = 0; i < n; i++) {
        uint32_t kind = w[i] & 3;
        void **slot = (void **)(fp - (w[i] >> 2));
        if (kind == 2 && *slot && kod_unwind_group_hook) kod_unwind_group_hook(*slot);
        if (kind == 3 && *slot) {
            // Unless the array has let go of the buffer since, or filled it.
            void **place = (void **)*slot + *(int64_t *)(fp - (w[i + 1] >> 2));
            void **value = (void **)(fp - (w[i + 2] >> 2));
            if (((uint32_t *)*slot)[-2] > 1 && !*place) {
                *place = *value;
                *value = 0;
            }
        }
        if (kind == 1) i++;
        if (kind == 3) i += 2;
    }
    for (uint32_t i = 0; i < n; i++) {
        uint32_t kind = w[i] & 3;
        void **slot = (void **)(fp - (w[i] >> 2));
        void *held = *slot;
        *slot = 0;
        if (kind == 1) {
            i++;
            **(void ***)(fp - (w[i] >> 2)) = held;
        } else {
            rc_release_c(held);
        }
        if (kind == 3) i += 2;
    }
}

// Goes back to `to`, giving up the frames from the one that called the
// function whose frame is `fp`.
__attribute__((noreturn)) static void kod_unwind(KodCatch *to, uint64_t *fp) {
    kod_catch_top = to;
    for (;;) {
        uint64_t *up = (uint64_t *)fp[0];
        if (up == to->fp || up == 0) break;
        kod_unwind_frame(up, fp[1]);
        fp = up;
    }
    kod_catch_top = to->prev;
    _longjmp(to->back, 1);
}

// Under a debugger, a panic that ends the program stops it first, where it
// happened, with its stack (docs/debugging.md); `continue` lets it end.
static void kod_stop_for_debugger(void) {
    struct kinfo_proc info;
    size_t size = sizeof info;
    int mib[4] = {CTL_KERN, KERN_PROC, KERN_PROC_PID, getpid()};
    info.kp_proc.p_flag = 0;
    if (sysctl(mib, 4, &info, &size, NULL, 0) == 0 && (info.kp_proc.p_flag & P_TRACED)) {
        __builtin_debugtrap();
    }
}

// Prints the panic and ends the program, or under a catch goes back to it,
// releasing `owned`, which may be what holds the message.
__attribute__((noreturn)) static void kod_panic_text(const char *msg, size_t len, KodStr *owned, uint64_t *fp) {
    KodCatch *to = kod_catch_top;
    if (to && !kod_uncaught && !kod_err_keep) {
        to->message = kod_str_from_bytes(msg, (int64_t)len);
        rc_release_c(owned);
        kod_err_len = 0;
        kod_no_preempt = 1;
        kod_err_keep = 1;
        kod_inspect_print_backtrace_from((int64_t)fp);
        if (kod_backtrace_hook) kod_backtrace_hook();
        kod_err_keep = 0;
        kod_no_preempt = 0;
        to->backtrace = kod_str_from_bytes(kod_err_text, (int64_t)kod_err_len);
        kod_unwind(to, fp);
    }
    kod_err_keep = 0;
    // No other task runs while it is printed.
    kod_no_preempt = 1;
    // Stdout is flushed first, so what the program printed comes out before
    // the message when both end up in one pipe or log.
    fflush(stdout);
    fwrite("panic: ", 1, 7, stderr);
    fwrite(msg, 1, len, stderr);
    fputc('\n', stderr);
    kod_inspect_print_backtrace_from((int64_t)fp);
    if (kod_backtrace_hook) kod_backtrace_hook();
    kod_stop_for_debugger();
    exit(1);
}

// The builtin `panic`, and what `must`, `assert` and others call.
void kod_panic(KodStr *msg) {
    kod_panic_text(msg->buf, (size_t)msg->len, 0, __builtin_frame_address(0));
}

// As kod_panic, with a message that is this call's: what `must` made of an error.
void kod_panic_owned(KodStr *msg) {
    kod_panic_text(msg->buf, (size_t)msg->len, msg, __builtin_frame_address(0));
}

// As kod_panic, but no catch takes it.
void kod_panic_uncaught(KodStr *msg) {
    kod_uncaught = 1;
    kod_panic_text(msg->buf, (size_t)msg->len, 0, __builtin_frame_address(0));
}

// A panic that happened before goes on, to the catch `target` (its kod_catch_here)
// or to the innermost when that is 0.
void kod_panic_again(KodStr *msg, KodStr *backtrace, int64_t target) {
    KodCatch *to = target ? (KodCatch *)target : kod_catch_top;
    if (!to) {
        fflush(stdout);
        fwrite("panic: ", 1, 7, stderr);
        fwrite(msg->buf, 1, (size_t)msg->len, stderr);
        fputc('\n', stderr);
        fwrite(backtrace->buf, 1, (size_t)backtrace->len, stderr);
        kod_stop_for_debugger();
        exit(1);
    }
    to->message = kod_str_from_bytes(msg->buf, msg->len);
    to->backtrace = kod_str_from_bytes(backtrace->buf, backtrace->len);
    kod_unwind(to, __builtin_frame_address(0));
}

static KodStr *kod_caught[2];

// A child made by fork isn't under its parent's catches.
static void kod_catch_forked(void) {
    kod_catch_top = 0;
}

// Calls the Kod function at `fn` (unsafe.c_function): 0 when it came back, 1
// when a panic did, which kod_caught_message and kod_caught_backtrace have.
__attribute__((noinline)) int64_t kod_catch(int64_t fn) {
    static int hooked = 0;
    if (!hooked) {
        hooked = 1;
        pthread_atfork(NULL, NULL, kod_catch_forked);
    }
    KodCatch c;
    c.prev = kod_catch_top;
    c.fp = __builtin_frame_address(0);
    c.message = c.backtrace = 0;
    if (_setjmp(c.back) == 0) {
        kod_catch_top = &c;
        ((void (*)(void))fn)();
        kod_catch_top = c.prev;
        return 0;
    }
    kod_caught[0] = c.message;
    kod_caught[1] = c.backtrace;
    return 1;
}

static KodStr *kod_caught_take(int i) {
    KodStr *s = kod_caught[i];
    kod_caught[i] = 0;
    return s ? s : kod_empty_str();
}

KodStr *kod_caught_message(void) { return kod_caught_take(0); }
KodStr *kod_caught_backtrace(void) { return kod_caught_take(1); }

// The frame of the innermost catch, or 0.
int64_t kod_catch_fp(void) { return kod_catch_top ? (int64_t)kod_catch_top->fp : 0; }

// The innermost catch, 0 when there is none.
int64_t kod_catch_here(void) { return (int64_t)kod_catch_top; }

// Backtrace generation lives in kod (stdlib/kod/inspect.kod) — the
// C runtime keeps just the primitives the kod walker needs (raw
// memory reads, c-string lift, section-bounds accessors) plus a
// small wrapper that captures the panic-handler's own fp and hands
// it to the kod entry point.

// Mach-O linker-synthesised bounds for the per-function symbol
// rows the codegen emits via emit_symtab_entry.
extern const char kod_symtab_section_start[]
    __asm__("section$start$__DATA$__kod_symtab");
extern const char kod_symtab_section_end[]
    __asm__("section$end$__DATA$__kod_symtab");

int64_t _inspect_read_i64(int64_t addr) { return *(int64_t *)addr; }
int64_t _inspect_read_i32(int64_t addr) { return *(int32_t *)addr; }
// Used by `inspect.print_backtrace()` (the user-facing zero-arg
// form): __builtin_frame_address(1) is the caller's fp. The kod
// caller's frame is what we want to start walking from — so the
// trace's first row is the user function that called print_backtrace,
// not inspect.print_backtrace itself. `noinline` keeps the wrapper
// frame distinct so fa(1) does the right thing.
__attribute__((noinline)) int64_t _inspect_caller_fp(void) {
    return (int64_t)(uintptr_t)__builtin_frame_address(1);
}
KodStr *_inspect_cstr_to_str(int64_t addr) {
    return kod_str_from_cstr((const char *)addr);
}
int64_t _inspect_symtab_start(void) {
    return (int64_t)(uintptr_t)kod_symtab_section_start;
}
int64_t _inspect_symtab_end(void) {
    return (int64_t)(uintptr_t)kod_symtab_section_end;
}

// Called by the codegen's array-indexing bounds check on a miss.
// Negative indices are already normalised (idx += len) before this
// runs, so any out-of-range value here is genuinely out of bounds.
void kod_index_oob(int64_t idx, int64_t len) {
    char msg[96];
    int n = snprintf(msg, sizeof msg, "index %lld out of bounds for array of length %lld",
                     (long long)idx, (long long)len);
    kod_panic_text(msg, (size_t)n, 0, __builtin_frame_address(0));
}

void kod_div_zero(void) {
    const char *msg = "integer division by zero";
    kod_panic_text(msg, strlen(msg), 0, __builtin_frame_address(0));
}

// Called when an int64 `+`, `-`, `*` or `/` gives a result that doesn't fit.
void kod_int_overflow(void) {
    const char *msg = "integer overflow";
    kod_panic_text(msg, strlen(msg), 0, __builtin_frame_address(0));
}

// Print to stderr without exiting. Used by the codegen to surface
// user-facing errors (unknown method, etc.) while continuing to
// scan the rest of the module for additional errors.
void kod_eprint(KodStr *msg) {
    kod_err_write(msg->buf, (size_t)msg->len);
    kod_err_write("\n", 1);
}

// Kod-side `puts` extern — len-aware, won't fool itself on embedded
// NULs. Trailing newline matches libc puts.
int64_t kod_puts(KodStr *s) {
    // One lock for the line: fwrite and fputc would each take it.
    flockfile(stdout);
    for (int64_t i = 0; i < s->len; i++) putc_unlocked(s->buf[i], stdout);
    putc_unlocked('\n', stdout);
    funlockfile(stdout);
    return 0;
}


// The builtin `fail`. The test runner is Kod (stdlib/testing.kod), and a test
// program's `_main` defines this to call it; anywhere else there is no test to
// fail, so it panics like `assert` outside a test.
__attribute__((weak)) void kod_test_fail(KodStr *msg) {
    kod_panic(msg);
}

// A negative bound counts from the end, as an index does; then both clamp to 0..len.
static int64_t clamp_slice(int64_t len, int64_t *start, int64_t end) {
    if (*start < 0) *start += len;
    if (end < 0) end += len;
    if (*start < 0) *start = 0;
    if (*start > len) *start = len;
    if (end > len) end = len;
    return end > *start ? end - *start : 0;
}

KodStr *kod_str_slice(KodStr *s, int64_t start, int64_t end) {
    int64_t len = clamp_slice(s->len, &start, end);
    KodStr *out = kod_str_alloc(len);
    kod_copy(out->buf, s->buf + start, len);
    return out;
}

KodStr *kod_str_concat(KodStr *a, KodStr *b) {
    KodStr *out = kod_str_alloc(a->len + b->len);
    kod_copy(out->buf, a->buf, a->len);
    kod_copy(out->buf + a->len, b->buf, b->len);
    return out;
}

// Lexicographic compare on the byte buffers, with length-difference
// tiebreaker (matches memcmp / strcmp semantics). Replaces the
// previous direct `_strcmp` call inside compile_str_eq, which would
// have read past struct headers under the new layout.
int64_t kod_str_cmp(KodStr *a, KodStr *b) {
    int64_t min_len = a->len < b->len ? a->len : b->len;
    int rc = memcmp(a->buf, b->buf, (size_t)min_len);
    if (rc != 0) return rc;
    return a->len - b->len;
}

// A growable byte buffer behind the stdlib `StrBuilder` and the str methods
// that build strings. Kod holds it as an int64 handle. The buffer doubles
// when full, so n appended bytes cost
// O(n) and leave under 2n bytes of abandoned buffers behind.
typedef struct {
    char *buf;
    int64_t len;
    int64_t cap;
} KodStrBuilder;

int64_t kod_sb_new(void) {
    KodStrBuilder *sb = (KodStrBuilder *)rc_alloc(sizeof(KodStrBuilder), 1);
    sb->cap = 32;
    sb->len = 0;
    sb->buf = (char *)rc_alloc_raw(sb->cap, 0);
    return (int64_t)sb;
}

static void kod_sb_reserve(KodStrBuilder *sb, int64_t extra) {
    if (extra > INT64_MAX / 4 - sb->len) {
        kod_panic(kod_str_from_cstr("string builder is too large"));
    }
    int64_t need = sb->len + extra;
    if (need <= sb->cap) return;
    int64_t new_cap = sb->cap;
    while (new_cap < need) new_cap *= 2;
    char *new_buf = (char *)rc_alloc_raw(new_cap, 0);
    memcpy(new_buf, sb->buf, (size_t)sb->len);
    rc_release_c(sb->buf);
    sb->buf = new_buf;
    sb->cap = new_cap;
}

// Room for `extra` more bytes (stdlib/bytebuffer.kod).
void kod_sb_reserve_extra(int64_t handle, int64_t extra) {
    kod_sb_reserve((KodStrBuilder *)handle, extra);
}

void kod_sb_append(int64_t handle, KodStr *s) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    kod_sb_reserve(sb, s->len);
    kod_copy(sb->buf + sb->len, s->buf, s->len);
    sb->len += s->len;
}

void kod_sb_append_byte(int64_t handle, int64_t b) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    kod_sb_reserve(sb, 1);
    sb->buf[sb->len++] = (char)(b & 0xff);
}

// `n` in decimal, as int64.to_str writes it.
// Writes the decimal digits of n, last first, into digits (20 bytes) and
// gives how many there are; the sign is the caller's.
static int kod_digits_reversed(int64_t n, char *digits) {
    int len = 0;
    // From the signed value, so the smallest int64 needs no negating.
    int64_t rest = n;
    do {
        int64_t d = rest % 10;
        digits[len++] = (char)('0' + (d < 0 ? -d : d));
        rest /= 10;
    } while (rest != 0);
    return len;
}

void kod_sb_append_int(int64_t handle, int64_t n) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    char digits[20];
    int len = kod_digits_reversed(n, digits);
    kod_sb_reserve(sb, len + 1);
    if (n < 0) sb->buf[sb->len++] = '-';
    while (len > 0) sb->buf[sb->len++] = digits[--len];
}

// n in decimal, in one allocation (int64's to_str).
KodStr *kod_int64_to_str(int64_t n) {
    char digits[20];
    int len = kod_digits_reversed(n, digits);
    int sign = n < 0;
    KodStr *s = kod_str_new(len + sign);
    if (sign) s->buf[0] = '-';
    for (int i = 0; i < len; i++) s->buf[sign + i] = digits[len - 1 - i];
    return s;
}

int64_t kod_sb_len(int64_t handle) {
    return ((KodStrBuilder *)handle)->len;
}

void kod_sb_clear(int64_t handle) {
    ((KodStrBuilder *)handle)->len = 0;
}

KodStr *kod_sb_to_str(int64_t handle) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    return kod_str_from_bytes(sb->buf, sb->len);
}

// CRC-32 (the gzip polynomial) of n bytes, continuing from `crc`, the
// running state without gzip's final xor. Eight bytes per instruction where
// the CPU has the CRC instructions, a byte at a time otherwise.
static uint32_t kod_crc32_run(uint32_t crc, const unsigned char *p, int64_t n) {
#if defined(__ARM_FEATURE_CRC32)
    for (; n >= 8; p += 8, n -= 8) {
        uint64_t w;
        memcpy(&w, p, 8);
        crc = __crc32d(crc, w);
    }
    for (; n > 0; p++, n--) crc = __crc32b(crc, *p);
#else
    for (; n > 0; p++, n--) {
        crc ^= *p;
        for (int k = 0; k < 8; k++) crc = (crc >> 1) ^ (0xEDB88320u & (0u - (crc & 1)));
    }
#endif
    return crc;
}

// Adler-32 of n bytes, continuing from `sum` (b << 16 | a). 5552 bytes is
// the most that can be added before the sums could overflow 32 bits.
static uint32_t kod_adler32_run(uint32_t sum, const unsigned char *p, int64_t n) {
    uint32_t a = sum & 0xffff, b = sum >> 16;
    while (n > 0) {
        int64_t chunk = n < 5552 ? n : 5552;
        n -= chunk;
        for (; chunk > 0; p++, chunk--) {
            a += *p;
            b += a;
        }
        a %= 65521;
        b %= 65521;
    }
    return (b << 16) | a;
}

// The range start..end clamped to a buffer of `len` bytes.
static int64_t kod_clamp_range(int64_t len, int64_t *start, int64_t end) {
    if (*start < 0) *start = 0;
    if (end > len) end = len;
    return end > *start ? end - *start : 0;
}

int64_t kod_crc32_bytes(int64_t crc, KodStr *b, int64_t start, int64_t end) {
    int64_t n = kod_clamp_range(b->len, &start, end);
    return kod_crc32_run((uint32_t)crc, (const unsigned char *)b->buf + start, n);
}

int64_t kod_crc32_sb(int64_t crc, int64_t handle, int64_t start, int64_t end) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    int64_t n = kod_clamp_range(sb->len, &start, end);
    return kod_crc32_run((uint32_t)crc, (const unsigned char *)sb->buf + start, n);
}

int64_t kod_adler32_sb(int64_t sum, int64_t handle, int64_t start, int64_t end) {
    KodStrBuilder *sb = (KodStrBuilder *)handle;
    int64_t n = kod_clamp_range(sb->len, &start, end);
    return kod_adler32_run((uint32_t)sum, (const unsigned char *)sb->buf + start, n);
}

// stdlib/unsafe.kod; its loads, stores, c_int and refs are compiler intrinsics.
// A `bytes` holding a copy of the `n` bytes at `addr`.
KodStr *kod_unsafe_copy_out(int64_t addr, int64_t n) {
    return kod_str_from_bytes((const char *)addr, n < 0 ? 0 : n);
}

// Append rhs to lhs, mutating lhs in place when its `cap` is large enough
// and reallocating with exponential growth otherwise. Returns lhs.
//
// Intentional aliasing-semantics change versus the original "always-fresh
// hdr" behavior: callers like `xs += [x]` now observe amortized O(1) per
// append (was O(n), so O(n²) over a build loop). `let b = a; a += [x]`
// will now also append to `b` — but no in-tree caller relied on the old
// copy-on-concat semantics, and the test suites all pass.
// Slice copy: returns a fresh array with elements [start, end). Every
// element in a Kod array is 8 bytes (pointer-or-int64), so a flat
// memcpy is enough — no per-element rewrap needed. Negative `end - start`
// clamps to a zero-length slice. Explicit range checking is the caller's
// job (the codegen could emit a `len` check; today we don't).
// Pack a Kod `[int64]` (one byte per element, low 8 bits) into a fresh
// Kod bytes buffer of the same length. Useful for builders that
// accumulate bytes as int64s and emit binary output in one shot —
// avoids the quadratic-time pattern of repeatedly concatenating
// one-character buffers.
KodStr *kod_bytes_from_array(void *arr_raw) {
    KodArray *arr = (KodArray *)arr_raw;
    int64_t len = arr->len;
    KodStr *s = kod_str_alloc(len);
    int64_t *src = (int64_t *)arr->ptr;
    for (int64_t i = 0; i < len; i++) {
        s->buf[i] = (char)(src[i] & 0xff);
    }
    return s;
}

// `str` and `bytes` share the same runtime representation (a `KodStr *`);
// these casts are zero-copy. The type system uses them to mark the
// boundary between text and raw-byte handling.
KodStr *kod_str_to_bytes(void *s) { rc_retain_c(s); return (KodStr *)s; }
KodStr *kod_bytes_to_str(void *b) { rc_retain_c(b); return (KodStr *)b; }

// Only reached through a function value: codegen compiles a direct call to
// a bounds check and one load. Out of range panics with the first missing
// byte's index, as the compiled check does.
int64_t kod_bytes_le64(KodStr *b, int64_t at) {
    if (at < 0 || at >= b->len) kod_index_oob(at, b->len);
    if (b->len - at < 8) kod_index_oob(b->len, b->len);
    uint64_t v;
    memcpy(&v, b->buf + at, 8);
    return (int64_t)v;
}

#define RC_ARRAY_BIT (1ULL << 22)
#define RC_REFS_BIT (1ULL << 21)
static inline int rc_arr_counted(const void *p) { return ((uint64_t)p >> 36) == 0x300; }
static inline int rc_arr_refs(const void *a) {
    return rc_arr_counted(a) && ((((uint32_t *)a)[-1] >> 8) & RC_REFS_BIT);
}
static inline void rc_arr_set_refs(void *a) {
    if (rc_arr_counted(a)) ((uint32_t *)a)[-1] |= (uint32_t)(RC_REFS_BIT << 8);
}
// An array's elements are `width` bytes each: 1 for a `[bool]`, 16 to 32 for
// a flat struct's fields (see flat_width in codegen.kod), else 8. The
// compiler knows the element type at every call and passes it.
static KodArray *rc_arr_new(int64_t cap, int refs, int64_t width) {
    KodArray *out = (KodArray *)rc_alloc(sizeof(KodArray), (int64_t)(RC_ARRAY_BIT | (refs ? RC_REFS_BIT : 0)));
    out->ptr = rc_alloc_raw(cap > 0 ? cap * width : 8, 0);
    out->cap = cap;
    return out;
}
static void rc_arr_retain_all(void **p, int64_t n) {
    for (int64_t i = 0; i < n; i++) rc_retain_c(p[i]);
}

void *kod_arr_slice(void *src_raw, int64_t start, int64_t end, int64_t width) {
    KodArray *src = (KodArray *)src_raw;
    int64_t len = clamp_slice(src->len, &start, end);
    int refs = rc_arr_refs(src);
    KodArray *out = rc_arr_new(len, refs, width);
    out->len = len;
    if (len > 0) {
        memcpy(out->ptr, (char *)src->ptr + start * width, len * width);
        if (refs) rc_arr_retain_all((void **)out->ptr, len);
    }
    return out;
}

void *kod_arr_copy(void *src_raw, int64_t width) {
    return kod_arr_slice(src_raw, 0, ((KodArray *)src_raw)->len, width);
}

// Grow `arr`'s buffer to hold at least `need` elements, doubling.
static void rc_arr_reserve(KodArray *arr, int64_t need, int64_t width, int64_t first_cap) {
    if (arr->cap >= need) return;
    int64_t new_cap = arr->cap > 0 ? arr->cap : first_cap;
    while (new_cap < need) new_cap *= 2;
    char *buf = (char *)rc_alloc_raw(new_cap * width, 0);
    if (arr->len > 0) memcpy(buf, arr->ptr, arr->len * width);
    rc_release_c(arr->ptr);
    arr->ptr = buf;
    arr->cap = new_cap;
}

void *kod_arr_concat(void *lhs_raw, void *rhs_raw, int64_t width) {
    KodArray *lhs = (KodArray *)lhs_raw;
    KodArray *rhs = (KodArray *)rhs_raw;
    int64_t total = lhs->len + rhs->len;
    int refs = rc_arr_refs(rhs) || rc_arr_refs(lhs);
    rc_arr_reserve(lhs, total, width, 4);
    int64_t rhs_len = rhs->len;
    if (rhs_len > 0) memmove((char *)lhs->ptr + lhs->len * width, rhs->ptr, rhs_len * width);
    if (refs) {
        rc_arr_retain_all((void **)lhs->ptr + lhs->len, rhs_len);
        if (lhs->len == 0) rc_arr_set_refs(lhs);
    }
    lhs->len = total;
    return lhs;
}

// `xs += [x]` without the one-element array: `value` goes on the end of `arr` in
// place. When `refs` is set it is a counted reference the caller has already
// retained for the array. An element wider than 8 bytes, a flat struct's
// fields, is copied from where `value` points: a cell, or another element.
void *kod_arr_push(void *arr_raw, int64_t value, int64_t refs, int64_t width) {
    KodArray *arr = (KodArray *)arr_raw;
    if (__builtin_expect(width <= 8, 1)) {
        rc_arr_reserve(arr, arr->len + 1, width, 4);
        if (__builtin_expect(width == 8, 1)) {
            ((int64_t *)arr->ptr)[arr->len] = value;
        } else {
            ((uint8_t *)arr->ptr)[arr->len] = (uint8_t)value;
        }
    } else {
        // Read first: `value` may point into the buffer that growing frees.
        int64_t words = width / 8;
        const int64_t *src = (const int64_t *)value;
        int64_t f0 = src[0], f1 = src[1];
        int64_t f2 = words > 2 ? src[2] : 0;
        int64_t f3 = words > 3 ? src[3] : 0;
        rc_arr_reserve(arr, arr->len + 1, width, 4);
        int64_t *dst = (int64_t *)((char *)arr->ptr + arr->len * width);
        dst[0] = f0;
        dst[1] = f1;
        if (words > 2) dst[2] = f2;
        if (words > 3) dst[3] = f3;
    }
    if (refs && arr->len == 0) rc_arr_set_refs(arr);
    arr->len++;
    return arr;
}

// `arr * n`: a new array of `n` copies of `arr`'s elements in order; empty for
// `n` of zero or less. The copies double until they fill it.
void *kod_arr_repeat(void *arr_raw, int64_t n, int64_t width) {
    KodArray *arr = (KodArray *)arr_raw;
    int64_t len = arr->len;
    if (n < 0) n = 0;
    if (len > 0 && n > INT64_MAX / width / len) {
        static KodStr too_big = {"array repetition too large", 26};
        kod_panic(&too_big);
    }
    int64_t total = len * n;
    int refs = rc_arr_refs(arr);
    KodArray *out = rc_arr_new(total, refs, width);
    out->len = total;
    if (total > 0) {
        char *dst = (char *)out->ptr;
        memcpy(dst, arr->ptr, len * width);
        int64_t filled = len;
        while (filled < total) {
            int64_t chunk = filled < total - filled ? filled : total - filled;
            memcpy(dst + filled * width, dst, chunk * width);
            filled += chunk;
        }
        if (refs) rc_arr_retain_all((void **)dst, total);
    }
    return out;
}

// Copy on write: the array at `*place`, made the place's own first. An array
// another place also holds (its count isn't 1), or one outside the counted
// heap, is copied; the copy goes to `*place` and the original loses the
// place's reference.
void *kod_arr_unique(void **place, int64_t width) {
    KodArray *a = (KodArray *)*place;
    if (rc_arr_counted(a) && ((uint32_t *)a)[-2] == 1) return a;
    KodArray *c = (KodArray *)kod_arr_slice(a, 0, a->len, width);
    *place = c;
    rc_release_c(a);
    return c;
}

// `xs = xs[..end]`: the array at `*place` keeps the elements before `end` (a
// negative `end` counts from the end) and lets go of the rest, in place when the
// place is its only holder.
void kod_arr_truncate_at(void **place, int64_t end, int64_t width) {
    KodArray *a = (KodArray *)*place;
    int64_t start = 0;
    int64_t keep = clamp_slice(a->len, &start, end);
    if (keep == a->len) return;
    if (!(rc_arr_counted(a) && ((uint32_t *)a)[-2] == 1)) {
        *place = kod_arr_slice(a, 0, keep, width);
        rc_release_c(a);
        return;
    }
    if (rc_arr_refs(a)) {
        for (int64_t i = keep; i < a->len; i++) rc_release_c(((void **)a->ptr)[i]);
    }
    a->len = keep;
}

// `xs += [x]` and `xs += ys` on the array at `*place`, made its own first.
void kod_arr_push_at(void **place, int64_t value, int64_t refs, int64_t width) {
    kod_arr_push(kod_arr_unique(place, width), value, refs, width);
}

void kod_arr_concat_at(void **place, void *rhs_raw, int64_t width) {
    // Appending an array to itself reads the elements before they're copied.
    KodArray *rhs = (KodArray *)rhs_raw;
    if (rhs == *place && !(rc_arr_counted(rhs) && ((uint32_t *)rhs)[-2] == 1)) {
        rc_retain_c(rhs);
        kod_arr_concat(kod_arr_unique(place, width), rhs, width);
        rc_release_c(rhs);
        return;
    }
    kod_arr_concat(kod_arr_unique(place, width), rhs, width);
}

void *kod_arr_concat_new(void *lhs_raw, void *rhs_raw, int64_t width) {
    KodArray *lhs = (KodArray *)lhs_raw;
    KodArray *rhs = (KodArray *)rhs_raw;
    int64_t total = lhs->len + rhs->len;
    int refs = rc_arr_refs(lhs) || rc_arr_refs(rhs);
    KodArray *out = rc_arr_new(total, refs, width);
    out->len = total;
    if (lhs->len > 0) memcpy(out->ptr, lhs->ptr, lhs->len * width);
    if (rhs->len > 0) memcpy((char *)out->ptr + lhs->len * width, rhs->ptr, rhs->len * width);
    if (refs) rc_arr_retain_all((void **)out->ptr, total);
    return out;
}

/* Waiting without holding up other tasks (docs/tasks.md): stdlib/tasks.c sets
 * the hook once a program has started a task. A call that would block calls
 * kod_wait_event first, with kevent's ident, filter and data (EVFILT_READ or
 * EVFILT_WRITE on a descriptor, data the most nanoseconds to wait or 0;
 * EVFILT_TIMER for nanoseconds; EVFILT_PROC on a child); 1 means the task
 * waited for the event while others ran, 0 that the caller should just block,
 * as it does without tasks, 2 that the task is cancelled, 3 that the time
 * ran out first, and 4 that another task has closed the descriptor. A socket's own timeout (SO_RCVTIMEO, SO_SNDTIMEO) is the
 * limit for a descriptor given 0, as it is for a read that blocks; one given -1
 * is a socket without a limit. A filter of 0 only asks whether the task is cancelled. */
int64_t (*kod_wait_hook)(int64_t ident, int64_t filter, int64_t data) = 0;

/* Under a simulation, crypto/random's bytes come from its seed (splitmix64),
 * so that a run repeats: kod_sim_random fills `buf` and gives 1, or gives 0
 * when no simulation is under way. */
static int kod_sim_random_on = 0;
static uint64_t kod_sim_random_state = 0;

void kod_sim_set_random(int64_t on, int64_t seed) {
    kod_sim_random_on = (int)on;
    kod_sim_random_state = (uint64_t)seed ^ 0x5eed5eed5eed5eedULL;
}

int64_t kod_sim_random(uint8_t *buf, int64_t n) {
    if (!kod_sim_random_on) return 0;
    for (int64_t i = 0; i < n; i++) {
        if (i % 8 == 0) {
            kod_sim_random_state += 0x9e3779b97f4a7c15ULL;
        }
        uint64_t z = kod_sim_random_state;
        z = (z ^ (z >> 30)) * 0xbf58476d1ce4e5b9ULL;
        z = (z ^ (z >> 27)) * 0x94d049bb133111ebULL;
        z ^= z >> 31;
        buf[i] = (uint8_t)(z >> (8 * (i % 8)));
    }
    return 1;
}

/* A simulation's clock (stdlib/tasks.kod, docs/simulation.md): the
 * nanoseconds since it began, which time.monotonic_ns gives instead of the
 * real clock's; -1 when none is under way. */
static int64_t kod_sim_clock_ns = -1;

void kod_sim_set_clock(int64_t ns) {
    kod_sim_clock_ns = ns;
}

int64_t kod_sim_clock(void) {
    return kod_sim_clock_ns;
}

/* Where a simulation's calendar starts, in nanoseconds since 1970. */
static int64_t kod_sim_epoch_ns = 0;

void kod_sim_set_epoch(int64_t ns) {
    kod_sim_epoch_ns = ns;
}

int64_t kod_sim_epoch(void) {
    return kod_sim_epoch_ns;
}

// After kod_wait_event gave 1 for a write: how many bytes the descriptor has
// room for, so that a write of no more doesn't wait; 0 when that isn't known.
int64_t kod_room = 0;
int64_t kod_wait_room(void) {
    return kod_room;
}

/* Told of a descriptor about to be closed, so that no task waits for it for
 * good: kevent says nothing of it then (stdlib/tasks.c sets the hook). */
void (*kod_close_hook)(int64_t fd) = 0;

void kod_closing(int64_t fd) {
    if (kod_close_hook) kod_close_hook(fd);
}

/* Whether the descriptor kod_wait_event was last called for is a file's, which
 * is always ready: kevent says nothing of one read to its end (tasks.c). */
int kod_wait_file = 0;

int64_t kod_wait_event(int64_t ident, int64_t filter, int64_t data) {
    if (!kod_wait_hook) return 0;
    kod_wait_file = 0;
    if ((filter == -1 || filter == -2) && data == 0) {
        struct timeval tv = {0, 0};
        socklen_t size = sizeof tv;
        int option = filter == -1 ? SO_RCVTIMEO : SO_SNDTIMEO;
        if (getsockopt((int)ident, SOL_SOCKET, option, &tv, &size) == 0) {
            data = (int64_t)tv.tv_sec * 1000000000 + (int64_t)tv.tv_usec * 1000;
        } else {
            struct stat st;
            kod_wait_file = fstat((int)ident, &st) == 0 && (S_ISREG(st.st_mode) || S_ISDIR(st.st_mode));
        }
    }
    return kod_wait_hook(ident, filter, data);
}
