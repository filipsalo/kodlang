"""Programs too deep or too large for the machine's registers and immediates
still compile and give the right answer. The sources are generated, because
what matters is their size, and each answer is worked out here."""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
KOD = ROOT / "build" / "apps" / "kod" / "kod"

pytestmark = pytest.mark.usefixtures("sh_kodc")

HELPERS = """
type P = struct {
    v: int64
}

func id(anon a: int64) -> int64 {
    return a
}

func fails(anon a: int64) -> int64 or Error {
    throw Oops(n: a)
}

func works(anon a: int64) -> int64 or Error {
    return a
}

type Oops = struct {
    n: int64

    func to_str(self) -> str {
        return f"oops {self.n}"
    }
}
"""


def run(tmp_path: Path, body: str, decls: str = "") -> str:
    source = tmp_path / "limits.kod"
    source.write_text(
        f"{HELPERS}{decls}\nfunc main() -> int64 {{\n{body}\n    return 0\n}}\n"
    )
    result = subprocess.run(
        [str(KOD), "run", str(source)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    return result.stdout.strip()


DEPTHS = [4, 8, 16, 17, 18, 30, 100]


@pytest.mark.parametrize("depth", DEPTHS)
def test_nested_match_expressions(tmp_path, depth):
    expr = "1"
    for _ in range(depth):
        expr = f"(1 + match a {{ 1 -> {expr} else -> 0 }})"
    assert run(tmp_path, f"    let a = id(1)\n    print_int({expr})") == str(depth + 1)


@pytest.mark.parametrize("depth", DEPTHS)
def test_nested_and_or(tmp_path, depth):
    ands = "a"
    ors = "b"
    for _ in range(depth):
        ands = f"(a and {ands})"
        ors = f"(b or {ors})"
    false_at_bottom = "b"
    for _ in range(depth):
        false_at_bottom = f"(a and {false_at_bottom})"
    body = f"""    let a = id(1) == 1
    let b = id(1) == 2
    print({ands})
    print({ors})
    print({false_at_bottom})"""
    assert run(tmp_path, body).split() == ["true", "false", "false"]


@pytest.mark.parametrize("depth", DEPTHS)
def test_nested_constructors(tmp_path, depth):
    expr = "P(v: 1)"
    for _ in range(depth):
        expr = f"P(v: {expr}.v + 1)"
    assert run(tmp_path, f"    print_int({expr}.v)") == str(depth + 1)


@pytest.mark.parametrize("depth", DEPTHS)
def test_nested_match_statements(tmp_path, depth):
    lines = [f"    print_int(n + {depth})"]
    for i in range(depth):
        lines = [
            "    match id(n) {",
            "    1 -> {",
            *lines,
            "    }",
            "    else -> print(0)",
            "    }",
        ]
    assert run(tmp_path, "    let n = id(1)\n" + "\n".join(lines)) == str(depth + 1)


@pytest.mark.parametrize("depth", DEPTHS)
def test_values_held_across_nesting_survive(tmp_path, depth):
    # Each level holds a different value in a register while the next is compiled.
    expr = "1"
    want = 1
    for i in range(2, depth + 2):
        expr = f"(id({i}) * 2 + match id({i}) {{ {i} -> {expr} else -> 0 }})"
        want = i * 2 + want
    assert run(tmp_path, f"    print_int({expr})") == str(want)


@pytest.mark.parametrize("depth", [18, 40])
def test_try_leaves_from_deep_inside(tmp_path, depth):
    def nest(inner: str) -> str:
        expr = inner
        for _ in range(depth):
            expr = f"(1 + match a {{ 1 -> {expr} else -> 0 }})"
        return expr

    decls = f"""
func deep(anon a: int64, ok: bool) -> int64 or Error {{
    if ok {{
        return {nest("try works(5)")}
    }}
    return {nest("try fails(7)")}
}}
"""
    body = """    print_int(must deep(1, ok: true))
    let failed = deep(1, ok: false)
    match failed {
        Ok(n) -> print_int(n)
        Err(e) -> print(e.to_str())
    }"""
    assert run(tmp_path, body, decls).split("\n") == [str(depth + 5), "oops 7"]


SKIP_AND_STOP = """{
            if i == 2 {
                continue
            }
            if i == 5 {
                break
            }
            i
        }"""


def nest_matches(inner: str, depth: int) -> str:
    expr = inner
    for _ in range(depth):
        expr = f"(1 + match a {{ 1 -> {expr} else -> 0 }})"
    return expr


@pytest.mark.parametrize("depth", [18, 40])
def test_break_and_continue_from_deep_inside(tmp_path, depth):
    body = f"""    let a = id(1)
    mut total = 0
    for i in 0..9 {{
        total += {nest_matches(f"match a {{ 1 -> {SKIP_AND_STOP} else -> 0 }}", depth)}
    }}
    print_int(total)"""
    # i = 0, 1, 3 and 4 each add depth + i.
    assert run(tmp_path, body) == str(4 * depth + 8)


@pytest.mark.parametrize("depth", [12, 18, 40])
def test_values_held_around_a_loop_survive_its_jumps(tmp_path, depth):
    # The loop runs deep inside held values, and its jumps skip the restores
    # of what was evicted within it.
    loop = f"""{{
        mut total = 0
        for i in 0..9 {{
            total += {nest_matches(f"match a {{ 1 -> {SKIP_AND_STOP} else -> 0 }}", depth)}
        }}
        total
    }}"""
    expr = f"match a {{ 1 -> {loop} else -> 0 }}"
    want = 4 * depth + 8
    for i in range(2, depth + 2):
        expr = f"(id({i}) * 2 + match id({i}) {{ {i} -> {expr} else -> 0 }})"
        want = i * 2 + want
    assert run(tmp_path, f"    let a = id(1)\n    print_int({expr})") == str(want)


def test_jump_out_of_call_arguments_leaks_no_stack(tmp_path):
    decls = """
func add(anon a: int64, anon b: int64) -> int64 {
    return a + b
}
"""
    body = """    let a = id(1)
    mut total = 0
    for i in 0..3000000 {
        total += add(0, match a { 1 -> {
            if i % 2 == 0 {
                continue
            }
            i
        } else -> 0 })
    }
    print_int(total)"""
    assert run(tmp_path, body, decls) == str(sum(range(1, 3000000, 2)))


def test_nested_loops_each_keep_their_own_stack(tmp_path):
    decls = """
func add(anon a: int64, anon b: int64) -> int64 {
    return a + b
}
"""
    body = """    let a = id(1)
    mut total = 0
    for i in 0..4 {
        total += add(100, match a { 1 -> {
            mut sub = 0
            for j in 0..6 {
                sub += add(10, match a { 1 -> {
                    if j == 1 {
                        continue
                    }
                    if j == 4 {
                        break
                    }
                    j
                } else -> 0 })
            }
            if i == 2 {
                continue
            }
            sub
        } else -> 0 })
    }
    print_int(total)"""
    # Per outer pass the inner adds (10 + 0) + (10 + 2) + (10 + 3) = 35; i = 2 is skipped.
    assert run(tmp_path, body, decls) == str(3 * 135)


def test_jumps_out_of_deep_code_leak_no_stack(tmp_path):
    # Three million iterations would overflow an 8 MB stack at 16 bytes each.
    skip = """{
            if i % 2 == 0 {
                continue
            }
            i
        }"""
    body = f"""    let a = id(1)
    mut total = 0
    for i in 0..3000000 {{
        total += {nest_matches(f"match a {{ 1 -> {skip} else -> 0 }}", 18)} - 18
    }}
    print_int(total)"""
    assert run(tmp_path, body) == str(sum(range(1, 3000000, 2)))


@pytest.mark.parametrize("count", [500, 520, 600, 1000, 5000])
def test_large_frames(tmp_path, count):
    lets = "\n".join(f"    let v{i} = id({i})" for i in range(count))
    adds = "\n".join(f"    t += v{i}" for i in range(count))
    body = f"{lets}\n    mut t = 0\n{adds}\n    print_int(t)"
    assert run(tmp_path, body) == str(sum(range(count)))


@pytest.mark.parametrize("count", [4095, 4096, 4097, 5000, 40000])
def test_large_array_literals(tmp_path, count):
    items = ", ".join(str(i) for i in range(count))
    body = f"    let xs: [int64] = [{items}]\n    print_int(xs[{count - 1}] + xs[0] + len(xs))"
    assert run(tmp_path, body) == str(count - 1 + count)


@pytest.mark.parametrize("count", [4095, 4096, 5000])
def test_large_structs_and_payloads(tmp_path, count):
    fields = "\n".join(f"    f{i}: int64" for i in range(count))
    args = ", ".join(f"f{i}: {i}" for i in range(count))
    params = ", ".join(f"f{i}: int64" for i in range(count))
    binds = ", ".join(f"b{i}" for i in range(count))
    decls = f"type S = struct {{\n{fields}\n}}\ntype E = enum {{\n    V({params})\n}}\n"
    body = f"""    let s = S({args})
    print_int(s.f{count - 1})
    let e: E = .V({args})
    match e {{
        .V({binds}) -> print_int(b{count - 1} + b0)
    }}"""
    assert run(tmp_path, body, decls).split() == [str(count - 1), str(count - 1)]


def test_deep_expression_in_a_large_frame(tmp_path):
    lets = "\n".join(f"    let v{i} = id({i})" for i in range(1000))
    expr = "v999"
    for i in range(30):
        expr = f"(v{i} + match a {{ 1 -> {expr} else -> 0 }})"
    body = f"    let a = id(1)\n{lets}\n    print_int({expr})"
    assert run(tmp_path, body) == str(999 + sum(range(30)))
