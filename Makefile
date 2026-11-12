# Kod build chain.
#
# Targets:
#   make                  same as `make stage1` (build sh_kodc, the self-hosted compiler)
#   make stage0           build shared stdlib objects under build/stage0/
#   make stage1           build sh_kodc under build/stage1/
#   make bootstrap        wipe build/ and rebuild stage0 + stage1 from scratch
#   make bootstrap-snapshot
#                         run selfhost-check, then copy the compiler it built
#                         to bootstrap/sh_kodc. Commit the result on its own.
#   make test             build sh_kodc + the kod driver, then run pytest
#                         (example programs, every *_test.kod, self-hosting checks):
#                         in parallel, then the `serial` tests one at a time
#   make gates            make test, then make test again with a poisoned
#                         runtime (-DRC_POISON); run before committing
#   make selfhost-check   fixed point: stage1 compiles the compiler (stage2),
#                         stage2 compiles it again (stage3); asm must match,
#                         and stage1 and stage2 must compile every .kod file
#                         in the repo identically
#   make asm-diff [BASE=rev]
#                         compile every .kod file with sh_kodc built at BASE
#                         (default HEAD) and with the working tree's; report
#                         differences. A pure compiler refactor shows none.
#   make clean-apps       drop build/apps/ and build/cache/ (per-app outputs)
#   make clean            drop build/ entirely (keeps bootstrap/sh_kodc)
#
# Linking: link.cfg (and link.local.cfg, untracked, which overrides single
# names on one machine) holds the linker command, the C compiler and its
# flags, and the always-linked C files and Kod modules. This Makefile
# includes it and tools/kod.kod reads the same files, so both link alike.
# The objects and links are rebuilt when the files change, or when the
# configuration in force differs from the one build/.link-config records; the
# C objects also when a header in stdlib/ changes.
#
# Layout:
#   bootstrap/sh_kodc     arm64-darwin sh_kodc snapshot: what builds stage1,
#                         on a fresh clone or after `make clean`. The only way
#                         in (see docs/self-hosting.md for recovering one).
#   build/stage0/         the objects every program links (link.cfg's RUNTIME_C
#                         and STAGE0_KOD) and the compiler library
#   build/stage1/         kodc.{s,o}, runtime_main.{s,o}, sh_kodc
#   build/apps/<stem>/    the final executable, and its objects in <stem>.obj/

PY := uv run python

# Compiler used to lower stage1 sources to .s.
BOOTSTRAP_SH_KODC := bootstrap/sh_kodc
KODC := ./$(BOOTSTRAP_SH_KODC)
KODC_EMIT_MAIN := ./$(BOOTSTRAP_SH_KODC) _emit-runtime-main

STAGE0 := build/stage0
STAGE1 := build/stage1

# The link configuration: LINK, CC, CFLAGS, RUNTIME_C and STAGE0_KOD.
# link.local.cfg, if there is one, overrides single names. Every rule that
# links, or compiles a C file, depends on the files, since they hold the
# command and its flags.
#
# link.local.cfg overrides and does not add: a name it sets must be one that
# link.cfg sets, since Make would take any other (a typo, STAGE0, SHELL) as it
# comes. The names are read with sed, before the file is included.
HASH := \#
CFG_NAME_SED := s/^[ ]*\([^$(HASH) :=]*\)[ ]*[:?+]*=.*/\1/p
CFG_NAMES := $(shell sed -n '$(CFG_NAME_SED)' link.cfg)
LOCAL_NAMES := $(shell sed -n '$(CFG_NAME_SED)' link.local.cfg 2>/dev/null)
$(foreach n,$(LOCAL_NAMES),$(if $(filter $(n),$(CFG_NAMES)),,$(error link.local.cfg sets $(n), which link.cfg does not set; it only overrides those)))
include link.cfg
-include link.local.cfg
$(foreach n,LINK RUNTIME_C STAGE0_KOD,$(if $(strip $($(n))),,$(error link.cfg and link.local.cfg set no $(n))))

