#!/bin/sh
# Build the native self-hosted compiler at build/sh_kodc.
#
# Bootstraps from kodc.kod via the Python interpreter on the first run.
# On subsequent runs, only the assemble + link steps re-execute unless the
# .s outputs change.
set -e

cd "$(dirname "$0")/.."

mkdir -p build/sh

# Emit the .o files for arena, runtime, _builtins, _io via the Python builder
# (which itself will now use sh_kodc once it exists; see kod/builder.py).
# We run any tiny program just to materialise those supporting objects.
uv run python -m kod --no-type-check build tests/hello.kod >/dev/null 2>&1 || true

# Drive kodc.kod (interpreted) over each compiler-source file. These are the
# slow steps; we only re-do them when the source is newer than the .s output.
gen() {
    src="$1"; dst="$2"
    if [ ! -f "$dst" ] || [ "$src" -nt "$dst" ]; then
        echo "  kodc.kod $src -> $dst"
        uv run python -m kod --no-type-check interpret kodc.kod "$src" > "$dst"
    fi
}

gen stdlib/kod/lexing.kod   build/sh/lexing.s
gen stdlib/kod/parsing.kod  build/sh/parsing.s
gen stdlib/kod/codegen.kod  build/sh/codegen.s
gen kodc.kod                build/sh/kodc.s

assemble() {
    src="$1"; dst="${src%.s}.o"
    if [ ! -f "$dst" ] || [ "$src" -nt "$dst" ]; then
        as -target arm64-apple-darwin -o "$dst" "$src"
    fi
}

assemble build/sh/lexing.s
assemble build/sh/parsing.s
assemble build/sh/codegen.s
assemble build/sh/kodc.s

cat > build/runtime_main.s << 'EOF'
.text
.globl _main
_main:
    stp x29, x30, [sp, #-64]!
    mov x29, sp
    stp x19, x20, [sp, #16]
    stp x21, x22, [sp, #32]
    str x23, [sp, #48]
    mov x19, x0
    mov x20, x1
    lsl x0, x19, #3
    bl _arena_alloc
    mov x21, x0
    mov x22, #0
Lloop:
    cmp x22, x19
    b.ge Ldone
    ldr x23, [x20, x22, lsl #3]
    str x23, [x21, x22, lsl #3]
    add x22, x22, #1
    b Lloop
Ldone:
    mov x0, #24
    bl _arena_alloc
    str x21, [x0]
    str x19, [x0, #8]
    str x19, [x0, #16]
    bl $kodc$main
    ldr x23, [sp, #48]
    ldp x21, x22, [sp, #32]
    ldp x19, x20, [sp, #16]
    ldp x29, x30, [sp], #64
    ret
EOF
as -target arm64-apple-darwin -o build/runtime_main.o build/runtime_main.s

ld -arch arm64 \
   -platform_version macos 13.0 13.0 \
   -L /Library/Developer/CommandLineTools/SDKs/MacOSX.sdk/usr/lib \
   -lSystem \
   -o build/sh_kodc \
   build/runtime_main.o build/runtime.o build/arena.o \
   build/_builtins.o build/_io.o \
   build/_int64.o build/_str.o build/_bool.o \
   build/sh/lexing.o build/sh/parsing.o build/sh/codegen.o build/sh/kodc.o 2>/dev/null

echo "built build/sh_kodc"
