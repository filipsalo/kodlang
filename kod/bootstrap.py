"""The `_main` shim writer for the no-snapshot bootstrap.

When `bootstrap/sh_kodc` is missing, the Makefile compiles the compiler under
the interpreter and needs the shim of `kodc.kod` and `tools/kod.kod` before
any `sh_kodc` exists. `tests/bootstrap_test.py` keeps this identical, byte for
byte, to `sh_kodc _emit-runtime-main` (kodc.kod:build_runtime_main_asm): the
templates below are that function's, dedented the way a Kod triple-quoted
string is. It does only what those two entries need: a path whose symbol it
can't write the way `build.path_to_prefix` does is refused, and it knows
nothing of a project module that shares its path with a stdlib module (the two
entries have no such twin; the test asserts it).
"""

import re
from pathlib import Path
from textwrap import dedent

from kod import ast
from kod.filesys import FileWrapper
from kod.program import Program

_PLAIN_PATH = re.compile(r"[A-Za-z0-9_/]+")


def module_prefix(source: Path) -> str:
    """The symbol prefix `build.path_to_prefix` gives the module at `source`,
    a path relative to the project root.

    Only plain paths are handled: letters, digits, `_` and `/`, not starting
    with a digit. Anything else is escaped by the compiler in ways written
    only there, so it is an error here rather than a wrong symbol."""
    path = source.with_suffix("")
    parts = path.parts
    if parts and parts[0] == "/":
        parts = parts[1:]
    if parts and parts[0] == "stdlib":
        parts = parts[1:]
    name = "/".join(parts)
    if not _PLAIN_PATH.fullmatch(name) or name[0].isdigit():
        raise ValueError(f"can't write the symbol prefix of {path} in Python")
    return name.replace("/", "$")


# `{unwrap}` is a Result main's exit: the Ok (discriminant 1) payload, else
# panic. The empty one leaves a blank line, as in kodc.kod.
_UNWRAP = dedent(
    """\
            ldr x9, [x0, #0]
            cmp x9, #1
            b.eq Lmain_ok
            ldr x0, [x0, #8]
            ldr x1, [x0, #8]
            ldr x9, [x1, #0]
            ldr x0, [x0, #0]
            blr x9
            bl _kod_panic
        Lmain_ok:
            ldr x0, [x0, #8]
    """
)

# main takes no argv and returns plainly: tail-call it.
_PLAIN = dedent(
    """\
    .text
    .globl _main
    _main:
        b ${mangled}$main
    .subsections_via_symbols
    """
)

# main takes no argv and returns a Result.
_RESULT = dedent(
    """\
    .text
    .globl _main
    _main:
        stp x29, x30, [sp, #-16]!
        mov x29, sp
        bl ${mangled}$main
    {unwrap}
        ldp x29, x30, [sp], #16
        ret
    .subsections_via_symbols
    """
)

# main takes argv: marshal (argc, argv) into a Kod string array before the
# call, then the optional Result unwrap.
_ARGV = dedent(
    """\
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
        ldr x0, [x20, x22, lsl #3]
        bl _kod_str_from_cstr
        str x0, [x21, x22, lsl #3]
        add x22, x22, #1
        b Lloop
    Ldone:
        mov x0, #24
        bl _arena_alloc
        str x21, [x0]
        str x19, [x0, #8]
        str x19, [x0, #16]
        bl ${mangled}$main
    {unwrap}
        ldr x23, [sp, #48]
        ldp x21, x22, [sp, #32]
        ldp x19, x20, [sp, #16]
        ldp x29, x30, [sp], #64
        ret
    .subsections_via_symbols
    """
)


def compose_runtime_main_asm(program: Program, file: FileWrapper) -> str:
    """Compose the runtime _main shim for the given entry file. The
    shape depends on whether main takes argv and whether it returns
    `T or Error`. Raises ValueError when there is no `main` or the
    path's symbol can't be written."""
    module = program.get_module(file.canonical_path.with_suffix(""))
    main_decl = next(
        (
            s
            for s in module.body
            if isinstance(s, ast.FunctionDeclaration) and s.name == "main"
        ),
        None,
    )
    if main_decl is None:
        raise ValueError(f"no `main` function in {file.canonical_path}")
    mangled = module_prefix(file.canonical_path)
    returns_result = ast.returns_result(main_decl, module, program)
    unwrap = _UNWRAP if returns_result else ""
    if len(main_decl.params) > 0:
        template = _ARGV
    elif returns_result:
        template = _RESULT
    else:
        template = _PLAIN
    return template.format(mangled=mangled, unwrap=unwrap)