# Make sees that a configuration file changed by its time, but not that one is
# gone or has lost a name. So the configuration in force is also recorded in
# $(LINK_STAMP): when it differs from the record, the record is remade, and
# whatever depends on it with it.
LINK_STAMP := build/.link-config
LINK_NOW := $(foreach n,$(CFG_NAMES),$(n)=$($(n));)
LINK_SAME := $(shell test "$$(cat $(LINK_STAMP) 2>/dev/null)" = '$(LINK_NOW)' && echo same)
ifeq ($(LINK_SAME),)
.PHONY: $(LINK_STAMP)
endif
LINK_CFG := link.cfg $(wildcard link.local.cfg) $(LINK_STAMP)

ifneq ($(filter-out %.c,$(RUNTIME_C)),)
$(error RUNTIME_C must name only .c files: $(RUNTIME_C))
endif
ifneq ($(filter-out %.kod,$(STAGE0_KOD)),)
$(error STAGE0_KOD must name only .kod files: $(STAGE0_KOD))
endif

# Always-linked objects, in link order: each RUNTIME_C file lowers to
# $(STAGE0)/<name>.o and each STAGE0_KOD module to $(STAGE0)/_<basename>.o.
STAGE0_OBJS := \
    $(patsubst %.c,$(STAGE0)/%.o,$(notdir $(RUNTIME_C))) \
    $(patsubst %,$(STAGE0)/_%.o,$(basename $(notdir $(STAGE0_KOD))))

# Every module compile reads the stage0 sources (builtins generics are
# monomorphised into each object; io/process/time layouts are imported),
# so any edit to one recompiles everything — a few seconds. Also depend
# on the compiler binary itself.
KODC_DEP := $(patsubst ./%,%,$(firstword $(KODC)))
KOD_DEPS := $(KODC_DEP) $(STAGE0_KOD)

# Compiler-library .o files shared by `make stage1` (sh_kodc itself)
# and `make kod` (the native kod driver). Compiled into build/stage0/
# so anyone linking against the Kod compiler library reuses the same
# objects instead of rebuilding per app.
COMPILER_LIB_OBJS := \
    $(STAGE0)/_ast.o \
    $(STAGE0)/_lexing.o \
    $(STAGE0)/_parsing.o \
    $(STAGE0)/_regalloc.o \
    $(STAGE0)/_codegen.o \
    $(STAGE0)/_build.o

COMPILER_KOD := \
    stdlib/kod/ast.kod \
    stdlib/kod/lexing.kod \
    stdlib/kod/parsing.kod \
    stdlib/kod/regalloc.kod \
    stdlib/kod/codegen.kod \
    stdlib/kod/build.kod \
    kodc.kod

STAGE1_OBJS := \
    $(STAGE1)/kodc.o \
    $(STAGE1)/runtime_main.o

AS := as -target arm64-apple-darwin

.PHONY: all stage0 stage1 bootstrap bootstrap-snapshot kod test gates selfhost-check asm-diff clean clean-apps clean-stage1

# sh_kodc writes complete-looking assembly even when it reports errors;
# without this a failed compile leaves a fresh .s that the next make
# would happily assemble.
.DELETE_ON_ERROR:

all: stage1

$(BOOTSTRAP_SH_KODC):
	@echo "$@ not found; restore it with: git checkout -- $@ (see docs/self-hosting.md)" >&2
	@exit 1

$(LINK_STAMP):
	mkdir -p $(dir $@)
	echo '$(LINK_NOW)' > $@

# Native `kod` driver: `kod build / run / test / check`, written in Kod.
# The launcher (kod/__main__.py) hands off to this binary.
KOD_APP := build/apps/kod
kod: $(KOD_APP)/kod

$(KOD_APP)/kod: $(STAGE0_OBJS) $(COMPILER_LIB_OBJS) $(KOD_APP)/_kod.o $(KOD_APP)/runtime_main.o $(LINK_CFG)
	mkdir -p $(KOD_APP)
	$(LINK) -o $@ \
	    $(STAGE0_OBJS) $(COMPILER_LIB_OBJS) $(KOD_APP)/_kod.o $(KOD_APP)/runtime_main.o

