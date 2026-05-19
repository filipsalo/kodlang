# Kod build chain.
#
# Targets:
#   make             same as `make stage1` (build sh_kodc, the self-hosted compiler)
#   make stage0      build shared stdlib objects under build/stage0/
#   make stage1      build sh_kodc under build/stage1/
#   make bootstrap   wipe build/ and rebuild stage0 + stage1 from scratch
#   make test        run pytest
#   make clean-apps  drop build/apps/ (per-app outputs)
#   make clean       drop build/ entirely
#
# Layout:
#   build/stage0/  arena.o, runtime.o, _builtins.o, _int64.o, _str.o, _bool.o
#   build/stage1/  the compiler-source .{s,o}, runtime_main.{s,o}, sh_kodc
#   build/apps/<stem>/  per-app artifacts + final executable

PY := uv run python
KOD := $(PY) -m kod

STAGE0 := build/stage0
STAGE1 := build/stage1

STAGE0_OBJS := \
    $(STAGE0)/arena.o \
    $(STAGE0)/runtime.o \
    $(STAGE0)/_builtins.o \
    $(STAGE0)/_int64.o \
    $(STAGE0)/_str.o \
    $(STAGE0)/_bool.o

STAGE0_SOURCES := \
    stdlib/arena.c \
    stdlib/runtime.c \
    stdlib/builtins.kod \
    stdlib/primitives/int64.kod \
    stdlib/primitives/str.kod \
    stdlib/primitives/bool.kod

COMPILER_KOD := \
    stdlib/kod/ast.kod \
    stdlib/kod/lexing.kod \
    stdlib/kod/parsing.kod \
    stdlib/kod/codegen.kod \
    kodc.kod

STAGE1_OBJS := \
    $(STAGE1)/lexing.o \
    $(STAGE1)/parsing.o \
    $(STAGE1)/codegen.o \
    $(STAGE1)/kodc.o \
    $(STAGE1)/runtime_main.o

LDFLAGS := -lc -L /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib
MACOS_VERSION := $(shell sw_vers -productVersion)
AS := as -target arm64-apple-darwin

.PHONY: all stage0 stage1 bootstrap test clean clean-apps clean-stage1

all: stage1

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

# Each compiler-source .kod file is interpreted via stage0 (Python interpreter
# driving kodc.kod) to produce a .s, which we then assemble.
$(STAGE1)/lexing.s: stdlib/kod/lexing.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KOD) interpret kodc.kod $< > $@

$(STAGE1)/parsing.s: stdlib/kod/parsing.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KOD) interpret kodc.kod $< > $@

$(STAGE1)/codegen.s: stdlib/kod/codegen.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KOD) interpret kodc.kod $< > $@

$(STAGE1)/kodc.s: kodc.kod $(COMPILER_KOD)
	mkdir -p $(STAGE1)
	$(KOD) interpret kodc.kod $< > $@

$(STAGE1)/runtime_main.s: kodc.kod kod/builder.py
	mkdir -p $(STAGE1)
	$(KOD) _emit-runtime-main kodc.kod $@

$(STAGE1)/%.o: $(STAGE1)/%.s
	$(AS) -o $@ $<

bootstrap:
	rm -rf build
	$(MAKE) stage1

test: stage1
	uv run pytest tests/

clean-apps:
	rm -rf build/apps

clean-stage1:
	rm -rf $(STAGE1)

clean:
	rm -rf build
