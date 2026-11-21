"""The `kod` code blocks in docs/*.md compile.

Each block is compiled on its own, as a program: its top-level declarations
(types, functions, imports, constants) as they are, and its other lines as the
body of a `main`. A block that declares `main` is a program already.

- Declarations from earlier blocks of the same page are there too, so a block
  can use the types and functions the page has shown, unless it declares a
  name of its own again.
- A line whose comment says `error` shows what the compiler rejects, and is
  left out.
- An HTML comment right before a block, which the page doesn't show, can give
  it setup code: `<!-- kod: let nums = [1, 2, 3] -->` (one or more lines), or
  leave it out: `<!-- no-check -->`. Setup declarations of new names are
  carried to later blocks too.
- A fragment that uses `try` runs in a function returning `int64 or Error`.
- Beside a `func`, `mut name: T = ...` at the left margin is a module variable.
- A block that only shows signatures (a `func` line with no body) or uses `...`
  or `<name>` as a placeholder is left out.
"""

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SH_KODC = ROOT / "build" / "stage1" / "sh_kodc"

BLOCK = re.compile(r"(?:<!--\s*(no-check|kod:(.*?))\s*-->\s*\n)?```kod\n(.*?)```", re.S)
# A top-level `let NAME` is a constant; a `mut x` at the left margin of a
# fragment is a local, unless the fragment declares functions and it has a type.
DECL = re.compile(
    r"^(type |shared |func |interface |import |extern |test |let [A-Z][A-Z_0-9]*[:\s])"
)
# Beside functions, a typed `mut x: T` is a module variable.
FUNCS_DECL = re.compile(DECL.pattern[:-1] + r"|mut [A-Za-z_][A-Za-z_0-9]*:)")
# In a block with `func main`, every left-margin line is a declaration.
PROGRAM_DECL = re.compile(
    r"^(type |shared |func |interface |import |extern |test |let |mut )"
)
NAME = re.compile(
    r"^(?:extern func|func|type|interface|let|mut)\s+([A-Za-z_][A-Za-z_0-9]*)|^import\s+(\"[^\"]*\"(?: \{)?)"
)


def shape_skipped(code: str) -> bool:
    for line in code.split("\n"):
        if "extern" in line:
            continue
        if re.match(r"^\s*func [^{]*\)( -> [^{]+)?\s*$", line):
            return True
        if "..." in line or re.search(r"<[a-z][a-z ]*>", line):
            return True
    return False


def split(code: str, program: bool = False) -> tuple[list[list[str]], list[str]]:
    """The top-level declarations of a block, each as its lines, and the rest."""
    decl = (
        PROGRAM_DECL
        if program
        else FUNCS_DECL
        if re.search(r"^func ", code, re.M)
        else DECL
    )
    decls: list[list[str]] = []
    stmts: list[str] = []
    in_decl = False
    for line in code.split("\n"):
        if re.search(r"//.*\berror\b", line):
            continue
        if line.strip() and not line.startswith((" ", "\t", "}")):
            in_decl = bool(decl.match(line))
            if in_decl:
                decls.append([])
        if in_decl:
            decls[-1].append(line)
        else:
            stmts.append(line)
    return decls, stmts


def decl_name(lines: list[str]) -> str:
    m = NAME.match(lines[0])
    if not m:
        return lines[0]
    return m.group(1) or m.group(2)


def programs():
    for page in sorted((ROOT / "docs").glob("*.md")):
        text = page.read_text()
        carried: dict[str, list[str]] = {}
        for m in BLOCK.finditer(text):
            marker, setup, code = m.group(1), m.group(2) or "", m.group(3)
            line = text[: m.start(3)].count("\n") + 1
            if marker == "no-check" or shape_skipped(code):
                continue
            program = bool(re.search(r"^func main\(", code, re.M))
            setup = setup.strip() if "\n" not in setup.strip() else setup.strip("\n")
            setup_decls, setup_stmts = split(setup, program)
            decls, stmts = split(code, program)
            own = setup_decls + decls
            if program:
                yield f"{page.name}:{line}", "\n".join("\n".join(d) for d in own) + "\n"
            else:
                names = {decl_name(d) for d in own}
                earlier = [d for n, d in carried.items() if n not in names]
                body = "\n".join(
                    "    " + s if s.strip() else s for s in setup_stmts + stmts
                )
                src = "\n\n".join("\n".join(d) for d in earlier + own)
                if re.search(r"\btry\b", "\n".join(stmts)):
                    # `try` needs a function that can return an error.
                    main = f"func example() -> int64 or Error {{\n{body}\n    return 0\n}}\n\nfunc main() -> int64 {{\n    return must example()\n}}\n"
                else:
                    main = f"func main() -> int64 {{\n{body}\n    return 0\n}}\n"
                yield f"{page.name}:{line}", f"{src}\n\n{main}"
            # A setup that stands in for one of the page's declarations isn't
            # carried; its other declarations are.
            for d in setup_decls:
                if decl_name(d) not in carried:
                    carried[decl_name(d)] = d
            for d in decls:
                if decl_name(d) != "main":
                    carried[decl_name(d)] = d


EXAMPLES = list(programs())


@pytest.mark.parametrize("where,src", EXAMPLES, ids=[w for w, _ in EXAMPLES])
def test_docs_example_compiles(where, src, tmp_path, sh_kodc):
    path = tmp_path / "example.kod"
    path.write_text(src)
    r = subprocess.run(
        [str(SH_KODC), str(path)], capture_output=True, text=True, cwd=ROOT
    )
    errors = [
        line.split(": error: ", 1)[1]
        for line in r.stderr.split("\n")
        if ": error: " in line
    ]
    assert r.returncode == 0, (
        f"docs/{where}: " + "; ".join(errors[:3]) + f"\n--- as compiled:\n{src}"
    )
