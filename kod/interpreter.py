#!/usr/bin/env python
"""Simple interpreter for the Kod language"""

import ctypes
import dataclasses
import os
import re
import sys
from typing import Any

from kod import ast, tokens
from kod import values as types
from kod.exceptions import KodError, get_source
from kod.program import Program
from kod.span import Span

libc = ctypes.cdll.LoadLibrary("libSystem.dylib")

# Whether reassigning an immutable (`let`) binding is an error. Mirrors
# codegen.kod's enforce_immutability so both frontends agree.
_ENFORCE_IMMUTABILITY = True


class BreakSignal(Exception):
    """Break out of a loop"""


class ContinueSignal(Exception):
    """Continue to next loop iteration"""


class ReturnValue(Exception):
    """Return from a function"""

    def __init__(self, value):
        self.value = value


class ThrownError(Exception):
    """A Kod `throw` — propagates up through function calls until caught by
    a `must` (panic) or a `try` (re-raise + return from the enclosing fn).
    Equivalent to the compiled .Err arm of a Result return."""

    def __init__(self, value):
        self.value = value


@dataclasses.dataclass
class BoundMethod:
    """A method bound to a receiver instance."""

    func: ast.FunctionDeclaration
    receiver: Any


def _downcast_pattern(pattern, value):
    """`alias.T(b)` over a struct, as an interface holds one, is the downcast to `T`."""
    if not hasattr(type(value), "struct_fields"):
        return pattern
    qualifier = pattern.__dict__.get("_kod_qualifier")
    if qualifier is not None:
        error = _downcast_error(pattern.enum_name, pattern.variant_name, qualifier)
        raise KodError(error or _many_bindings(pattern), pattern.span)
    if len(pattern.bindings) > 1:
        return pattern
    binding = pattern.bindings[0] if pattern.bindings else ""
    return ast.TypePattern(pattern.variant_name, binding, pattern.span)


def _downcast_error(qualifier, type_name, kind):
    """Why `qualifier.T(...)` over an interface isn't a downcast; "" if it is one."""
    shown = f"`{qualifier}.{type_name}`"
    if kind == "local":
        return (
            f"`{qualifier}` is a local here, so {shown} doesn't name a type of"
            " its module; give the local another name"
        )
    if kind == "other":
        return f"{shown} needs an enum value"
    return ""


def _many_bindings(pattern):
    n = len(pattern.bindings)
    if n <= 1:
        return ""
    return (
        f"a downcast to `{pattern.enum_name}.{pattern.variant_name}` binds one"
        f" name, got {n}; bind the value and read its fields"
    )


def _note_qualifier(pattern, bound, scope):
    """Whether `X` in a pattern `X.T(...)` names an import there, for a downcast."""
    if type(pattern) is not ast.EnumVariantPattern:
        return
    name = pattern.enum_name
    if name in ("Option", "Result"):
        return
    kind = "other"
    if name in scope.aliases:
        kind = "local" if name in bound else ""
    if kind or len(pattern.bindings) > 1:
        pattern.__dict__["_kod_qualifier"] = kind


def _value_pattern(pattern, value):
    """`pattern` with `.Some`/`.None` and `.Ok`/`.Err` read for `value`'s kind."""
    if isinstance(pattern, ast.EnumVariantPattern):
        if pattern.enum_name not in ("Option", "Result"):
            return _downcast_pattern(pattern, value)
    elif not isinstance(pattern, ast.ImplicitEnumVariantPattern):
        return pattern
    if isinstance(value, types.EnumValue) and (
        pattern.variant_name in value.enum_type.variants
    ):
        return pattern
    if isinstance(value, types.ResultValue) and len(pattern.bindings) <= 1:
        binding = pattern.bindings[0] if pattern.bindings else ""
        if pattern.variant_name == "Ok":
            return ast.ResultOkPattern(binding, pattern.span)
        if pattern.variant_name == "Err":
            return ast.ResultErrPattern(binding, pattern.span)
    if pattern.variant_name == "None" and not pattern.bindings:
        return ast.OptionalNonePattern(pattern.span)
    if pattern.variant_name == "Some" and len(pattern.bindings) <= 1:
        binding = pattern.bindings[0] if pattern.bindings else ""
        return ast.OptionalSomePattern(binding, pattern.span)
    return pattern


def _param_type(expr, subst):
    """The type a return type naming a type parameter has in an instance; else None."""
    if ast.is_result_type_expr(expr):
        return _param_type(expr.args[0], subst)
    if isinstance(expr, ast.OptionalTypeExpr):
        return _param_type(expr.inner, subst)
    if isinstance(expr, ast.ArrayTypeExpr):
        inner = _param_type(expr.element, subst)
        return types.ArrayType.make(inner) if inner is not None else None
    if isinstance(expr, ast.NamedTypeExpr):
        return subst.get(expr.name)
    return None


def _slot_target(expr):
    """`expr` unwrapped if its `.Variant`s take their enum from its slot."""
    while True:
        t = type(expr)
        if t is ast.Expression:
            expr = expr.value
        elif t is ast.FunctionCallParam:
            expr = expr.expression
        else:
            break
    if (
        t is ast.ImplicitEnumVariant
        or t is ast.ArrayLiteral
        or t is ast.MatchExpression
    ):
        return expr
    if t is ast.FunctionCall and type(expr.callee) is ast.ImplicitEnumVariant:
        return expr
    if t is ast.BinaryOperator and type(expr.op) is tokens.Plus:
        if _wants_slot(expr.lhs) or _wants_slot(expr.rhs):
            return expr
    return None


def _unlabelled_field(shown, fields, args, i):
    """`Point(10, 20)`: offer the value the next field that no label names."""
    args = list(args)
    labels = {a.label.id for a in args if getattr(a, "label", None) is not None}
    free = [name for name in fields if name not in labels]
    nth = sum(1 for a in args[:i] if getattr(a, "label", None) is None)
    hint = f" (`{free[nth]}:`)" if nth < len(free) else ""
    return f"argument {i + 1} of `{shown}` needs a field label{hint}"


def _chain_anchor(expr):
    """The first operand of a `+` chain that isn't a literal or `match`; else None."""
    if type(expr) is ast.BinaryOperator and type(expr.op) is tokens.Plus:
        # Kept on the node: each `+` of a chain with no anchor asks this of its lhs.
        anchor = expr.__dict__.get("_kod_anchor", False)
        if anchor is False:
            anchor = _chain_anchor(expr.lhs)
            if anchor is None:
                anchor = _chain_anchor(expr.rhs)
            expr.__dict__["_kod_anchor"] = anchor
        return anchor
    target = _slot_target(expr)
    if type(target) is ast.ArrayLiteral or type(target) is ast.MatchExpression:
        return None
    return expr


def _wants_slot(expr):
    """Whether `expr` holds a `.Variant` that takes its enum from a slot."""
    if type(expr) is ast.BinaryOperator:
        # Kept on the node: each `+` of a chain asks this of its whole lhs.
        wants = expr.__dict__.get("_kod_wants_slot")
        if wants is None:
            wants = _slot_target(expr) is not None
            expr.__dict__["_kod_wants_slot"] = wants
        return wants
    target = _slot_target(expr)
    if type(target) is ast.ArrayLiteral:
        return any(_wants_slot(e) for e in target.elements)
    return target is not None


class _OkSlot:
    """The `T` of a `T or Error` return, where `.Ok` and `.Err` can be the result's."""

    def __init__(self, inner):
        self.inner = inner


def _enums_with(names, variant_name):
    found = []
    for val in names.values():
        if isinstance(val, types.GenericTemplate):
            val = val.template
        if (
            isinstance(val, type)
            and hasattr(val, "variants")
            and variant_name in val.variants
        ):
            found.append(val)
    return found


def _fits_result(name, args):
    if name not in ("Ok", "Err") or len(args) != 1:
        return False
    label = args[0].label if isinstance(args[0], ast.FunctionCallParam) else None
    return label is None or label.id == ("value" if name == "Ok" else "error")


def _own_variant(inner, name, arg, payload):
    """T's one-field `name` holding `payload`, if the result's variant can't take it."""
    if not (isinstance(inner, type) and issubclass(inner, types.EnumType)):
        return None
    info = inner.variants.get(name)
    if info is None or len(info.fields) != 1:
        return None
    label = arg.label if isinstance(arg, ast.FunctionCallParam) else None
    if label is not None and label.id != info.fields[0].id:
        return None
    if name == "Ok":
        fits = isinstance(payload, types.EnumValue) and payload.enum_type is inner
    else:
        fits = isinstance(
            payload, (types.Int64, types.Bool, types.String, types.StructType)
        )
    if fits:
        return None
    return types.EnumValue(inner, name, {info.fields[0].id: payload})


def _is_variant(expr):
    t = type(expr)
    if t is ast.FunctionCall:
        return type(expr.callee) is ast.ImplicitEnumVariant
    return t is ast.ImplicitEnumVariant


def _takes_side(expr):
    """Whether `expr` takes its enum from the other side of `==`."""
    return _is_variant(expr) or type(expr) is ast.MatchExpression


def _implicit_variant(expr):
    if isinstance(expr, ast.ImplicitEnumVariant):
        return expr.variant_name, []
    if isinstance(expr, ast.FunctionCall) and isinstance(
        expr.callee, ast.ImplicitEnumVariant
    ):
        return expr.callee.variant_name, list(expr.args)
    return "", []


def _substituted(t, subst):
    try:
        return types._substitute_type(t, subst)
    except KeyError:
        return t


_FUNC_DECLS = (ast.FunctionDeclaration, ast.ExternalFunctionDeclaration)


def _pattern_names(pattern):
    names = getattr(pattern, "bindings", None)
    if names is None:
        names = [getattr(pattern, "binding", "")]
    return [name for name in names if name]


def _type_name(value):
    """How Kod writes the type of a primitive, struct or enum value."""
    if isinstance(value, types.StructType):
        return type(value).__name__
    if isinstance(value, types.EnumValue):
        return value.enum_type.name
    return getattr(type(value), "name", type(value).__name__)


def _children(node):
    for field in dataclasses.fields(node):
        value = getattr(node, field.name)
        if isinstance(value, ast.ASTNode):
            yield value
        elif isinstance(value, (list, tuple)):
            for item in value:
                if isinstance(item, ast.ASTNode):
                    yield item


