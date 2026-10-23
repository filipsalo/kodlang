"""Compare sh_kodc output between a base revision and the working tree.

Usage: uv run python tools/asm_diff.py [BASE]   (default: HEAD; or `make asm-diff`)

Builds sh_kodc at BASE (cached as build/asm-diff/<sha>/sh_kodc), then
compiles every .kod file in the working tree with both that compiler and
build/stage1/sh_kodc. Both run from the repo root, so both read the
working tree's stdlib and only compiler changes show up. Reports each file
whose assembly, diagnostics or exit status differ and writes both outputs
under build/asm-diff/out/. Exits 1 if anything differs.
"""

import shutil
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "build" / "asm-diff"


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout


def build_base_compiler(rev: str) -> Path:
    try:
        sha = git("rev-parse", "--verify", "--quiet", f"{rev}^{{commit}}").strip()
    except subprocess.CalledProcessError:
        sys.exit(f"asm-diff: unknown revision `{rev}`")
    cached = OUT / sha / "sh_kodc"
    if cached.exists():
        return cached
    src = OUT / sha / "src"
    shutil.rmtree(src, ignore_errors=True)
    src.mkdir(parents=True)
    print(f"asm-diff: building sh_kodc at {rev} ({sha[:10]})", file=sys.stderr)
    archive = subprocess.run(
        ["git", "archive", sha], cwd=ROOT, check=True, capture_output=True
    ).stdout
    subprocess.run(["tar", "-x", "-C", str(src)], input=archive, check=True)
    if not (src / "bootstrap" / "sh_kodc").exists():
        print(
            f"asm-diff: {rev} has no bootstrap snapshot; building it through the"
            " Python interpreter (minutes)",
            file=sys.stderr,
        )
    subprocess.run(["make", "-s", "stage1"], cwd=src, check=True, stdout=sys.stderr)
    shutil.copy2(src / "build" / "stage1" / "sh_kodc", cached)
    shutil.rmtree(src)
    return cached


def corpus() -> list[str]:
    files = git(
        "ls-files", "--cached", "--others", "--exclude-standard", "--", "*.kod"
    ).splitlines()
    # Dot-paths are worktrees under .claude/ and the transient test aggregator.
    return sorted(
        f for f in set(files) if not f.startswith(".") and (ROOT / f).is_file()
    )


def compile_with(compiler: Path, path: str) -> str:
    try:
        r = subprocess.run(
            [str(compiler), path],
            cwd=ROOT,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        return "--- timed out ---\n"
    return f"{r.stdout}--- stderr ---\n{r.stderr}--- exit {r.returncode} ---\n"


def main() -> int:
    base_rev = sys.argv[1] if len(sys.argv) > 1 else "HEAD"
    base = build_base_compiler(base_rev)
    subprocess.run(["make", "-s", "stage1"], cwd=ROOT, check=True, stdout=sys.stderr)
    new = ROOT / "build" / "stage1" / "sh_kodc"
    files = corpus()
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(
            pool.map(lambda f: (f, compile_with(base, f), compile_with(new, f)), files)
        )

    out = OUT / "out"
    shutil.rmtree(out, ignore_errors=True)
    differing = []
    for f, base_out, new_out in results:
        if base_out == new_out:
            continue
        differing.append(f)
        stem = f.replace("/", "__")
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{stem}.base").write_text(base_out)
        (out / f"{stem}.new").write_text(new_out)
        print(f"differs: {f}")

    print(f"asm-diff: {len(files)} files, {len(differing)} differ from {base_rev}")
    if differing:
        stem = differing[0].replace("/", "__")
        rel = out.relative_to(ROOT)
        print(f"  e.g. diff {rel}/{stem}.base {rel}/{stem}.new")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
