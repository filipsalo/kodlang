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

# Compiler-library .o files shared by `make stage1` (sh_kodc itself)
# and `make kod` (the native kod driver). Compiled into build/stage0/
# so anyone linking against the Kod compiler library reuses the same
# objects instead of rebuilding per app.
COMPILER_LIB_OBJS := \
    $(STAGE0)/_ast.o \
    $(STAGE0)/_lexing.o \
    $(STAGE0)/_parsing.o \
    $(STAGE0)/_codegen.o \
    $(STAGE0)/_build.o

COMPILER_KOD := \
    stdlib/kod/ast.kod \
    stdlib/kod/lexing.kod \
    stdlib/kod/parsing.kod \
    stdlib/kod/codegen.kod \
    stdlib/kod/build.kod \
    kodc.kod

STAGE1_OBJS := \
    $(STAGE1)/kodc.o \
    $(STAGE1)/runtime_main.o

LDFLAGS := -lc -L /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib -dead_strip
MACOS_VERSION := $(shell sw_vers -productVersion)
AS := as -target arm64-apple-darwin

.PHONY: all stage0 stage1 bootstrap bootstrap-snapshot kod test clean clean-apps clean-stage1

all: stage1

# Native `kod` driver — `kod build / run` orchestration written in
# kod itself. Once built, the Python `kod` CLI (kod/__main__.py)
# delegates straight to this binary for build / run / test / check
# so users skip the Python startup tax.
KOD_APP := build/apps/kod
kod: $(KOD_APP)/kod

$(KOD_APP)/kod: $(STAGE0_OBJS) $(COMPILER_LIB_OBJS) $(KOD_APP)/_kod.o $(KOD_APP)/runtime_main.o
	mkdir -p $(KOD_APP)
	ld -macos_version_min $(MACOS_VERSION) $(LDFLAGS) -o $@ \
	    $(STAGE0_OBJS) $(COMPILER_LIB_OBJS) $(KOD_APP)/_kod.o $(KOD_APP)/runtime_main.o

$(KOD_APP)/_kod.o: tools/kod.kod $(COMPILER_KOD)
	mkdir -p $(KOD_APP)
	$(KODC) _compile $< $@

$(KOD_APP)/runtime_main.s: tools/kod.kod
	mkdir -p $(KOD_APP)
	$(KODC_EMIT_MAIN) tools/kod.kod $@

$(KOD_APP)/runtime_main.o: $(KOD_APP)/runtime_main.s
	$(AS) -o $@ $<

stage0: $(STAGE0_OBJS)

# C runtime objects: arena (bump allocator) + the rest of the C glue
# (str/array primitives, panic, test runtime, …).
$(STAGE0)/arena.o: stdlib/arena.c
	mkdir -p $(STAGE0)
	clang -c -o $@ $<

$(STAGE0)/runtime.o: stdlib/runtime.c
	mkdir -p $(STAGE0)
	clang -c -o $@ $<

# Stdlib .kod modules — each compiled to its own .o via the
# bootstrap snapshot (or the Python interpreter when the snapshot
# is missing, e.g. during bootstrap-snapshot). $(KODC) _compile
# drives codegen + `as` in a single subprocess.
$(STAGE0)/_builtins.o: stdlib/builtins.kod
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_int64.o: stdlib/primitives/int64.kod
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_str.o: stdlib/primitives/str.kod
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_bool.o: stdlib/primitives/bool.kod
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_io.o: stdlib/io.kod
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_process.o: stdlib/process.kod
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_time.o: stdlib/time.kod
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

# Compiler-library .o files shared between sh_kodc and the kod tool.
# The $(COMPILER_KOD) dep means a touch to ANY compiler source
# retriggers the lot — over-conservative but matches how stage1
# treats the same sources.
$(STAGE0)/_ast.o: stdlib/kod/ast.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_lexing.o: stdlib/kod/lexing.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_parsing.o: stdlib/kod/parsing.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_codegen.o: stdlib/kod/codegen.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

$(STAGE0)/_build.o: stdlib/kod/build.kod $(COMPILER_KOD)
	mkdir -p $(STAGE0)
	$(KODC) _compile $< $@

stage1: $(STAGE1)/sh_kodc

$(STAGE1)/sh_kodc: $(STAGE0_OBJS) $(COMPILER_LIB_OBJS) $(STAGE1_OBJS)
	mkdir -p $(STAGE1)
	ld -macos_version_min $(MACOS_VERSION) $(LDFLAGS) -o $@ \
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
