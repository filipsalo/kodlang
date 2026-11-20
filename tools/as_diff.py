"""Compare kod/macho's objects with clang's, by what they mean.

Usage: uv run python tools/as_diff.py [FILE.kod ...]   (default: every .kod in git)

Compiles each file with build/stage1/sh_kodc, assembles the assembly twice
(clang's assembler, and `sh_kodc _assemble`, which is kod/macho), and compares
the two objects. The layouts differ on purpose (docs/ir.md, step 9), so the
comparison is by meaning:

- each section: its name, flags, address and bytes, with every field a
  relocation fills cleared;
- each relocation: its section, address, kind and target, the target an
  undefined symbol's name or an address (a defined symbol's, or a section's,
  plus the addend);
- the symbols other than temporary ones (L..., ltmp...): name, kind, section,
  value, and weak or not; the undefined ones by name;
- the header flags and the minimum OS version.

Prints each file that differs and the first difference; exits 1 if any did.
"""

import struct
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SH_KODC = ROOT / "build" / "stage1" / "sh_kodc"
CLANG_AS = ["clang", "-target", "arm64-apple-darwin", "-c", "-x", "assembler"]

UNSIGNED, BRANCH26, PAGE21, PAGEOFF12, GOT_PAGE21, GOT_PAGEOFF12, ADDEND = (
    0,
    2,
    3,
    4,
    5,
    6,
    10,
)
NAMES = {
    0: "UNSIGNED",
    2: "BRANCH26",
    3: "PAGE21",
    4: "PAGEOFF12",
    5: "GOT_LOAD_PAGE21",
    6: "GOT_LOAD_PAGEOFF12",
}


def read_object(data: bytes) -> dict:
    _magic, _cpu, _sub, _ftype, ncmds, _size, flags, _ = struct.unpack_from(
        "<IiiIIIII", data, 0
    )
    off = 32
    sections, symbols, minos = [], [], None
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, off)
        if cmd == 0x19:
            nsects = struct.unpack_from("<I", data, off + 64)[0]
            for i in range(nsects):
                f = struct.unpack_from("<16s16sQQIIIIIIII", data, off + 72 + 80 * i)
                sections.append(
                    {
                        "name": (
                            f[1].rstrip(b"\0") + b"," + f[0].rstrip(b"\0")
                        ).decode(),
                        "addr": f[2],
                        "bytes": bytearray(data[f[4] : f[4] + f[3]]),
                        "reloff": f[6],
                        "nreloc": f[7],
                        "flags": f[8],
                    }
                )
        elif cmd == 0x2:
            symoff, nsyms, stroff, _strsize = struct.unpack_from("<IIII", data, off + 8)
            for i in range(nsyms):
                strx, ntype, nsect, desc, value = struct.unpack_from(
                    "<IBBHQ", data, symoff + 16 * i
                )
                end = data.index(b"\0", stroff + strx)
                symbols.append(
                    (data[stroff + strx : end].decode(), ntype, nsect, desc, value)
                )
        elif cmd == 0x32:
            minos = struct.unpack_from("<I", data, off + 12)[0]
        off += size
    return {
        "flags": flags,
        "sections": sections,
        "symbols": symbols,
        "minos": minos,
        "data": data,
    }


def clear(section: bytearray, at: int, kind: int, length: int) -> int:
    """Clears the field a relocation fills; gives what was there."""
    if kind == UNSIGNED:
        size = 1 << length
        value = int.from_bytes(section[at : at + size], "little", signed=True)
        section[at : at + size] = bytes(size)
        return value
    word = int.from_bytes(section[at : at + 4], "little")
    if kind == BRANCH26:
        word &= ~0x3FFFFFF
    elif kind in (PAGE21, GOT_PAGE21):
        word &= ~((0x7FFFF << 5) | (3 << 29))
    else:
        word &= ~(0xFFF << 10)
    section[at : at + 4] = word.to_bytes(4, "little")
    return 0