class _Scope:
    """What the static pass knows of a function besides the names bound so far."""

    def __init__(self, func, program, module):
        self.program = program
        self.module = getattr(func, "module", None) or module
        params = {p.variable.id for p in func.params}
        self.seen = set(params)
        self.declared = set(params)
        # Names a `let` or a parameter without `mut` binds, which the frame
        # holds as immutable until another binding of the name thaws them.
        self.fixed = {p.variable.id for p in func.params if not p.mutable}
        for stmt in func.body:
            _local_names(stmt, self.declared, self.fixed)
        imports = self.module.get_imports() if self.module is not None else ()
        self.aliases = {imp.local_name for imp in imports}

    def named(self, name):
        """What the module, an item it imports or a builtin calls `name`."""
        module = self.module
        value = module.names.get(name) if module is not None else None
        if value is None and module is not None:
            for imp in module.get_imports():
                if name in imp.items:
                    path = module.resolve_import(imp.module_name)
                    value = self.program.get_module(path).names.get(name)
                    break
        if value is None:
            value = self.program.builtins.names.get(name)
        return value

    def fallback(self, name, call=False):
        """What `name` means where no local of it is bound, if anything."""
        if call and name in ("str", "hash"):
            return name
        value = self.named(name)
        if call or isinstance(value, _FUNC_DECLS):
            return value
        return None

    def enum_named(self, name):
        """The enum `name` means before a `.`, where a local has the name too."""
        if name not in self.declared:
            return None
        value = self.named(name)
        if isinstance(value, type) and issubclass(value, types.EnumType):
            return value
        return None

    def unbound(self, name, verb):
        if name in self.seen:
            use = "call" if verb == "called" else "use"
            return (
                f"`{name}` is declared in a block that has ended; declare it"
                f" outside the block to {use} it here"
            )
        return f"`{name}` is {verb} before its `let`"


def _local_names(node, names, fixed):
    """Every name a binding in `node` declares, outside function literals;
    those an immutable `let` declares go to `fixed` too."""
    t = type(node)
    if t is ast.FunctionDeclaration:
        return
    if t is ast.VariableDeclaration:
        names.add(node.variable.id)
        if not node.mutable:
            fixed.add(node.variable.id)
    elif t is ast.LetElseStatement:
        names.update(_pattern_names(node.pattern))
    elif t is ast.ForEachStatement:
        names.add(node.binding)
    elif t is ast.MatchStatement or t is ast.MatchExpression:
        for arm in node.arms:
            names.update(_pattern_names(arm.pattern))
            for child in arm.body if isinstance(arm.body, list) else [arm.body]:
                _local_names(child, names, fixed)
    for child in _children(node):
        _local_names(child, names, fixed)


def _mark_scopes(func, program, module=None):
    """Note at each name whether a local of it is bound there, and check its use."""
    func.__dict__["_kod_scoped"] = True
    scope = _Scope(func, program, module)
    params = {p.variable.id: (1, p.span) for p in func.params}
    _scope_block(func.body, params, 1, scope)


def _mark_program_scopes(program):
    for module in program:
        for stmt in module.body:
            funcs = []
            if isinstance(stmt, ast.FunctionDeclaration):
                funcs = [stmt]
            elif isinstance(stmt, ast.TypeDeclaration):
                owner = getattr(stmt.type, "template", stmt.type)
                funcs = getattr(owner, "methods", {}).values()
            for func in funcs:
                if "_kod_scoped" not in func.__dict__:
                    _mark_scopes(func, program, module)


def _line_of(span):
    return get_source(span.filename)[: span.start].count("\n") + 1


def _name_span(span, name, end=None):
    """The last whole-word `name` in `span` before `end` and any `->`."""
    text = get_source(span.filename)[span.start : end or span.end].split("->")[0]
    for m in reversed(list(re.finditer(rf"\b{re.escape(name)}\b", text))):
        start = span.start + m.start()
        return Span(span.filename, start, start + len(name))
    return span


def _bind(bound, name, span, depth, scope):
    # Until blocks get scopes, a nested binding would share the outer one's slot.
    outer = bound.get(name)
    if outer is not None and outer[0] < depth:
        raise KodError(
            f"`{name}` is already a local here (line {_line_of(outer[1])}); blocks"
            " don't have their own scopes yet, so give this one another name",
            span,
        )
    bound[name] = (depth, span)
    scope.seen.add(name)


def _bind_pattern(bound, pattern, depth, scope, end=None):
    for name in _pattern_names(pattern):
        _bind(bound, name, _name_span(pattern.span, name, end), depth, scope)


def _scope_use(node, bound, scope, verb, fallback=True):
    """A local's name used where no binding of it is: its fallback, or an error."""
    name = node.id
    if name in bound or name not in scope.declared:
        return
    target = scope.fallback(name, call=verb == "called") if fallback else None
    if target is None:
        raise KodError(scope.unbound(name, verb), node.span)
    if verb == "read":
        node.__dict__["_kod_func"] = target


def _note_thaw(stmt, names, scope):
    """Mark `stmt` if a name it binds may be one a `let` left immutable."""
    if any(name in scope.fixed for name in names):
        stmt.__dict__["_kod_thaw"] = True


def _scope_block(stmts, bound, depth, scope):
    bound = dict(bound)
    for stmt in stmts:
        _scope_stmt(stmt, bound, depth, scope)


def _scope_stmt(stmt, bound, depth, scope):
    t = type(stmt)
    inner = depth + 1
    if t is ast.VariableDeclaration:
        _scope_expr(stmt.value, bound, depth, scope)
        _bind(bound, stmt.variable.id, stmt.variable.span, depth, scope)
    elif t is ast.LetElseStatement:
        _scope_expr(stmt.value, bound, depth, scope)
        _scope_block(stmt.else_body, bound, inner, scope)
        _note_qualifier(stmt.pattern, bound, scope)
        _note_thaw(stmt, _pattern_names(stmt.pattern), scope)
        _bind_pattern(bound, stmt.pattern, depth, scope, stmt.value.span.start)
    elif t is ast.IfStatement:
        _scope_expr(stmt.condition, bound, depth, scope)
        _scope_block(stmt.true_branch, bound, inner, scope)
        _scope_block(stmt.false_branch, bound, inner, scope)
    elif t is ast.ForStatement:
        _scope_expr(stmt.condition, bound, depth, scope)
        _scope_block(stmt.body, bound, inner, scope)
    elif t is ast.ForEachStatement:
        _scope_expr(stmt.iterable, bound, depth, scope)
        body = dict(bound)
        _note_thaw(stmt, [stmt.binding], scope)
        name_span = _name_span(stmt.span, stmt.binding, stmt.iterable.span.start)
        _bind(body, stmt.binding, name_span, inner, scope)
        _scope_block(stmt.body, body, inner, scope)
    elif t is ast.MatchStatement:
        _scope_expr(stmt.expression, bound, depth, scope)
        _note_thaw(
            stmt, [n for arm in stmt.arms for n in _pattern_names(arm.pattern)], scope
        )
        for arm in stmt.arms:
            body = dict(bound)
            _note_qualifier(arm.pattern, bound, scope)
            _bind_pattern(body, arm.pattern, inner, scope)
            _scope_block(arm.body, body, inner, scope)
    elif t is ast.Assignment and type(stmt.lhs) is ast.Name:
        _scope_use(stmt.lhs, bound, scope, "assigned", fallback=False)
        _scope_expr(stmt.rhs, bound, depth, scope)
    elif isinstance(stmt, ast.ASTNode):
        _scope_expr(stmt, bound, depth, scope)


def _scope_expr(node, bound, depth, scope):
    t = type(node)
    if t is ast.Name:
        _scope_use(node, bound, scope, "read")
        return
    if t is ast.FunctionDeclaration:
        if "_kod_scoped" not in node.__dict__:
            _mark_scopes(node, scope.program, scope.module)
        return
    if t is ast.FunctionCallParam:
        _scope_expr(node.expression, bound, depth, scope)
        return
    if t is ast.GenericInstantiation:
        return
    if t is ast.FunctionCall and type(node.callee) is ast.Name:
        node.callee.__dict__["_kod_bound"] = node.callee.id in bound
        _scope_use(node.callee, bound, scope, "called")
        _scope_expr(node.args, bound, depth, scope)
        return
    if t is ast.BinaryOperator and isinstance(node.op, tokens.Dot):
        if type(node.lhs) is ast.Name:
            enum = scope.enum_named(node.lhs.id)
            if enum is not None:
                # As in the compiler, the enum wins over a local of its name.
                node.lhs = enum
                return
            node.lhs.__dict__["_kod_bound"] = node.lhs.id in bound
            if node.lhs.id not in scope.aliases:
                _scope_use(node.lhs, bound, scope, "read", fallback=False)
        elif type(node.lhs) is not type:  # an enum already, in a `+=` target seen twice
            _scope_expr(node.lhs, bound, depth, scope)
        return
    if t is ast.MatchExpression:
        _scope_expr(node.expression, bound, depth, scope)
        for arm in node.arms:
            body = dict(bound)
            _note_qualifier(arm.pattern, bound, scope)
            _bind_pattern(body, arm.pattern, depth + 1, scope)
            _scope_expr(arm.body, body, depth + 1, scope)
        return
    for child in _children(node):
        _scope_expr(child, bound, depth, scope)


def _value_arm(arm, value):
    """`arm` with its pattern read for `value`, as in _value_pattern."""
    pattern = _value_pattern(arm.pattern, value)
    if pattern is arm.pattern:
        return arm
    return dataclasses.replace(arm, pattern=pattern)