$(KOD_APP)/_kod.s: tools/kod.kod $(COMPILER_KOD)
	mkdir -p $(KOD_APP)
	$(KODC) $< > $@

$(KOD_APP)/_kod.o: $(KOD_APP)/_kod.s
	$(AS) -o $@ $<

$(KOD_APP)/runtime_main.s: tools/kod.kod
	mkdir -p $(KOD_APP)
	$(KODC_EMIT_MAIN) tools/kod.kod $@

$(KOD_APP)/runtime_main.o: $(KOD_APP)/runtime_main.s
	$(AS) -o $@ $<

stage0: $(STAGE0_OBJS)

# C runtime objects (the arena allocator, the str/array primitives, panic, the
# test runtime, ...): one rule per RUNTIME_C file. They depend on link.cfg
# because that holds the compiler and its flags, and on the headers in stdlib/
# (kod_rt.h declares the layout of str and arrays) since there are no
# dependency files: a changed layout must not leave runtime.o stale next to
# the C files programs compile against the header.
C_HEADERS := $(wildcard stdlib/*.h)
define runtime_c_rule
$(STAGE0)/$(basename $(notdir $(1))).o: $(1) $(LINK_CFG) $(C_HEADERS)
	mkdir -p $(STAGE0)
	$$(CC) $$(CFLAGS) -c -o $$@ $$<
endef
$(foreach c,$(RUNTIME_C),$(eval $(call runtime_c_rule,$(c))))

# Always-linked stdlib .kod modules (STAGE0_KOD) — each lowered to .s by
# $(KODC) then assembled.
define stage0_kod_rule
$(STAGE0)/_$(basename $(notdir $(1))).s: $(1)
	mkdir -p $(STAGE0)
	$$(KODC) $$< > $$@
endef
$(foreach m,$(STAGE0_KOD),$(eval $(call stage0_kod_rule,$(m))))

# Compiler-library .s files shared between sh_kodc and the kod tool.
# The $(COMPILER_KOD) dep means a touch to ANY compiler source
# retriggers the lot — over-conservative but matches how stage1
# treats the same sources.
$(STAGE0)/_ast.s: stdlib/kod/ast.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) $< > $@

$(STAGE0)/_lexing.s: stdlib/kod/lexing.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) $< > $@

$(STAGE0)/_parsing.s: stdlib/kod/parsing.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) $< > $@

$(STAGE0)/_regalloc.s: stdlib/kod/regalloc.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) $< > $@

$(STAGE0)/_codegen.s: stdlib/kod/codegen.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) $< > $@

$(STAGE0)/_build.s: stdlib/kod/build.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) $< > $@

# Assemble any stage0 .s (stdlib + compiler-lib) to its .o. The C
# objects (arena.o, rc.o, runtime.o) have explicit rules above and
# don't match this (no corresponding .s).
$(STAGE0)/%.o: $(STAGE0)/%.s
	$(AS) -o $@ $<

stage1: $(STAGE1)/sh_kodc

# build/cache/ holds module objects keyed by this compiler (docs/cli.md), so a
# new one makes them all dead.
$(STAGE1)/sh_kodc: $(STAGE0_OBJS) $(COMPILER_LIB_OBJS) $(STAGE1_OBJS) $(LINK_CFG)
	mkdir -p $(STAGE1)
	rm -rf build/cache
	$(LINK) -o $@ \
	    $(STAGE0_OBJS) $(COMPILER_LIB_OBJS) $(STAGE1_OBJS)

# kodc.kod is the only compiler source that's stage1-only — the
# lexer/parser/codegen/build library lives in stage0/COMPILER_LIB_OBJS
# and is shared with the kod tool.
$(STAGE1)/kodc.s: kodc.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KODC) $< > $@

$(STAGE1)/runtime_main.s: kodc.kod
	mkdir -p $(STAGE1)
	$(KODC_EMIT_MAIN) kodc.kod $@

$(STAGE1)/%.o: $(STAGE1)/%.s
	$(AS) -o $@ $<

# Extra prerequisites for every .kod lowering above (see KOD_DEPS).
$(patsubst %.o,%.s,$(filter $(STAGE0)/_%.o,$(STAGE0_OBJS) $(COMPILER_LIB_OBJS))) \
$(STAGE1)/kodc.s $(KOD_APP)/_kod.s: $(KOD_DEPS)
$(STAGE1)/runtime_main.s $(KOD_APP)/runtime_main.s: $(KODC_DEP)

bootstrap:
	rm -rf build
	$(MAKE) stage1

# Replace the checked-in snapshot with the compiler selfhost-check built, once
# that compiler has reproduced itself byte for byte. Nothing touches the old
# snapshot before that. The mv is not a cp over the old file: macOS kills a
# signed binary that was rewritten in place.
bootstrap-snapshot: selfhost-check
	cmp $(SELFHOST)/stage2/stage1/sh_kodc $(SELFHOST)/stage3/stage1/sh_kodc
	cp $(SELFHOST)/stage2/stage1/sh_kodc $(BOOTSTRAP_SH_KODC).new
	mv $(BOOTSTRAP_SH_KODC).new $(BOOTSTRAP_SH_KODC)
	@echo "==> Wrote $(BOOTSTRAP_SH_KODC). Commit it on its own."

test: stage1 kod
	uv run pytest -q -n auto --dist loadgroup -m "not serial" tests/
	uv run pytest -q -m serial tests/

# The poisoned pass writes link.local.cfg, so one that is there already is not
# ours to replace; the trap removes ours and rebuilds however the pass ends.
POISON_CFLAGS := -target arm64-apple-darwin -I stdlib -O2 -DRC_POISON
gates:
	@if [ -e link.local.cfg ]; then echo "gates: link.local.cfg exists; move it aside first" >&2; exit 1; fi
	$(MAKE) -s test
	@echo "==> gates: again with a poisoned runtime"
	@trap 'rm -f link.local.cfg; $(MAKE) -s stage1 kod' EXIT; \
	    echo 'CFLAGS := $(POISON_CFLAGS)' > link.local.cfg && $(MAKE) -s test
	@echo "==> gates: passed"

# Rebuild the whole compiler (stage0 + stage1) twice more, first with the
# current sh_kodc and then with the result, into scratch dirs. The two
# rebuilds must emit byte-identical assembly.
# Stage1 and stage2 must also agree on the corpus: the snapshot can miscompile new code.
SELFHOST := build/selfhost
selfhost-check: stage1
	rm -rf $(SELFHOST)
	$(MAKE) -s stage1 STAGE0=$(SELFHOST)/stage2/stage0 STAGE1=$(SELFHOST)/stage2/stage1 \
	    KODC=./$(STAGE1)/sh_kodc KODC_EMIT_MAIN="./$(STAGE1)/sh_kodc _emit-runtime-main"
	$(MAKE) -s stage1 STAGE0=$(SELFHOST)/stage3/stage0 STAGE1=$(SELFHOST)/stage3/stage1 \
	    KODC=./$(SELFHOST)/stage2/stage1/sh_kodc KODC_EMIT_MAIN="./$(SELFHOST)/stage2/stage1/sh_kodc _emit-runtime-main"
	@diff -r -x '*.o' -x sh_kodc $(SELFHOST)/stage2 $(SELFHOST)/stage3 \
	    || { echo "selfhost-check: stage2 and stage3 assembly differ (see diff above)"; exit 1; }
	@echo "selfhost-check: stage2 == stage3"
	@$(PY) tools/asm_diff.py --compilers $(STAGE1)/sh_kodc $(SELFHOST)/stage2/stage1/sh_kodc

BASE ?= HEAD
asm-diff:
	$(PY) tools/asm_diff.py $(BASE)

clean-apps:
	rm -rf build/apps build/cache

clean-stage1:
	rm -rf $(STAGE1)

clean:
	rm -rf build
