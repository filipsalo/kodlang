# Kod build chain.
#
# Targets:
#   make                  same as `make stage1` (build sh_kodc, the self-hosted compiler)
#   make stage0           build shared stdlib objects under build/stage0/
#   make stage1           build sh_kodc under build/stage1/
#   make bootstrap        wipe build/ and rebuild stage0 + stage1 from scratch
#   make bootstrap-snapshot
#                         force the slow Python path end-to-end and copy the
#                         resulting sh_kodc to bootstrap/sh_kodc. Run after
#                         changes that the checked-in snapshot can no longer
#                         handle (parser format, runtime ABI, …) and commit.
#   make test             run pytest
#   make clean-apps       drop build/apps/ (per-app outputs)
#   make clean            drop build/ entirely (keeps bootstrap/sh_kodc)
#
# Layout:
#   bootstrap/sh_kodc     arm64-darwin sh_kodc snapshot — checked in so a
#                         fresh clone (or `make clean`) can rebuild stage1
#                         in seconds instead of ~165 s in the Python interp.
#   build/stage0/         arena.o, runtime.o, _builtins.o, _int64.o, _str.o, _bool.o
#   build/stage1/         the compiler-source .{s,o}, runtime_main.{s,o}, sh_kodc
#   build/apps/<stem>/    per-app artifacts + final executable

PY := uv run python
KOD := $(PY) -m kod

# Compiler used to lower stage1 sources to .s. The checked-in snapshot
# is ~30× faster than the Python interpreter on a cold stage1 build;
# falls back to Python when the snapshot is missing (first build before
# the binary lands, or `make bootstrap-snapshot`).
BOOTSTRAP_SH_KODC := bootstrap/sh_kodc
KODC := $(if $(wildcard $(BOOTSTRAP_SH_KODC)),./$(BOOTSTRAP_SH_KODC),$(KOD) _interpret kodc.kod)
KODC_EMIT_MAIN := $(if $(wildcard $(BOOTSTRAP_SH_KODC)),./$(BOOTSTRAP_SH_KODC) _emit-runtime-main,$(KOD) _emit-runtime-main)

STAGE0 := build/stage0
STAGE1 := build/stage1

STAGE0_OBJS := \
    $(STAGE0)/arena.o \
    $(STAGE0)/runtime.o \
    $(STAGE0)/_builtins.o \
    $(STAGE0)/_int64.o \
    $(STAGE0)/_str.o \
    $(STAGE0)/_bool.o \
    $(STAGE0)/_io.o \
    $(STAGE0)/_process.o \
    $(STAGE0)/_time.o

STAGE0_SOURCES := \
    stdlib/arena.c \
    stdlib/runtime.c \
    stdlib/builtins.kod \
    stdlib/primitives/int64.kod \
    stdlib/primitives/str.kod \
    stdlib/primitives/bool.kod \
    stdlib/io.kod \
    stdlib/process.kod \
    stdlib/time.kod

COMPILER_KOD := \
    stdlib/kod/ast.kod \
    stdlib/kod/lexing.kod \
    stdlib/kod/parsing.kod \
    stdlib/kod/codegen.kod \
    stdlib/kod/build.kod \
    kodc.kod

STAGE1_OBJS := \
    $(STAGE1)/lexing.o \
    $(STAGE1)/parsing.o \
    $(STAGE1)/codegen.o \
    $(STAGE1)/build.o \
    $(STAGE1)/kodc.o \
    $(STAGE1)/runtime_main.o

LDFLAGS := -lc -L /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib
MACOS_VERSION := $(shell sw_vers -productVersion)
AS := as -target arm64-apple-darwin

.PHONY: all stage0 stage1 bootstrap bootstrap-snapshot kod test clean clean-apps clean-stage1

all: stage1

# Native `kod` driver — `kod build / run` orchestration written in kod
# itself. Built into build/apps/kod/kod by the Python `kod build`
# (which is the bootstrap path). Once present, users can prefer
# `./build/apps/kod/kod build foo.kod` over `uv run kod build foo.kod`
# to skip the Python startup tax.
kod: stage1
	$(KOD) build tools/kod.kod

stage0: $(STAGE0_OBJS)

# The stage0 rule builds *all* stage0 objects in one shot via builder.py
# (which already knows how to assemble each stdlib module). Touching any
# of the stage0 sources retriggers the bundle.
$(STAGE0_OBJS): $(STAGE0_SOURCES)
	$(KOD) _build-stage0

stage1: $(STAGE1)/sh_kodc

$(STAGE1)/sh_kodc: $(STAGE1_OBJS) $(STAGE0_OBJS)
	mkdir -p $(STAGE1)
	ld -macos_version_min $(MACOS_VERSION) $(LDFLAGS) -o $@ \
	    $(STAGE0_OBJS) $(STAGE1_OBJS)

# Each compiler-source .kod file is lowered to .s by $(KODC) — the
# checked-in arm64-darwin snapshot when present, the Python interpreter
# driving kodc.kod otherwise.
$(STAGE1)/lexing.s: stdlib/kod/lexing.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KODC) $< > $@

$(STAGE1)/parsing.s: stdlib/kod/parsing.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KODC) $< > $@

$(STAGE1)/codegen.s: stdlib/kod/codegen.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KODC) $< > $@

$(STAGE1)/build.s: stdlib/kod/build.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KODC) $< > $@

$(STAGE1)/kodc.s: kodc.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KODC) $< > $@

$(STAGE1)/runtime_main.s: kodc.kod kod/builder.py
	mkdir -p $(STAGE1)
	$(KODC_EMIT_MAIN) kodc.kod $@

$(STAGE1)/%.o: $(STAGE1)/%.s
	$(AS) -o $@ $<

bootstrap:
	rm -rf build
	$(MAKE) stage1

# Rebuild the checked-in arm64-darwin snapshot from scratch via the
# Python interpreter, then drop the result into bootstrap/. Run this
# after a change that the current snapshot can't compile (parser
# format, runtime ABI, codegen shape, …) and commit the new binary.
# Hiding the snapshot first forces the slow Python path; the recursive
# `make stage1` reruns the Makefile so KODC re-evaluates to the
# Python form.
bootstrap-snapshot:
	@echo "==> Rebuilding bootstrap snapshot via Python interpreter (slow)..."
	rm -f $(BOOTSTRAP_SH_KODC)
	rm -rf build/stage0 build/stage1
	$(MAKE) stage1
	@mkdir -p $(dir $(BOOTSTRAP_SH_KODC))
	cp build/stage1/sh_kodc $(BOOTSTRAP_SH_KODC)
	@echo "==> Wrote $(BOOTSTRAP_SH_KODC). Verify, then commit it."

test: stage1
	uv run pytest tests/

clean-apps:
	rm -rf build/apps

clean-stage1:
	rm -rf $(STAGE1)

clean:
	rm -rf build