class Interpreter:
    """Simple interpreter for the Kod language"""

    def __init__(self, program: Program):
        self.program = program
        self.stack = [{}]
        # Parallel to self.stack: the set of immutable (`let`, not `mut`)
        # binding names in each frame. Mirrors the codegen's per-VarSlot
        # mutable flag so `_interpret` rejects the same reassignments.
        self.immutable_stack = [set()]
        # The running functions, innermost last; a `return` goes to the last.
        self.funcs = []

    def run(self, file, argv=()):
        """Run the program"""
        for module in self.program:
            for statement in module.body:
                self.execute_statement(module, statement)
        entry_module = self.program.get_module(file.canonical_path.with_suffix(""))
        _mark_program_scopes(self.program)
        main = self.lookup(entry_module, "main")
        if len(main.params) > 0:
            string_array = types.ArrayType.make(types.String)
            argv = string_array([types.String(arg.encode("utf8")) for arg in argv])
            args = [argv]
        else:
            args = []
        try:
            exit_code = self.call_function(entry_module, main, args)
        except ThrownError as e:
            msg = self._coerce_to_str(entry_module, e.value)
            sys.stderr.write(f"panic: {msg.value.decode('utf8')}\n")
            sys.exit(1)
        # A fallible `main` returns a ResultValue: an unhandled Err panics.
        if isinstance(exit_code, types.ResultValue):
            if not exit_code.ok:
                msg = self._coerce_to_str(entry_module, exit_code.payload)
                sys.stderr.write(f"panic: {msg.value.decode('utf8')}\n")
                sys.exit(1)
            exit_code = exit_code.payload
        sys.exit(exit_code.value if exit_code else 0)

    def _is_rhs_name(self, rhs):
        """The name an `is` right-hand side calls or names: "Ok" for `is .Ok(v)`."""
        callee = rhs.callee if isinstance(rhs, ast.FunctionCall) else rhs
        if isinstance(callee, (ast.Variable, ast.Name)):
            return callee.id
        if isinstance(callee, ast.ImplicitEnumVariant):
            return callee.variant_name
        if (
            isinstance(callee, ast.BinaryOperator)
            and isinstance(callee.op, tokens.Dot)
            and isinstance(callee.lhs, (ast.Variable, ast.Name))
            and callee.lhs.id in ("Option", "Result")
            and isinstance(callee.rhs, (ast.Variable, ast.Name))
        ):
            return callee.rhs.id
        return ""

    def _qualified_type_name(self, module, rhs):
        """`T` for an `is` right-hand side `alias.T` or `alias.T(b)`; else ""."""
        callee = rhs.callee if isinstance(rhs, ast.FunctionCall) else rhs
        if (
            isinstance(callee, ast.BinaryOperator)
            and isinstance(callee.op, tokens.Dot)
            and isinstance(callee.lhs, (ast.Variable, ast.Name))
            and isinstance(callee.rhs, (ast.Variable, ast.Name))
            and self._alias_import(module, callee.lhs.id) is not None
        ):
            if callee.lhs.__dict__.get("_kod_bound"):
                error = _downcast_error(callee.lhs.id, callee.rhs.id, "local")
                raise KodError(error, rhs.span)
            return callee.rhs.id
        return ""

    def _returns_result(self, func):
        """ast.returns_result, cached on the declaration: call_function is hot."""
        fallible = func.__dict__.get("_returns_result")
        if fallible is None:
            fallible = ast.returns_result(func, func.module, self.program)
            func.__dict__["_returns_result"] = fallible
        return fallible

    def _is_rhs_variant(self, rhs):
        """The variant an `is` right-hand side names: "Red" for `Color.Red`."""
        callee = rhs.callee if isinstance(rhs, ast.FunctionCall) else rhs
        if isinstance(callee, ast.ImplicitEnumVariant):
            return callee.variant_name
        if (
            isinstance(callee, ast.BinaryOperator)
            and isinstance(callee.op, tokens.Dot)
            and isinstance(callee.rhs, (ast.Variable, ast.Name))
        ):
            return callee.rhs.id
        return ""

    def _is_result_enum(self, enum_type):
        """True for the stdlib Result enum, whose values are ResultValues."""
        name = getattr(enum_type, "name", "")
        return name == "Result" or name.startswith("Result[")

    def _is_result_value(self, v):
        """True if `v` is already a fallible-result carrier — the legacy
        ResultValue dataclass OR an EnumValue of stdlib Result[T, E]
        (template or any monomorphisation). Used by call_function to
        avoid double-wrapping `.Ok(...)` / `.Err(...)` returns."""
        if isinstance(v, types.ResultValue):
            return True
        if isinstance(v, types.EnumValue):
            name = getattr(v.enum_type, "name", "")
            if name == "Result" or name.startswith("Result["):
                return True
        return False

    def assign(self, module, name, value):
        """Assign a value to a variable"""
        match name:
            case ast.Variable() | ast.Name():
                name = name.id
        for frame in self.stack[-1], module.names:
            if name in frame:
                frame[name] = value
                return
        raise ValueError(f"Unknown name {name!r}")

    def _resolve_import(self, module, imp):
        """Memoise the resolved module on the Import node so subsequent
        references skip the Path construction + dict-hash pathlib walk.
        Stage1 codegen.kod otherwise resolves ~900k imports."""
        cached = getattr(imp, "_resolved_module", None)
        if cached is None:
            path = module.resolve_import(imp.module_name)
            cached = self.program.get_module(path)
            imp._resolved_module = cached
        return cached

    def _local_func(self, callee):
        """The function value a local in scope at this call holds, or None."""
        bound = callee.__dict__.get("_kod_bound")
        if bound is None:
            bound = callee.id in self.stack[-1]
        if not bound:
            return None
        value = self.stack[-1].get(callee.id)
        return value if isinstance(value, (*_FUNC_DECLS, BoundMethod)) else None

    def _aliases(self, module):
        """Each import by its alias, though a function may share the name."""
        aliases = module.__dict__.get("_kod_aliases")
        if aliases is None:
            aliases = {imp.local_name: imp for imp in module.get_imports()}
            module.__dict__["_kod_aliases"] = aliases
        return aliases

    def _alias_import(self, module, name):
        return self._aliases(module).get(name)

    def _item(self, module, name):
        items = module.__dict__.get("_kod_items")
        if items is None:
            items = {}
            for imp in module.get_imports():
                for item in imp.items:
                    items.setdefault(item, imp)
            module.__dict__["_kod_items"] = items
        imp = items.get(name)
        if imp is None:
            return None
        return self._resolve_import(module, imp).names.get(name)

    def _own_func(self, module, name):
        value = module.names.get(name)
        if isinstance(value, _FUNC_DECLS):
            return value
        value = self._item(module, name)
        return value if isinstance(value, _FUNC_DECLS) else None

    def _module_func(self, module, name):
        value = self._own_func(module, name)
        if value is not None:
            return value
        value = self.program.builtins.names.get(name)
        return value if isinstance(value, _FUNC_DECLS) else None

    def _is_builtin_call(self, module, callee):
        if self._local_func(callee) is not None:
            return False
        if module is self.program.builtins:
            return True
        return self._own_func(module, callee.id) is None

    def _named(self, module, name):
        """What `name` means in the module, past its locals: its own, an item or a builtin."""
        value = module.names.get(name)
        if value is None:
            value = self._item(module, name)
        if value is None:
            value = self.program.builtins.names.get(name)
        return value

    def _struct_named(self, module, name):
        """The struct `name` means in the module: its own, an item or a builtin."""
        value = self._named(module, name)
        if isinstance(value, type) and issubclass(value, types.StructType):
            return value
        return None

    def _call_target(self, module, callee):
        """What `callee(...)` calls, in the compiler's order: a struct of the
        name, a function value the local holds, then a function of the name."""
        if type(callee) is ast.Name and "_kod_bound" in callee.__dict__:
            target = callee.__dict__.get("_kod_struct", False)
            if target is False:
                target = self._struct_named(module, callee.id)
                callee.__dict__["_kod_struct"] = target
            if target is None:
                target = self._local_func(callee)
            if target is None:
                target = self._module_func(module, callee.id)
            if target is not None:
                return target
            if callee.__dict__["_kod_bound"]:
                value = self.stack[-1].get(callee.id)
                raise KodError(
                    f"`{callee.id}` is a local of type `{_type_name(value)}`,"
                    " not a function",
                    callee.span,
                )
            # Left in the frame by a block that has ended, or by a later `let`.
            stale = self.stack[-1].get(callee.id)
            if not callee.__dict__["_kod_bound"] and isinstance(
                stale, (*_FUNC_DECLS, BoundMethod)
            ):
                raise ValueError(f"Unknown name {callee.id!r}")
        return self.evaluate_expression(module, callee)

    def lookup(self, module, name) -> Any:
        """Look up a variable in the stack"""
        match name:
            case ast.Variable() | ast.Name():
                name = name.id
        for frame in self.stack[-1], module.names:
            if name in frame:
                value = frame[name]
                if isinstance(value, ast.StringLiteral):
                    value = value.value
                elif isinstance(value, ast.Import):
                    return self._resolve_import(module, value)
                return value
        item = self._item(module, name)
        if item is not None:
            return item
        if name in self.program.builtins.names:
            return self.program.builtins.names[name]
        raise ValueError(f"Unknown name {name!r}")

    def evaluate_binary_operator(
        self, module, op, lhs, rhs, as_lvalue=False, slot=None, append=False
    ):
        """Evaluate a binary operator; an array `+` chain is built as `slot`.

        `append` is `+=`'s `+`: an array on the left grows in place.
        """
        match op:
            case tokens.Dot():
                imp = None
                if type(lhs) is ast.Name:
                    bound = lhs.__dict__.get("_kod_bound")
                    if bound is None:
                        bound = lhs.id in self.stack[-1]
                    if not bound:
                        imp = self._alias_import(module, lhs.id)
                if isinstance(imp, ast.Import):
                    lhs = self._resolve_import(module, imp)
                else:
                    lhs = self.evaluate_expression(module, lhs, as_lvalue)
                if isinstance(lhs, ast.Module):
                    return lhs.names[rhs.id]
                methods = getattr(type(lhs), "methods", {})
                if rhs.id in methods:
                    return BoundMethod(methods[rhs.id], lhs)
                return getattr(lhs, rhs.id)
            case tokens.OpenBracket():
                lhs_val = self.evaluate_expression(module, lhs)
                struct_methods = getattr(type(lhs_val), "methods", {})
                if "op_index" in struct_methods:
                    bound = BoundMethod(struct_methods["op_index"], lhs_val)
                    key = self._evaluate_args(module, [rhs], bound)
                    return self.call_function(module, bound, key)
                rhs_val = self.evaluate_expression(module, rhs)
                try:
                    return lhs_val.op_index(rhs_val)
                except (IndexError, KeyError) as e:
                    sp = lhs.span
                    src = sp.filename.read_text() if sp.filename.exists() else ""
                    line_no = src[: sp.start].count("\n") + 1
                    raise IndexError(f"{e} at {sp.filename}:{line_no}") from None
            case tokens.Plus():
                op_func_name = "op_plus"
            case tokens.Minus():
                op_func_name = "op_minus"
            case tokens.NotEqual():
                if _takes_side(lhs) or _takes_side(rhs):
                    lhs_val, rhs_val = self._variant_operands(module, lhs, rhs)
                    return lhs_val.op_ne(rhs_val)
                op_func_name = "op_ne"
            case tokens.LessThan():
                op_func_name = "op_lt"
            case tokens.LessEqual():
                op_func_name = "op_le"
            case tokens.GreaterThan():
                op_func_name = "op_gt"
            case tokens.GreaterEqual():
                op_func_name = "op_ge"
            case tokens.Is() | tokens.IsNot():
                negate = isinstance(op, tokens.IsNot)
                lhs_val = self.evaluate_expression(module, lhs)
                if isinstance(lhs_val, types.ResultValue):
                    matches = (self._is_rhs_name(rhs) == "Ok") == bool(lhs_val.ok)
                    return types.Bool(matches != negate)
                variant = self._is_rhs_variant(rhs)
                if (
                    isinstance(lhs_val, types.EnumValue)
                    and variant in lhs_val.enum_type.variants
                ):
                    return types.Bool((lhs_val.variant_name == variant) != negate)
                # Interface downcast: `value is StructType` — a type name that
                # isn't the optional `Some`/`none` marker. Interface values are
                # the raw struct instance, so this is a class-name check.
                name = self._is_rhs_name(rhs) or self._qualified_type_name(module, rhs)
                if name not in ("", "Some", "None", "Ok", "Err") and not isinstance(
                    rhs, ast.NoneLiteral
                ):
                    if isinstance(lhs_val, types.NoneType):
                        return types.Bool(negate)
                    matches = type(lhs_val).__name__ == name
                    return types.Bool(matches != negate)
                is_none = isinstance(lhs_val, types.NoneType)
                if isinstance(rhs, ast.NoneLiteral) or name == "None":
                    return types.Bool(is_none != negate)
                else:
                    return types.Bool((not is_none) != negate)
            case tokens.EqualEqual():
                if _takes_side(lhs) or _takes_side(rhs):
                    lhs_val, rhs_val = self._variant_operands(module, lhs, rhs)
                    return lhs_val.op_eq(rhs_val)
                op_func_name = "op_eq"
            case tokens.And():
                lhs_val = self.evaluate_expression(module, lhs)
                if not lhs_val.to_bool().value:
                    return types.Bool(False)
                rhs_val = self.evaluate_expression(module, rhs)
                return types.Bool(rhs_val.to_bool().value)
            case tokens.Or():
                lhs_val = self.evaluate_expression(module, lhs)
                if lhs_val.to_bool().value:
                    return types.Bool(True)
                rhs_val = self.evaluate_expression(module, rhs)
                return types.Bool(rhs_val.to_bool().value)
            case tokens.Percent():
                op_func_name = "op_mod"
            case tokens.Slash():
                op_func_name = "op_div"
            case tokens.Star():
                op_func_name = "op_mul"
            case tokens.Ampersand():
                op_func_name = "op_band"
            case tokens.Pipe():
                op_func_name = "op_bor"
            case tokens.Caret():
                op_func_name = "op_bxor"
            case tokens.ShiftLeft():
                op_func_name = "op_shl"
            case tokens.ShiftRight():
                op_func_name = "op_shr"
            case _:
                raise ValueError(f"Don't know how to evaluate binary operator {op}")
        if op_func_name == "op_plus":
            if slot is None and _wants_slot(lhs):
                slot = self._chain_slot(module, lhs, rhs)
            if slot is None:
                lhs = self.evaluate_expression(module, lhs)
            else:
                lhs = self._evaluate_for(module, lhs, slot)
            if isinstance(lhs, types.ArrayType):
                if _wants_slot(rhs):
                    if slot is None:
                        slot = self._array_slot(lhs)
                    rhs = self._evaluate_for(module, rhs, slot)
                else:
                    rhs = self.evaluate_expression(module, rhs)
                return lhs.op_plus_assign(rhs) if append else lhs.op_plus(rhs)
        else:
            lhs = self.evaluate_expression(module, lhs)
        if op_func := getattr(lhs, op_func_name):
            rhs = self.evaluate_expression(module, rhs)
            return op_func(rhs)
        raise ValueError(f"Don't know how to evaluate binary operator {op}")

    def evaluate_expression(
        self, module, expression, as_lvalue=False
    ) -> ast.ASTNode | type[types.Type] | types.Type:
        """Resolve an expression"""
        match expression:
            case type() if issubclass(expression, types.Type):
                return expression
            case type() if hasattr(expression, "variants"):
                return expression
            case types.Type() as instance:
                return instance
            case types.ResultValue() as result:
                return result
            case ast.BinaryOperator(lhs, op, rhs):
                return self.evaluate_binary_operator(module, op, lhs, rhs, as_lvalue)
            case ast.ChainComparison(operands, ops):
                # `a < b < c …` — evaluate each middle operand once, then
                # short-circuit-AND each pairwise comparison. As soon as
                # any link is false, the result is false and the remaining
                # operands aren't evaluated. evaluate_binary_operator
                # expects unevaluated AST nodes, so dispatch by method
                # name directly on the evaluated values here.
                cmp_methods = {
                    tokens.EqualEqual: "op_eq",
                    tokens.NotEqual: "op_ne",
                    tokens.LessThan: "op_lt",
                    tokens.LessEqual: "op_le",
                    tokens.GreaterThan: "op_gt",
                    tokens.GreaterEqual: "op_ge",
                }
                first_takes_side = _takes_side(operands[0])
                if first_takes_side:
                    prev, nxt = self._variant_operands(module, operands[0], operands[1])
                else:
                    prev = self.evaluate_expression(module, operands[0])
                for i, op in enumerate(ops):
                    if i > 0 or not first_takes_side:
                        nxt = self._evaluate_for(
                            module, operands[i + 1], self._value_slot(prev)
                        )
                    method = getattr(prev, cmp_methods[type(op)])
                    if not method(nxt).to_bool().value:
                        return types.Bool(False)
                    prev = nxt
                return types.Bool(True)
            case ast.TryExpression(inner):
                # A fallible call yields a ResultValue. `try` unwraps Ok or
                # re-raises Err as a ThrownError, which the enclosing fallible
                # frame turns back into an Err result (or main reports).
                value = self.evaluate_expression(module, inner)
                if isinstance(value, types.ResultValue):
                    if value.ok:
                        return value.payload
                    raise ThrownError(value.payload)
                return value
            case ast.MustExpression(inner):
                try:
                    value = self.evaluate_expression(module, inner)
                except ThrownError as e:
                    value = types.ResultValue(False, e.value)
                if isinstance(value, types.ResultValue):
                    if value.ok:
                        return value.payload
                    msg = self._coerce_to_str(module, value.payload)
                    sys.stderr.write(f"panic: {msg.value.decode('utf8')}\n")
                    sys.exit(1)
                return value
            case ast.OptionalUnwrap(value, default, _span):
                v = self.evaluate_expression(module, value)
                if not isinstance(v, types.NoneType):
                    return v
                if default is not None:
                    return self.evaluate_expression(module, default)
                sys.stderr.write("panic: unwrap on none\n")
                sys.exit(1)
            case ast.OptionalDot(value, field, _span):
                v = self.evaluate_expression(module, value)
                if isinstance(v, types.NoneType):
                    return types.none_value
                return getattr(v, field)
            case ast.OptionalMethodCall(value, method, args, _span):
                v = self.evaluate_expression(module, value)
                if isinstance(v, types.NoneType):
                    return types.none_value
                methods = getattr(type(v), "methods", {})
                bound = BoundMethod(methods[method], v)
                arg_values = [self.evaluate_expression(module, arg) for arg in args]
                return self.call_function(module, bound, arg_values)
            case ast.Name() | ast.Variable() as name:
                if as_lvalue:
                    return name
                target = name.__dict__.get("_kod_func")
                return self.lookup(module, name) if target is None else target
            case ast.Literal(value):
                return value
            case ast.Expression(value):
                return self.evaluate_expression(module, value, as_lvalue)
            case ast.FunctionCallParam() as param:
                return self.evaluate_expression(module, param.expression, as_lvalue)
            case ast.ArrayLiteral(elements):
                return self._array_value(
                    [self.evaluate_expression(module, e) for e in elements]
                )
            case ast.FunctionCall(callee, args):
                # .Variant(payload) — implicit enum variant constructor with
                # payload fields. Resolve the enum here so we can pass args
                # straight to its constructor instead of trying to evaluate
                # the bare implicit variant (which errors when fields exist).
                # `str(x)` — explicit conversion intrinsic. Mirrors the
                # codegen's special case: dispatches by the value's runtime
                # type to a string representation. Primitives convert to
                # their decimal / true-false / identity form; structs with a
                # user-defined to_str method dispatch through it.
                if isinstance(callee, ast.Name) and (
                    callee.id == "$str"
                    or (
                        callee.id == "str"
                        and len(args) == 1
                        and self._is_builtin_call(module, callee)
                    )
                ):
                    arg_params = list(args)
                    value = self.evaluate_expression(module, arg_params[0])
                    return self._coerce_to_str(module, value)
                # `hash(x)`: the values compiled code computes.
                if (
                    isinstance(callee, ast.Name)
                    and callee.id == "hash"
                    and len(args) == 1
                    and self._is_builtin_call(module, callee)
                ):
                    arg_params = list(args)
                    value = self.evaluate_expression(module, arg_params[0])
                    return self._hash_value(value)
                if isinstance(callee, ast.ImplicitEnumVariant):
                    enum_type = self._variant_enum(
                        module, callee.variant_name, callee.span
                    )
                    return self._variant_value(
                        module, enum_type, callee.variant_name, list(args)
                    )
                func = self._call_target(module, callee)
                if isinstance(func, type) and issubclass(func, types.StructType):
                    return self._construct(module, func, args, callee.span)
                self._check_labels(func, args)
                args = self._evaluate_args(module, args, func)
                return self.call_function(module, func, args)
            case ast.GenericInstantiation(name, type_args):
                # The generic type, whatever local has its name.
                template = self._named(module, name.id)
                return template.instantiate(tuple(type_args))
            case ast.ImplicitEnumVariant(variant_name):
                enum_type = self._variant_enum(module, variant_name, expression.span)
                if enum_type.variants[variant_name].fields:
                    raise ValueError(
                        f"Implicit enum variant .{variant_name} has payload fields; use explicit syntax"
                    )
                return types.EnumValue(enum_type, variant_name, {})
            case ast.StringSlice(string, start, end):
                s = self.evaluate_expression(module, string)
                n = len(s.value)
                i_val = self.evaluate_expression(module, start).value
                # `end` is None when the source omitted hi (`s[lo..]`);
                # default to len(s) so the slice runs to the end.
                if end is None:
                    j_val = n
                else:
                    j_val = self.evaluate_expression(module, end).value
                # Clamp like the runtime: bounds never wrap Python-style.
                i_val = min(max(i_val, 0), n)
                j_val = min(max(j_val, 0), n)
                if isinstance(s, types.String):
                    return types.String(s.value[i_val:j_val])
                # Array slice: preserve the element type so the result
                # behaves like the source for `for x in arr[lo..hi]`.
                arr_type = type(s)
                return arr_type(s.value[i_val:j_val])
            case ast.MatchExpression(subject, arms):
                value = self.evaluate_expression(module, subject)
                return self.evaluate_expression(
                    module, self._match_arm_body(value, arms)
                )
            case ast.FunctionDeclaration():
                # Function-as-value: `let f = foo` binds the function
                # declaration as the value. Subsequent indirect calls
                # (`f(x)`) feed it back through call_function.
                # Anonymous lambdas don't go through builder's
                # method-attaching pass, so stamp `.module` lazily
                # so call_function can find the enclosing module's
                # scope.
                if not hasattr(expression, "module"):
                    expression.module = module
                return expression
            case _:
                raise ValueError(
                    f"Don't know how to evaluate expression {expression!r}"
                )

    def _variant_slot(self, slot):
        inner = slot
        while isinstance(inner, type) and issubclass(inner, types.OptionalType):
            inner = inner.inner_type
        if not isinstance(inner, type):
            return None
        if issubclass(inner, types.EnumType):
            return inner
        if issubclass(inner, types.ArrayType) and hasattr(inner, "item_type"):
            if self._variant_slot(inner.item_type) is not None:
                return inner
        return None

    def _arg_slots(self, func):
        if isinstance(func, BoundMethod):
            cls = type(func.receiver)
            cache = cls.__dict__.get("_kod_method_slots")
            if cache is None:
                cache = {}
                setattr(cls, "_kod_method_slots", cache)
            slots = cache.get(func.func.name)
            if slots is None:
                subst = getattr(cls, "type_subst", None) or {}
                slots = self._slots_of(
                    [
                        _substituted(p.variable.type, subst)
                        for p in list(func.func.params)[1:]
                    ]
                )
                cache[func.func.name] = slots
            return slots
        if isinstance(func, (ast.FunctionDeclaration, ast.ExternalFunctionDeclaration)):
            slots = func.__dict__.get("_kod_arg_slots")
            if slots is None:
                slots = self._slots_of([p.variable.type for p in func.params])
                func.__dict__["_kod_arg_slots"] = slots
            return slots
        if isinstance(func, type) and issubclass(func, types.StructType):
            slots = func.__dict__.get("_kod_arg_slots")
            if slots is None:
                slots = self._slots_of(
                    [v.type for v in getattr(func, "struct_fields", [])]
                )
                setattr(func, "_kod_arg_slots", slots)
            return slots
        if isinstance(func, types.EnumVariantConstructor):
            fields = func.enum_type.variants[func.variant_name].fields
            return self._slots_of([f.type for f in fields])
        return ()

    def _slots_of(self, slot_types):
        slots = [self._variant_slot(t) for t in slot_types]
        return slots if any(slot is not None for slot in slots) else ()

    def _evaluate_args(self, module, args, func):
        if all(_slot_target(arg) is None for arg in args):
            return [self.evaluate_expression(module, arg) for arg in args]
        slots = self._arg_slots(func)
        return [
            self._evaluate_for(module, arg, slots[i] if i < len(slots) else None)
            for i, arg in enumerate(args)
        ]

    def _evaluate_for(self, module, expr, slot):
        """Evaluate `expr` for `slot`, whose enum its `.Variant`s belong to."""
        target = _slot_target(expr) if slot is not None else None
        if type(slot) is _OkSlot and target is not None:
            if isinstance(target, ast.MatchExpression):
                value = self.evaluate_expression(module, target.expression)
                body = self._match_arm_body(value, target.arms)
                return self._evaluate_for(module, body, slot)
            name, args = _implicit_variant(target)
            if _fits_result(name, args):
                inner = slot.inner if name == "Ok" else None
                payload = self._evaluate_for(module, args[0], inner)
                own = _own_variant(slot.inner, name, args[0], payload)
                if own is not None:
                    return own
                return types.ResultValue(name == "Ok", payload)
            slot = slot.inner
        slot = self._variant_slot(slot) if target is not None else None
        if slot is None:
            return self.evaluate_expression(module, expr)
        expr = target
        if issubclass(slot, types.EnumType):
            name, args = _implicit_variant(expr)
            if name in slot.variants:
                return self._variant_value(module, slot, name, args)
        elif isinstance(expr, ast.ArrayLiteral):
            return slot(
                [self._evaluate_for(module, e, slot.item_type) for e in expr.elements]
            )
        elif type(expr) is ast.BinaryOperator:
            return self.evaluate_binary_operator(
                module, expr.op, expr.lhs, expr.rhs, slot=slot
            )
        if isinstance(expr, ast.MatchExpression):
            value = self.evaluate_expression(module, expr.expression)
            return self._evaluate_for(
                module, self._match_arm_body(value, expr.arms), slot
            )
        return self.evaluate_expression(module, expr)

    def _variant_enum(self, module, variant_name, span):
        """The enum of a context-free `.Variant`: one the module sees, else the only loaded one."""
        scopes = [module.names, self.program.builtins.names]
        for imp in self._aliases(module).values():
            try:
                scopes.append(self._resolve_import(module, imp).names)
            except Exception:
                pass
        for scope in scopes:
            found = _enums_with(scope, variant_name)
            if found:
                return found[0]
        found = []
        for loaded in self.program.modules.values():
            for enum in _enums_with(loaded.names, variant_name):
                if enum not in found:
                    found.append(enum)
        if len(found) > 1:
            names = ", ".join(f"`{enum.name}`" for enum in found[:-1])
            both = "both" if len(found) == 2 else "all"
            raise KodError(
                f"`.{variant_name}` is ambiguous: {names} and `{found[-1].name}` {both} declare it; give the value a type",
                span,
            )
        if found:
            return found[0]
        raise ValueError(f"No enum found with variant .{variant_name}")

    def _check_labels(self, func, args):
        if isinstance(func, BoundMethod):
            name, params = func.func.name, list(func.func.params)[1:]
        elif isinstance(
            func, (ast.FunctionDeclaration, ast.ExternalFunctionDeclaration)
        ):
            name, params = func.name, list(func.params)
        elif isinstance(func, types.EnumVariantConstructor):
            self._check_payload_labels(func.enum_type, func.variant_name, args)
            return
        else:
            return
        for i, (arg, param) in enumerate(zip(args, params)):
            label = arg.label if isinstance(arg, ast.FunctionCallParam) else None
            if (
                label is not None
                and param.label is not None
                and label.id != param.label
            ):
                raise KodError(
                    f"parameter {i} of `{name}` expected label `{param.label}`, got `{label.id}`",
                    label.span,
                )

    def _check_payload_labels(self, enum_type, variant_name, args):
        fields = enum_type.variants[variant_name].fields
        for arg, field in zip(args, fields):
            label = arg.label if isinstance(arg, ast.FunctionCallParam) else None
            if label is not None and label.id != field.id:
                raise KodError(
                    f"`{enum_type.name}.{variant_name}` takes its payload in declaration order: expected `{field.id}`, got `{label.id}`",
                    label.span,
                )

    def _variant_value(self, module, enum_type, variant_name, args):
        self._check_payload_labels(enum_type, variant_name, args)
        vinfo = enum_type.variants[variant_name]
        evaled = [
            self._evaluate_for(module, arg, field.type)
            for arg, field in zip(args, vinfo.fields)
        ]
        if self._is_result_enum(enum_type) and len(evaled) == 1:
            return types.ResultValue(variant_name == "Ok", evaled[0])
        fields = {f.id: v for f, v in zip(vinfo.fields, evaled)}
        return types.EnumValue(enum_type, variant_name, fields)

    def _array_value(self, evaled):
        # Function values are AST nodes, which ArrayType.make can't name.
        if evaled and isinstance(evaled[0], ast.FunctionDeclaration):
            item_type = types.FunctionType
        else:
            item_type = type(evaled[0]) if evaled else types.NoneType
        return types.ArrayType.make(item_type)(evaled)

    def _variant_operands(self, module, lhs, rhs):
        """Operands of `==` with a `.Variant` or `match`, which takes the other side's enum."""
        if type(lhs) is ast.MatchExpression:
            lhs = self._match_leaf(module, lhs)
            if type(lhs) is not ast.ImplicitEnumVariant:
                if _takes_side(rhs):
                    lhs_val = self.evaluate_expression(module, lhs)
                    slot = self._value_slot(lhs_val)
                    return lhs_val, self._evaluate_for(module, rhs, slot)
                lhs_val = self._evaluate_for(
                    module, lhs, self._static_slot(module, rhs)
                )
                return lhs_val, self.evaluate_expression(module, rhs)
        # A unit variant is built without effects, so it can wait for the other side.
        if type(lhs) is ast.ImplicitEnumVariant and type(rhs) is ast.MatchExpression:
            rhs = self._match_leaf(module, rhs)
        if _takes_side(rhs):
            lhs_val = self.evaluate_expression(module, lhs)
            return lhs_val, self._evaluate_for(module, rhs, self._value_slot(lhs_val))
        rhs_val = self.evaluate_expression(module, rhs)
        return self._evaluate_for(module, lhs, self._value_slot(rhs_val)), rhs_val

    def _match_leaf(self, module, expr):
        """The arm body a `match` reaches, through nested ones, with its bindings set."""
        while type(expr) is ast.MatchExpression:
            value = self.evaluate_expression(module, expr.expression)
            expr = self._match_arm_body(value, expr.arms)
        return expr

    def _value_slot(self, value):
        return value.enum_type if isinstance(value, types.EnumValue) else None

    def _quiet_kind(self, module, expr):
        """A value `expr` would have, or else its type, found without evaluating it; else None."""
        t = type(expr)
        if t is ast.Expression:
            return self._quiet_kind(module, expr.value)
        if t is ast.Name or t is ast.Variable:
            try:
                return self.lookup(module, expr)
            except ValueError:
                return None
        if t is type:
            return expr  # an enum the static pass put before a `.`
        if t is ast.FunctionCall:
            func, receiver = self._quiet_callee(module, expr.callee)
            if isinstance(func, type) and issubclass(func, types.StructType):
                return func
            if not isinstance(func, ast.FunctionDeclaration):
                return None
            subst = getattr(receiver, "type_subst", None)
            if subst:
                kind = _param_type(func.return_type, subst)
                if kind is not None:
                    return kind
            owner = getattr(func, "module", None) or module
            return self._type_of(owner, func.return_type, any_type=True)
        if t is ast.MustExpression or t is ast.TryExpression:
            return self._quiet_kind(module, expr.expression)
        if t is ast.OptionalUnwrap:
            kind = self._quiet_kind(module, expr.value)
            if expr.default is not None and (kind is None or kind is types.none_value):
                return self._quiet_kind(module, expr.default)
            return kind
        if t is not ast.BinaryOperator:
            return None
        if type(expr.op) is tokens.Dot:
            owner = self._quiet_kind(module, expr.lhs)
            if isinstance(owner, type) and issubclass(owner, types.EnumType):
                return owner
            if isinstance(owner, type):
                return self._field_slot(owner, expr.rhs.id)
            if isinstance(owner, ast.Module):
                return owner.names.get(expr.rhs.id)
            if hasattr(type(owner), "struct_fields"):
                return getattr(owner, expr.rhs.id, None)
            return None
        if type(expr.op) is tokens.OpenBracket:
            array = self._quiet_kind(module, expr.lhs)
            if isinstance(array, type):
                return getattr(array, "item_type", None)
            if isinstance(array, types.ArrayType):
                item = getattr(type(array), "item_type", None)
                if self._variant_slot(item) is not None:
                    return item
                elements = array.value
                return elements[0] if isinstance(elements, list) and elements else None
        return None

    def _quiet_callee(self, module, callee):
        """What a call of `callee` calls and its receiver's type, found without side effects."""
        if type(callee) is ast.BinaryOperator and type(callee.op) is tokens.Dot:
            if not isinstance(callee.lhs, (ast.Name, ast.Variable)):
                owner = self._quiet_kind(module, callee.lhs)
                cls = owner if isinstance(owner, type) else type(owner)
                methods = getattr(cls, "methods", None)
                if not isinstance(methods, dict):
                    return None, None
                return methods.get(callee.rhs.id), cls
        elif not isinstance(callee, (ast.Name, ast.Variable, ast.GenericInstantiation)):
            return None, None
        try:
            func = self._call_target(module, callee)
        except (ValueError, KeyError, AttributeError):
            return None, None
        if isinstance(func, BoundMethod):
            return func.func, type(func.receiver)
        return func, None

    def _chain_slot(self, module, lhs, rhs):
        """The array slot of a `+` chain's first operand that isn't a literal or `match`."""
        anchor = _chain_anchor(lhs)
        if anchor is None:
            anchor = _chain_anchor(rhs)
        return None if anchor is None else self._static_slot(module, anchor)

    def _static_slot(self, module, expr):
        """The enum, or array of one, that `expr` has, found without evaluating it."""
        kind = self._quiet_kind(module, expr)
        if isinstance(kind, type):
            return self._variant_slot(kind)
        slot = self._value_slot(kind)
        return slot if slot is not None else self._array_slot(kind)

    def _elem_slot(self, array):
        """The enum, or array of one, that `array`'s elements have, from its first."""
        item = getattr(type(array), "item_type", None)
        if self._variant_slot(item) is not None:
            return item
        elements = getattr(array, "value", None)
        if not isinstance(elements, list) or not elements:
            return None
        if isinstance(elements[0], types.EnumValue):
            return elements[0].enum_type
        return self._array_slot(elements[0])

    def _array_slot(self, array):
        """`array`'s own type, as a slot for the `.Variant`s added to it."""
        if not isinstance(array, types.ArrayType):
            return None
        elem = self._elem_slot(array)
        return types.ArrayType.make(elem) if elem is not None else None

    def _field_slot(self, obj, name):
        cls = obj if isinstance(obj, type) else type(obj)
        for field in getattr(cls, "struct_fields", []):
            if field.id == name:
                return field.type
        return None

    def _assign_slot(self, module, lhs):
        """What an assignment to `lhs` stores, if known without side effects."""
        if isinstance(lhs, (ast.Name, ast.Variable)):
            try:
                value = self.lookup(module, lhs)
            except ValueError:
                return None
            slot = self._value_slot(value)
            return slot if slot is not None else self._array_slot(value)
        if not isinstance(lhs, ast.BinaryOperator) or not isinstance(
            lhs.lhs, (ast.Name, ast.Variable)
        ):
            return None
        try:
            obj = self.lookup(module, lhs.lhs)
        except ValueError:
            return None
        return self._store_slot(obj, lhs)

    def _store_slot(self, obj, lhs):
        """What a store into field or element `lhs` of `obj` takes."""
        if isinstance(lhs.op, tokens.Dot):
            return self._field_slot(obj, lhs.rhs.id)
        if isinstance(lhs.op, tokens.OpenBracket):
            setter = getattr(type(obj), "methods", {}).get("op_index_set")
            if setter is not None:
                slots = self._arg_slots(BoundMethod(setter, obj))
                return slots[1] if len(slots) > 1 else None
            return self._elem_slot(obj)
        return None

    def _return_slot(self):
        """What a `return` in the running function goes to; cached."""
        if not self.funcs:
            return None
        func = self.funcs[-1]
        slot = func.__dict__.get("_kod_return_slot", False)
        if slot is False:
            slot = self._type_of(getattr(func, "module", None), func.return_type)
            if self._returns_result(func):
                slot = _OkSlot(slot)
            func.__dict__["_kod_return_slot"] = slot
        return slot

    def _type_of(self, module, expr, any_type=False):
        """The enum, or array of one, that a return type names in `module`; any type if `any_type`."""
        if module is None:
            return None
        if ast.is_result_type_expr(expr):
            return self._type_of(module, expr.args[0], any_type)
        if isinstance(expr, ast.OptionalTypeExpr):
            return self._type_of(module, expr.inner, any_type)
        if isinstance(expr, ast.ArrayTypeExpr):
            inner = self._type_of(module, expr.element, any_type)
            return types.ArrayType.make(inner) if inner is not None else None
        if isinstance(expr, ast.ResolvedTypeExpr):
            return expr.resolved if any_type else self._variant_slot(expr.resolved)
        owner = None
        if isinstance(expr, ast.QualifiedTypeExpr):
            owner = self._alias_import(module, expr.module)
        elif isinstance(expr, ast.NamedTypeExpr):
            owner = module
            if expr.name not in module.names:
                owner = next(
                    (i for i in module.get_imports() if expr.name in i.items), None
                )
        else:
            return None
        if isinstance(owner, ast.Import):
            owner = self._resolve_import(module, owner)
        if not isinstance(owner, ast.Module):
            return None
        named = owner.names.get(expr.name)
        if isinstance(named, type) and issubclass(named, types.EnumType):
            if self._is_result_enum(named):
                named = named.variants["Ok"].fields[0].type
        if any_type:
            return named if isinstance(named, type) else None
        return self._variant_slot(named)

    def _match_arm_body(self, value, arms):
        """The body of the arm that `value` matches, its bindings set."""
        for arm in arms:
            arm = _value_arm(arm, value)
            if isinstance(arm.pattern, ast.IntegerPattern):
                if value.value == arm.pattern.value:
                    return arm.body
            elif isinstance(arm.pattern, ast.StringPattern):
                if value.to_py_str() == arm.pattern.value:
                    return arm.body
            elif isinstance(arm.pattern, ast.WildcardPattern):
                return arm.body
            elif isinstance(arm.pattern, ast.OptionalNonePattern):
                if isinstance(value, types.NoneType):
                    return arm.body
            elif isinstance(arm.pattern, ast.OptionalSomePattern):
                if not isinstance(value, types.NoneType):
                    if arm.pattern.binding:
                        self.stack[-1][arm.pattern.binding] = value
                    return arm.body
            elif isinstance(arm.pattern, ast.ResultOkPattern):
                if isinstance(value, types.ResultValue) and value.ok:
                    if arm.pattern.binding:
                        self.stack[-1][arm.pattern.binding] = value.payload
                    return arm.body
            elif isinstance(arm.pattern, ast.ResultErrPattern):
                if isinstance(value, types.ResultValue) and not value.ok:
                    if arm.pattern.binding:
                        self.stack[-1][arm.pattern.binding] = value.payload
                    return arm.body
            elif isinstance(arm.pattern, ast.TypePattern):
                if type(value).__name__ == arm.pattern.type_name:
                    if arm.pattern.binding:
                        self.stack[-1][arm.pattern.binding] = value
                    return arm.body
            elif isinstance(
                arm.pattern,
                (ast.EnumVariantPattern, ast.ImplicitEnumVariantPattern),
            ):
                if (
                    isinstance(value, types.EnumValue)
                    and value.variant_name == arm.pattern.variant_name
                ):
                    bindings = getattr(arm.pattern, "bindings", [])
                    field_values = list(value.fields.values())
                    for binding_name, field_value in zip(bindings, field_values):
                        self.stack[-1][binding_name] = field_value
                    return arm.body
        raise ValueError("Non-exhaustive match expression")

    def _thaw(self, patterns):
        """Unlike a `let`'s, the names `patterns` bind can be reassigned."""
        for pattern in patterns:
            self.immutable_stack[-1].difference_update(_pattern_names(pattern))

    def execute_statement(self, module, statement):
        """Execute a statement"""
        match statement:
            case ast.Return(expression):
                slot = None
                if _slot_target(expression) is not None:
                    slot = self._return_slot()
                value = self._evaluate_for(module, expression, slot)
                raise ReturnValue(value)
            case ast.ThrowStatement(expression):
                value = self.evaluate_expression(module, expression)
                raise ThrownError(value)
            case ast.Import():
                # The body scan in `Module.names` already binds local_name
                # to the Import statement; `lookup` resolves that to the
                # actual Module on the fly. Overwriting names here would
                # replace the Import with the Module object and break the
                # iface/enum search loops below that rely on the Import
                # marker.
                pass
            case ast.InterfaceDeclaration():
                pass
            case ast.FunctionDeclaration(name) | ast.ExternalFunctionDeclaration(name):
                module.names[name] = statement
                setattr(statement, "module", module)
            case ast.FunctionCall():
                callee = self._call_target(module, statement.callee)
                if isinstance(callee, type) and issubclass(callee, types.StructType):
                    self._construct(module, callee, statement.args, statement.span)
                    return
                args = self._evaluate_args(module, statement.args, callee)
                self.call_function(module, callee, args)
            case ast.VariableDeclaration(variable, value, _span, mutable):
                lhs = self.evaluate_expression(module, variable, as_lvalue=True)
                value = self._evaluate_for(module, value, variable.type)
                if len(self.stack) > 1:
                    self.stack[-1][lhs.id] = self.evaluate_expression(module, value)
                    # Track (re)declared mutability for this frame; most
                    # recent declaration wins, matching compile_let.
                    if mutable:
                        self.immutable_stack[-1].discard(lhs.id)
                    else:
                        self.immutable_stack[-1].add(lhs.id)
                else:
                    module.names[lhs.id] = self.evaluate_expression(module, value)
            case ast.TypeDeclaration(variable, value):
                lhs = self.evaluate_expression(module, variable, as_lvalue=True)
                if isinstance(value, types.GenericTemplate):
                    type_ = value
                else:
                    type_ = self.evaluate_expression(module, value)
                module.names[lhs.id] = type_
                # Imports run first, so the defining module stamps before any alias.
                if isinstance(type_, types.GenericTemplate):
                    owner = type_.template
                else:
                    owner = getattr(type_, "template_origin", type_)
                if "decl_module" not in getattr(owner, "__dict__", {}):
                    try:
                        owner.decl_module = module
                    except (AttributeError, TypeError):
                        pass
                for method in getattr(owner, "methods", {}).values():
                    if getattr(method, "module", None) is None:
                        method.module = module
            case ast.Assignment(lhs, rhs):
                slot = None
                target = _slot_target(rhs)
                if target is not None:
                    slot = self._assign_slot(module, lhs)
                # `+=` and `-=` share their target node with the operator's lhs.
                compound = isinstance(rhs, ast.BinaryOperator) and rhs.lhs is lhs
                if isinstance(lhs, ast.BinaryOperator) and isinstance(
                    lhs.op, tokens.Dot
                ):
                    obj = self.evaluate_expression(module, lhs.lhs)
                    if compound:
                        current = getattr(obj, lhs.rhs.id)
                        rhs_slot = None
                        if _wants_slot(rhs.rhs):
                            rhs_slot = self._field_slot(obj, lhs.rhs.id)
                        rhs_val = self.evaluate_binary_operator(
                            module,
                            rhs.op,
                            current,
                            rhs.rhs,
                            slot=rhs_slot,
                            append=type(rhs.op) is tokens.Plus,
                        )
                    else:
                        if slot is None and target is not None:
                            slot = self._store_slot(obj, lhs)
                        rhs_val = self._evaluate_for(module, rhs, slot)
                    setattr(obj, lhs.rhs.id, rhs_val)
                elif isinstance(lhs, ast.BinaryOperator) and isinstance(
                    lhs.op, tokens.OpenBracket
                ):
                    obj = self.evaluate_expression(module, lhs.lhs)
                    struct_methods = getattr(type(obj), "methods", {})
                    setter = struct_methods.get("op_index_set")
                    if setter is not None:
                        bound = BoundMethod(setter, obj)
                        key_val = self._evaluate_args(module, [lhs.rhs], bound)[0]
                    else:
                        key_val = self.evaluate_expression(module, lhs.rhs)
                    if compound:
                        if "op_index" in struct_methods:
                            getter = BoundMethod(struct_methods["op_index"], obj)
                            current = self.call_function(module, getter, [key_val])
                        else:
                            current = obj.op_index(key_val)
                        rhs_val = self.evaluate_binary_operator(
                            module,
                            rhs.op,
                            current,
                            rhs.rhs,
                            append=type(rhs.op) is tokens.Plus,
                        )
                    else:
                        if slot is None and target is not None:
                            slot = self._store_slot(obj, lhs)
                        rhs_val = self._evaluate_for(module, rhs, slot)
                    if setter is not None:
                        self.call_function(module, bound, [key_val, rhs_val])
                    else:
                        obj.value[key_val.value] = rhs_val
                else:
                    if compound and type(rhs.op) is tokens.Plus:
                        current = self.evaluate_expression(module, lhs)
                        rhs_val = self.evaluate_binary_operator(
                            module,
                            rhs.op,
                            current,
                            rhs.rhs,
                            slot=self._variant_slot(slot) if slot is not None else None,
                            append=True,
                        )
                    else:
                        rhs_val = self._evaluate_for(module, rhs, slot)
                    lhs_val = self.evaluate_expression(module, lhs, as_lvalue=True)
                    if (
                        _ENFORCE_IMMUTABILITY
                        and len(self.stack) > 1
                        and lhs_val.id in self.immutable_stack[-1]
                    ):
                        raise KodError(
                            f"cannot reassign immutable binding `{lhs_val.id}`; "
                            "declare it with `mut`",
                            lhs.span,
                        )
                    self.assign(module, lhs_val.id, rhs_val)
            case ast.IfStatement(condition, true_branch, false_branch):
                matched = (
                    self.evaluate_expression(module, condition).to_bool().value is True
                )
                for statement in true_branch if matched else false_branch:
                    self.execute_statement(module, statement)
            case ast.BreakStatement():
                raise BreakSignal()
            case ast.ContinueStatement():
                raise ContinueSignal()
            case ast.ForStatement(condition, body):
                while (
                    self.evaluate_expression(module, condition).to_bool().value is True
                ):
                    try:
                        for stmt in body:
                            self.execute_statement(module, stmt)
                    except BreakSignal:
                        break
                    except ContinueSignal:
                        continue
            case ast.ForEachStatement(binding, iterable, body):
                array = self.evaluate_expression(module, iterable)
                thaw = "_kod_thaw" in statement.__dict__
                for element in array.value:
                    self.stack[-1][binding] = element
                    if thaw:
                        self.immutable_stack[-1].discard(binding)
                    try:
                        for stmt in body:
                            self.execute_statement(module, stmt)
                    except BreakSignal:
                        break
                    except ContinueSignal:
                        continue
            case ast.MatchStatement(expression, arms):
                if "_kod_thaw" in statement.__dict__:
                    self._thaw(arm.pattern for arm in arms)
                value = self.evaluate_expression(module, expression)
                for arm in arms:
                    arm = _value_arm(arm, value)
                    if isinstance(arm.pattern, ast.IntegerPattern):
                        if value.value == arm.pattern.value:
                            for stmt in arm.body:
                                self.execute_statement(module, stmt)
                            break
                    elif isinstance(arm.pattern, ast.StringPattern):
                        if value.to_py_str() == arm.pattern.value:
                            for stmt in arm.body:
                                self.execute_statement(module, stmt)
                            break
                    elif isinstance(arm.pattern, ast.WildcardPattern):
                        for stmt in arm.body:
                            self.execute_statement(module, stmt)
                        break
                    elif isinstance(arm.pattern, ast.OptionalNonePattern):
                        if isinstance(value, types.NoneType):
                            for stmt in arm.body:
                                self.execute_statement(module, stmt)
                            break
                    elif isinstance(arm.pattern, ast.OptionalSomePattern):
                        if not isinstance(value, types.NoneType):
                            if arm.pattern.binding:
                                self.stack[-1][arm.pattern.binding] = value
                            for stmt in arm.body:
                                self.execute_statement(module, stmt)
                            break
                    elif isinstance(arm.pattern, ast.ResultOkPattern):
                        if isinstance(value, types.ResultValue) and value.ok:
                            if arm.pattern.binding:
                                self.stack[-1][arm.pattern.binding] = value.payload
                            for stmt in arm.body:
                                self.execute_statement(module, stmt)
                            break
                    elif isinstance(arm.pattern, ast.ResultErrPattern):
                        if isinstance(value, types.ResultValue) and not value.ok:
                            if arm.pattern.binding:
                                self.stack[-1][arm.pattern.binding] = value.payload
                            for stmt in arm.body:
                                self.execute_statement(module, stmt)
                            break
                    elif isinstance(arm.pattern, ast.TypePattern):
                        if type(value).__name__ == arm.pattern.type_name:
                            if arm.pattern.binding:
                                self.stack[-1][arm.pattern.binding] = value
                            for stmt in arm.body:
                                self.execute_statement(module, stmt)
                            break
                    elif isinstance(
                        arm.pattern,
                        (ast.EnumVariantPattern, ast.ImplicitEnumVariantPattern),
                    ):
                        if (
                            isinstance(value, types.EnumValue)
                            and value.variant_name == arm.pattern.variant_name
                        ):
                            bindings = getattr(arm.pattern, "bindings", [])
                            field_values = list(value.fields.values())
                            for binding_name, field_value in zip(
                                bindings, field_values
                            ):
                                self.stack[-1][binding_name] = field_value
                            for stmt in arm.body:
                                self.execute_statement(module, stmt)
                            break
            case ast.LetElseStatement(pattern, value_expr, else_body):
                value = self.evaluate_expression(module, value_expr)
                pattern = _value_pattern(pattern, value)
                matched = False
                if isinstance(
                    pattern, (ast.EnumVariantPattern, ast.ImplicitEnumVariantPattern)
                ):
                    if (
                        isinstance(value, types.EnumValue)
                        and value.variant_name == pattern.variant_name
                    ):
                        bindings = getattr(pattern, "bindings", [])
                        field_values = list(value.fields.values())
                        for binding_name, field_value in zip(bindings, field_values):
                            self.stack[-1][binding_name] = field_value
                        matched = True
                elif isinstance(pattern, ast.OptionalNonePattern):
                    matched = isinstance(value, types.NoneType)
                elif isinstance(pattern, ast.OptionalSomePattern):
                    if not isinstance(value, types.NoneType):
                        if pattern.binding:
                            self.stack[-1][pattern.binding] = value
                        matched = True
                elif isinstance(pattern, (ast.ResultOkPattern, ast.ResultErrPattern)):
                    if value.ok == isinstance(pattern, ast.ResultOkPattern):
                        if pattern.binding:
                            self.stack[-1][pattern.binding] = value.payload
                        matched = True
                if not matched:
                    for stmt in else_body:
                        self.execute_statement(module, stmt)
                elif "_kod_thaw" in statement.__dict__:
                    self._thaw([statement.pattern])
            case _:
                raise ValueError(f"Unexpected statement {statement}")

    def c_type(self, type_):
        """Convert a Kod type to a C type"""
        if type_ is types.String:
            return ctypes.c_char_p
        if type_ is types.Int64:
            return ctypes.c_int
        raise ValueError(f"Unknown type {type_!r}")

    def _map_dict_key(self, value):
        """Turn a Kod value into a hashable Python key for the Map fast
        path, equal exactly when `==` holds: str/bytes by content,
        int/bool by value, enums by variant; everything else falls back
        to identity (the compiled side's pointer equality)."""
        if isinstance(value, types.String):
            return ("str", value.value)
        if isinstance(value, types.Bytes):
            return ("bytes", value.value)
        if isinstance(value, types.Int64):
            return ("int", value.value)
        if isinstance(value, types.Bool):
            return ("bool", value.value)
        if isinstance(value, types.EnumValue):
            return ("enum", id(value.enum_type), value.variant_name)
        return ("id", id(value))

    def _map_py_dict(self, map_instance) -> dict:
        """Lazily attach a Python dict mirror to a Map instance. The
        dense keys/values arrays are kept as the source of truth for
        iteration order; the dict only serves O(1) lookup."""
        cached = getattr(map_instance, "_py_dict", None)
        if cached is not None:
            return cached
        d: dict = {}
        keys = getattr(map_instance, "keys", None)
        values = getattr(map_instance, "values", None)
        if keys is not None and values is not None:
            for k, v in zip(keys.value, values.value):
                d[self._map_dict_key(k)] = v
        map_instance._py_dict = d
        return d

    def _fast_map_method(self, name: str, receiver, args):
        d = self._map_py_dict(receiver)
        if name in ("get", "op_index"):
            py_key = self._map_dict_key(args[0])
            if py_key in d:
                return d[py_key]
            return types.none_value
        if name in ("set", "op_index_set"):
            key, value = args[0], args[1]
            py_key = self._map_dict_key(key)
            if py_key in d:
                # Update existing entry: locate by key in the dense
                # array and overwrite values[i]. Rare path (most sets
                # are new inserts), so the linear scan is fine.
                for i, existing in enumerate(receiver.keys.value):
                    if self._map_dict_key(existing) == py_key:
                        receiver.values.value[i] = value
                        break
            else:
                receiver.keys.value.append(key)
                receiver.values.value.append(value)
            d[py_key] = value
            return types.none_value
        if name == "contains":
            return types.Bool(self._map_dict_key(args[0]) in d)
        raise ValueError(f"unknown Map method {name!r}")

    def _hash_value(self, value) -> "types.Int64":
        """What compiled `hash(x)` gives; a value the compiler rejects hashes by id."""
        if isinstance(value, types.Int64):
            return types.Int64(value.value)
        if isinstance(value, types.Bool):
            return types.Int64(1 if value.value else 0)
        if isinstance(value, (types.String, types.Bytes)):
            h = 5381
            for byte in value.value:
                h = (h * 33 + byte) & 0xFFFF_FFFF_FFFF_FFFF
            return types.Int64(h - (1 << 64) if h >= 1 << 63 else h)
        if isinstance(value, types.EnumValue):
            info = value.enum_type.variants[value.variant_name]
            return types.Int64(info.discriminant)
        return types.Int64(id(value))

    def _coerce_to_str(self, module, value):
        """Convert a value to a Kod `str`. Used to implement the `str(x)`
        intrinsic: int → decimal, bool → "true"/"false", str → identity,
        struct with `to_str` method → call that method."""
        if isinstance(value, types.String):
            return value
        if isinstance(value, types.Bytes):
            return types.String(value.value)
        if isinstance(value, types.Int64):
            return types.String(str(value.value).encode("utf8"))
        if isinstance(value, types.Bool):
            return types.String(b"true" if value.value else b"false")
        methods = getattr(type(value), "methods", None) or {}
        if "to_str" in methods:
            return self.call_function(module, methods["to_str"], (value,))
        return types.String(str(value).encode("utf8"))

    def _construct(self, module, struct_type, args, span):
        """`struct_type(args)`: each value goes to the field its label names."""
        fields = struct_type.__dict__.get("_kod_fields")
        if fields is None:
            fields = {
                v.id: (v, self._variant_slot(v.type))
                for v in getattr(struct_type, "struct_fields", [])
            }
            setattr(struct_type, "_kod_fields", fields)
        shown = struct_type.__name__
        names = []
        for i, arg in enumerate(args):
            label = arg.label if isinstance(arg, ast.FunctionCallParam) else None
            if label is None:
                raise KodError(_unlabelled_field(shown, fields, args, i), arg.span)
            name = label.id
            where = label.span
            if name not in fields:
                raise KodError(f"struct `{shown}` has no field `{name}`", where)
            if name in names:
                raise KodError(f"field `{name}` is given twice", where)
            names.append(name)
        for name, (field, _slot) in fields.items():
            if field.default is None and name not in names:
                raise KodError(
                    f"struct `{shown}` requires field `{name}` (it has no default)",
                    span,
                )
        kwargs = {
            name: self._evaluate_for(module, arg, fields[name][1])
            for name, arg in zip(names, args)
        }
        if len(kwargs) < len(fields):
            owner = getattr(struct_type, "template_origin", struct_type)
            owner_module = getattr(owner, "decl_module", None) or module
            for name, (field, _slot) in fields.items():
                if name not in kwargs:
                    kwargs[name] = self._evaluate_default(
                        owner_module, field.default, field.type
                    )
        return struct_type(**kwargs)

    def _evaluate_default(self, module, expr, slot=None):
        """A default value, evaluated without the caller's locals in view."""
        self.stack.append({})
        self.immutable_stack.append(set())
        try:
            return self._evaluate_for(module, expr, slot)
        finally:
            self.stack.pop()
            self.immutable_stack.pop()

    def call_function(self, module, func, args=()):
        """Call a function"""
        if callable(func):
            if isinstance(func, type) and issubclass(func, types.StructType):
                arg_names = [field.name for field in dataclasses.fields(func)]
                kwargs = {name: value for name, value in zip(arg_names, args)}
                # Fill any field the construction omitted with its default
                # expression. struct_fields carries the ast.Variable for
                # each field, with `.default` set when declared `= expr`.
                owner = getattr(func, "template_origin", func)
                owner_module = getattr(owner, "decl_module", None) or module
                for v in getattr(func, "struct_fields", []):
                    if v.id not in kwargs and v.default is not None:
                        kwargs[v.id] = self._evaluate_default(
                            owner_module, v.default, v.type
                        )
                return func(**kwargs)
            return func(*args)
        if isinstance(func, ast.ExternalFunctionDeclaration):
            if func.name == "read_file":
                path = args[0].value.decode("utf8")
                try:
                    return types.String(open(path, "rb").read())
                except OSError:
                    return types.String(b"")
            if func.name == "kod_is_file":
                path = args[0].value.decode("utf8")
                return types.Int64(1 if os.path.isfile(path) else 0)
            if func.name == "kod_panic":
                # Mirror the runtime helper: print "panic: <msg>" to
                # stderr and exit(1). The Python interpreter has no
                # access to the C symbol so we implement it directly.
                msg = args[0].value.decode("utf8")
                sys.stderr.write(f"panic: {msg}\n")
                sys.exit(1)
            if func.name == "kod_puts":
                # Used to dispatch as libc puts; the runtime now ships
                # its own `kod_puts` wrapper. Route via libc.puts so
                # this still shares the libc stdout buffer that
                # putchar / printf write into — Python's sys.stdout
                # has its own buffer and would interleave wrong.
                libc.puts(args[0].value)
                return types.Int64(0)
            if func.name == "kod_bytes_from_array":
                # Mirror runtime kod_bytes_from_array: pack each int64
                # entry's low 8 bits into a fresh byte buffer.
                buf = bytes(int(v.value) & 0xFF for v in args[0].value)
                return types.Bytes(buf)
            if func.name == "kod_str_to_bytes":
                return types.Bytes(args[0].value)
            if func.name == "kod_bytes_to_str":
                return types.String(args[0].value)
            if func.name == "kod_eprint":
                # Mirror runtime kod_eprint: write to stderr, no exit.
                msg = args[0].value.decode("utf8")
                sys.stderr.write(f"{msg}\n")
                return types.none_value
            if func.name == "read_stdin_line":
                # Mirror runtime read_stdin_line: read one '\n'-terminated
                # line, strip a trailing '\r', empty string on EOF.
                line = sys.stdin.readline()
                if line.endswith("\n"):
                    line = line[:-1]
                if line.endswith("\r"):
                    line = line[:-1]
                return types.String(line.encode("utf8"))
            if func.name == "read_stdin_exact":
                # Mirror runtime read_stdin_exact: read exactly n bytes,
                # truncated on EOF (caller length-checks).
                n = int(args[0].value)
                buf = (
                    sys.stdin.buffer.read(n)
                    if hasattr(sys.stdin, "buffer")
                    else sys.stdin.read(n).encode("utf8")
                )
                return types.String(buf)
            if func.name == "write_stdout":
                # Mirror runtime write_stdout: raw write, no newline,
                # no flush.
                msg = args[0].value.decode("utf8")
                sys.stdout.write(msg)
                return types.none_value
            c_func = getattr(libc, func.name)
            c_func.argtypes = [self.c_type(p.variable.type) for p in func.params]
            args = [arg.value for arg in args]
            result = c_func(*args)
            # return_type is the data-only ast.TypeExpr; extern returns are
            # always primitive names, so match syntactically.
            if func.return_type == ast.NamedTypeExpr("int64"):
                return types.Int64(result)
            if func.return_type == ast.NamedTypeExpr("str"):
                return types.String(result)
            return types.none_value

        builtin_len = (
            isinstance(func, ast.FunctionDeclaration)
            and func.name == "len"
            and func is self.program.builtins.names.get("len")
        )
        if builtin_len and len(args) == 1 and isinstance(args[0], types.ArrayType):
            return types.Int64(len(args[0].value))
        if builtin_len and len(args) == 1 and isinstance(args[0], types.String):
            # str's `len` used to live in builtins.kod as a wrapper
            # around the libc strlen extern. The compile path now reads
            # the str struct's header directly; we mirror it here so
            # the interpreter doesn't fall back to a vanished function.
            return types.Int64(len(args[0].value))
        if builtin_len and len(args) == 1 and isinstance(args[0], types.Bytes):
            return types.Int64(len(args[0].value))
        if (
            builtin_len
            and len(args) == 1
            and "len" in getattr(type(args[0]), "methods", {})
        ):
            len_method = type(args[0]).methods["len"]
            return self.call_function(module, BoundMethod(len_method, args[0]), [])

        if isinstance(func, BoundMethod):
            receiver = func.receiver
            method = func.func
            # Map fast path: short-circuit the interpreted compact-dict
            # logic with a real Python dict. Otherwise every probe step
            # inside Map.get/set/contains becomes dozens of interpreted
            # statements, which dominates bootstrap time.
            if getattr(method, "struct_name", None) == "Map" and method.name in (
                "get",
                "set",
                "contains",
                "op_index",
                "op_index_set",
            ):
                return self._fast_map_method(method.name, receiver, args)
            func = method
            all_params = list(func.params)
            explicit_params = all_params[1:]  # skip self
            n_args = len(args)
            frame = {}
            for i, param in enumerate(explicit_params):
                if i < n_args:
                    a = args[i]
                    frame[param.variable.id] = (
                        self.lookup(module, a) if isinstance(a, ast.Variable) else a
                    )
                elif param.default is not None:
                    frame[param.variable.id] = self._evaluate_default(
                        func.module, param.default, param.variable.type
                    )
            frame["self"] = receiver
            if "_kod_scoped" not in func.__dict__:
                _mark_scopes(func, self.program)
            self.stack.append(frame)
            self.funcs.append(func)
            param_immutable = {p.variable.id for p in explicit_params if not p.mutable}
            if all_params and not all_params[0].mutable:
                param_immutable.add("self")
            self.immutable_stack.append(param_immutable)
            fallible = self._returns_result(func)
            try:
                for statement in func.body:
                    self.execute_statement(func.module, statement)
                if fallible:
                    return types.ResultValue(True, types.none_value)
            except ReturnValue as return_value:
                if fallible:
                    if self._is_result_value(return_value.value):
                        return return_value.value
                    return types.ResultValue(True, return_value.value)
                return return_value.value
            except ThrownError as thrown:
                if fallible:
                    return types.ResultValue(False, thrown.value)
                raise
            finally:
                self.stack.pop()
                self.immutable_stack.pop()
                self.funcs.pop()
            return None

        # Map args to params. Trailing params with a declared
        # default value fill in when the call supplied fewer args
        # — evaluated in the function's defining-module scope so
        # name lookups inside the default expression see the right
        # scope.
        n_args = len(args)
        frame = {}
        for i, param in enumerate(func.params):
            if i < n_args:
                a = args[i]
                frame[param.variable.id] = (
                    self.lookup(module, a) if isinstance(a, ast.Variable) else a
                )
            elif param.default is not None:
                frame[param.variable.id] = self._evaluate_default(
                    func.module, param.default, param.variable.type
                )
        args = frame
        if "_kod_scoped" not in func.__dict__:
            _mark_scopes(func, self.program)
        self.stack.append(args)
        self.funcs.append(func)
        self.immutable_stack.append(
            {p.variable.id for p in func.params if not p.mutable}
        )
        fallible = self._returns_result(func)
        try:
            for statement in func.body:
                self.execute_statement(func.module, statement)
            if fallible:
                return types.ResultValue(True, types.none_value)
        except ReturnValue as return_value:
            if fallible:
                if self._is_result_value(return_value.value):
                    return return_value.value
                return types.ResultValue(True, return_value.value)
            return return_value.value
        except ThrownError as thrown:
            if fallible:
                return types.ResultValue(False, thrown.value)
            raise
        finally:
            self.stack.pop()
            self.immutable_stack.pop()
            self.funcs.pop()