def meaning(obj: dict) -> dict:
    symbols = obj["symbols"]
    sections = obj["sections"]
    relocs = set()
    for s in sections:
        addend = 0
        for i in range(s["nreloc"]):
            address, info = struct.unpack_from("<iI", obj["data"], s["reloff"] + 8 * i)
            num, pcrel = info & 0xFFFFFF, (info >> 24) & 1
            length, extern, kind = (info >> 25) & 3, (info >> 27) & 1, info >> 28
            if kind == ADDEND:
                addend = num if num < 0x800000 else num - 0x1000000
                continue
            held = clear(s["bytes"], address, kind, length)
            if extern:
                name, ntype, _nsect, _desc, value = symbols[num]
                if ntype & 0xE == 0:
                    target = ("symbol", name, addend + held)
                else:
                    target = ("address", value + addend + held)
            else:
                # Against a section: an UNSIGNED field holds the address itself.
                target = ("address", held + addend)
            relocs.add(
                (s["name"], address, NAMES.get(kind, kind), pcrel, length, target)
            )
            addend = 0
    defined, undefined = set(), set()
    for name, ntype, nsect, desc, value in symbols:
        if name.startswith("L") or name.startswith("ltmp"):
            continue
        if ntype & 0xE == 0:
            undefined.add(name)
        else:
            defined.add((name, ntype, sections[nsect - 1]["name"], value, desc & 0x80))
    return {
        "flags": obj["flags"],
        "minos": obj["minos"],
        "sections": [
            (s["name"], s["flags"], s["addr"], bytes(s["bytes"])) for s in sections
        ],
        "relocs": relocs,
        "defined": defined,
        "undefined": undefined,
    }


def first_difference(a: dict, b: dict) -> str:
    for key in ("flags", "minos"):
        if a[key] != b[key]:
            return f"{key}: clang {a[key]:#x}, kod {b[key]:#x}"
    sa, sb = a["sections"], b["sections"]
    if [s[:3] for s in sa] != [s[:3] for s in sb]:
        return f"sections: clang {[s[:3] for s in sa]}, kod {[s[:3] for s in sb]}"
    for (name, _f, _a, x), (_n, _g, _b, y) in zip(sa, sb):
        if x != y:
            at = next(
                (i for i in range(min(len(x), len(y))) if x[i] != y[i]),
                min(len(x), len(y)),
            )
            return f"{name} differs at {at:#x} (sizes {len(x):#x}, {len(y):#x}): clang {x[at : at + 8].hex()}, kod {y[at : at + 8].hex()}"
    for key in ("relocs", "defined", "undefined"):
        if a[key] != b[key]:
            only_a = sorted(a[key] - b[key], key=str)[:3]
            only_b = sorted(b[key] - a[key], key=str)[:3]
            return f"{key}: only clang {only_a}, only kod {only_b}"
    return ""


def compare(path: str, scratch: Path) -> str | None:
    stem = path.replace("/", "__")
    asm = scratch / f"{stem}.s"
    r = subprocess.run([str(SH_KODC), path], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        return None
    asm.write_bytes(r.stdout)
    clang_o, kod_o = scratch / f"{stem}.clang.o", scratch / f"{stem}.kod.o"
    r = subprocess.run(CLANG_AS + ["-o", str(clang_o), str(asm)], capture_output=True)
    if r.returncode != 0:
        return f"clang: {r.stderr.decode()[:200]}"
    r = subprocess.run(
        [str(SH_KODC), "_assemble", str(asm), str(kod_o)], capture_output=True
    )
    if r.returncode != 0:
        return f"kod: {r.stderr.decode()[:300]}"
    return first_difference(
        meaning(read_object(clang_o.read_bytes())),
        meaning(read_object(kod_o.read_bytes())),
    )


def main() -> int:
    files = (
        sys.argv[1:]
        or subprocess.run(
            ["git", "ls-files", "*.kod"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.split()
    )
    with tempfile.TemporaryDirectory() as tmp, ThreadPoolExecutor() as pool:
        results = list(pool.map(lambda f: (f, compare(f, Path(tmp))), files))
    compared = [(f, d) for f, d in results if d is not None]
    differing = [(f, d) for f, d in compared if d]
    for f, d in differing:
        print(f"differs: {f}\n  {d}")
    print(f"as-diff: {len(compared)} files, {len(differing)} differ")
    return 1 if differing else 0


if __name__ == "__main__":
    sys.exit(main())
