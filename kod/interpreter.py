#!/usr/bin/env python
"""Simple interpreter for the Kod language"""

import ctypes
import dataclasses
import sys
from functools import partial
from typing import Any

from kod import ast, tokens
from kod import values as types
from kod.exceptions import KodError
from kod.program import Program

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


class Interpreter:
    """Simple interpreter for the Kod language"""

    def __init__(self, program: Program):
        self.program = program
        self.stack = [{}]
        # Parallel to self.stack: the set of immutable (`let`, not `mut`)
        # binding names in each frame. Mirrors the codegen's per-VarSlot
        # mutable flag so `_interpret` rejects the same reassignments.
        self.immutable_stack = [set()]

    def run(self, file, argv=()):
        """Run the program"""
        for module in self.program:
            for statement in module.body:
                self.execute_statement(module, statement)
        entry_module = self.program.get_module(file.canonical_path.with_suffix(""))
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
        sys.exit(exit_code.value if exit_code else 0)

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

    def lookup(self, module, name) -> Any:
        """Look up a variable in the stack"""
        match name:
            case ast.Variable() | ast.Name():
                name = name.id
        for frame in self.stack[-1], module.names, self.program.builtins.names:
            if name in frame:
                value = frame[name]
                if isinstance(value, ast.StringLiteral):
                    value = value.value
                elif isinstance(value, ast.Import):
                    return self._resolve_import(module, value)
                return value
        raise ValueError(f"Unknown name {name!r}")

    def evaluate_binary_operator(self, module, op, lhs, rhs, as_lvalue=False):
        """Evaluate a binary operator"""
        match op:
            case tokens.Dot():
                lhs = self.evaluate_expression(module, lhs, as_lvalue)
                if isinstance(lhs, ast.Module):
                    return lhs.names[rhs.id]
                methods = getattr(type(lhs), "methods", {})
                if rhs.id in methods:
                    return BoundMethod(methods[rhs.id], lhs)
                return getattr(lhs, rhs.id)
            case tokens.OpenBracket():
                lhs_val = self.evaluate_expression(module, lhs)
                rhs_val = self.evaluate_expression(module, rhs)
                struct_methods = getattr(type(lhs_val), "methods", {})
                if "op_index" in struct_methods:
                    return self.call_function(
                        module,
                        BoundMethod(struct_methods["op_index"], lhs_val),
                        [rhs_val],
                    )
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
                op_func_name = "op_ne"
            case tokens.LessThan():
                op_func_name = "op_lt"
            case tokens.LessEqual():
                op_func_name = "op_le"
            case tokens.GreaterThan():
                op_func_name = "op_gt"
            case tokens.GreaterEqual():
                op_func_name = "op_ge"
            case tokens.Is():
                lhs_val = self.evaluate_expression(module, lhs)
                is_none = isinstance(lhs_val, types.NoneType)
                if isinstance(rhs, ast.NoneLiteral):
                    return types.Bool(is_none)
                else:
                    return types.Bool(not is_none)
            case tokens.EqualEqual():
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
            case _:
                raise ValueError(f"Don't know how to evaluate binary operator {op}")
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
            case ast.BinaryOperator(lhs, op, rhs):
                return self.evaluate_binary_operator(module, op, lhs, rhs, as_lvalue)
            case ast.TryExpression(inner):
                # Letting the ThrownError propagate is exactly the `try`
                # semantics — the surrounding call_function frame catches
                # it (or main does).
                return self.evaluate_expression(module, inner)
            case ast.MustExpression(inner):
                try:
                    return self.evaluate_expression(module, inner)
                except ThrownError as e:
                    msg = self._coerce_to_str(module, e.value)
                    sys.stderr.write(f"panic: {msg.value.decode('utf8')}\n")
                    sys.exit(1)
            case ast.Name() | ast.Variable() as name:
                return name if as_lvalue else self.lookup(module, name)
            case ast.Literal(value):
                return value
            case ast.Expression(value):
                return self.evaluate_expression(module, value, as_lvalue)
            case ast.FunctionCallParam() as param:
                return self.evaluate_expression(module, param.expression, as_lvalue)
            case ast.ArrayLiteral(elements):
                evaled = [self.evaluate_expression(module, e) for e in elements]
                item_type = type(evaled[0]) if evaled else types.NoneType
                arr_type = types.ArrayType.make(item_type)
                return arr_type(evaled)
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
                if (
                    isinstance(callee, ast.Name)
                    and callee.id == "str"
                    and len(args) == 1
                ):
                    arg_params = list(args)
                    value = self.evaluate_expression(module, arg_params[0])
                    return self._coerce_to_str(module, value)
                # `hash(x)` — int64 hash. Compiled side uses identity
                # hashing (the value's bit pattern); we use Python's
                # hash() on the underlying value so the interpreter
                # produces consistent (if different) hashes.
                if (
                    isinstance(callee, ast.Name)
                    and callee.id == "hash"
                    and len(args) == 1
                ):
                    arg_params = list(args)
                    value = self.evaluate_expression(module, arg_params[0])
                    return self._hash_value(value)
                if isinstance(callee, ast.ImplicitEnumVariant):
                    variant_name = callee.variant_name
                    search_scopes = [module.names]
                    for val in module.names.values():
                        if isinstance(val, ast.Import):
                            try:
                                search_scopes.append(
                                    self._resolve_import(module, val).names
                                )
                            except Exception:
                                pass
                    for scope in search_scopes:
                        for _, val in scope.items():
                            if (
                                isinstance(val, type)
                                and hasattr(val, "variants")
                                and variant_name in val.variants
                            ):
                                vinfo = val.variants[variant_name]
                                evaled = [
                                    self.evaluate_expression(module, a) for a in args
                                ]
                                fields = {f.id: v for f, v in zip(vinfo.fields, evaled)}
                                return types.EnumValue(val, variant_name, fields)
                    raise ValueError(f"No enum found with variant .{variant_name}")
                func = self.evaluate_expression(module, callee)
                args = [self.evaluate_expression(module, arg) for arg in args]
                return self.call_function(module, func, args)
            case ast.GenericInstantiation(name, type_args):
                template = self.lookup(module, name)
                return template.instantiate(tuple(type_args))
            case ast.ImplicitEnumVariant(variant_name):
                search_scopes = [module.names]
                for val in module.names.values():
                    if isinstance(val, ast.Import):
                        try:
                            search_scopes.append(
                                self._resolve_import(module, val).names
                            )
                        except Exception:
                            pass
                for scope in search_scopes:
                    for name_, val in scope.items():
                        if (
                            isinstance(val, type)
                            and hasattr(val, "variants")
                            and variant_name in val.variants
                        ):
                            variant_info = val.variants[variant_name]
                            if not variant_info.fields:
                                return types.EnumValue(val, variant_name, {})
                            raise ValueError(
                                f"Implicit enum variant .{variant_name} has payload fields; use explicit syntax"
                            )
                raise ValueError(f"No enum found with variant .{variant_name}")
            case ast.StringSlice(string, start, end):
                s = self.evaluate_expression(module, string)
                i = self.evaluate_expression(module, start)
                j = self.evaluate_expression(module, end)
                return types.String(s.value[i.value : j.value])
            case ast.MatchExpression(subject, arms):
                value = self.evaluate_expression(module, subject)
                for arm in arms:
                    if isinstance(arm.pattern, ast.IntegerPattern):
                        if value.value == arm.pattern.value:
                            return self.evaluate_expression(module, arm.body)
                    elif isinstance(arm.pattern, ast.StringPattern):
                        if value.to_py_str() == arm.pattern.value:
                            return self.evaluate_expression(module, arm.body)
                    elif isinstance(arm.pattern, ast.WildcardPattern):
                        return self.evaluate_expression(module, arm.body)
                    elif isinstance(arm.pattern, ast.OptionalNonePattern):
                        if isinstance(value, types.NoneType):
                            return self.evaluate_expression(module, arm.body)
                    elif isinstance(arm.pattern, ast.OptionalSomePattern):
                        if not isinstance(value, types.NoneType):
                            if arm.pattern.binding:
                                self.stack[-1][arm.pattern.binding] = value
                            return self.evaluate_expression(module, arm.body)
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
                            return self.evaluate_expression(module, arm.body)
                raise ValueError("Non-exhaustive match expression")
            case _:
                raise ValueError(
                    f"Don't know how to evaluate expression {expression!r}"
                )

    def execute_statement(self, module, statement):
        """Execute a statement"""
        match statement:
            case ast.Return(expression):
                value = self.evaluate_expression(module, expression)
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
                callee = self.evaluate_expression(module, statement.callee)
                args = list(
                    map(partial(self.evaluate_expression, module), statement.args)
                )
                self.call_function(module, callee, args)
            case ast.VariableDeclaration(variable, value, _span, mutable):
                lhs = self.evaluate_expression(module, variable, as_lvalue=True)
                value = self.evaluate_expression(module, value)
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
                if hasattr(type_, "methods"):
                    for method in type_.methods.values():
                        method.module = module
            case ast.Assignment(lhs, rhs):
                rhs_val = self.evaluate_expression(module, rhs)
                if isinstance(lhs, ast.BinaryOperator) and isinstance(
                    lhs.op, tokens.Dot
                ):
                    obj = self.evaluate_expression(module, lhs.lhs)
                    setattr(obj, lhs.rhs.id, rhs_val)
                elif isinstance(lhs, ast.BinaryOperator) and isinstance(
                    lhs.op, tokens.OpenBracket
                ):
                    obj = self.evaluate_expression(module, lhs.lhs)
                    key_val = self.evaluate_expression(module, lhs.rhs)
                    struct_methods = getattr(type(obj), "methods", {})
                    if "op_index_set" in struct_methods:
                        self.call_function(
                            module,
                            BoundMethod(struct_methods["op_index_set"], obj),
                            [key_val, rhs_val],
                        )
                    else:
                        obj.value[key_val.value] = rhs_val
                else:
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
                for element in array.value:
                    self.stack[-1][binding] = element
                    try:
                        for stmt in body:
                            self.execute_statement(module, stmt)
                    except BreakSignal:
                        break
                    except ContinueSignal:
                        continue
            case ast.MatchStatement(expression, arms):
                value = self.evaluate_expression(module, expression)
                for arm in arms:
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
                if not matched:
                    for stmt in else_body:
                        self.execute_statement(module, stmt)
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
        path. Bytes/int/bool participate in value equality; everything
        else falls back to identity (matches the compiled side's pointer
        equality for non-interned structured keys)."""
        if isinstance(value, types.String):
            return ("str", value.value)
        if isinstance(value, types.Int64):
            return ("int", value.value)
        if isinstance(value, types.Bool):
            return ("bool", value.value)
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
        """Hash a Kod value to an int64. Used to implement the `hash(x)`
        intrinsic. Content-based for primitives; pointer-id for anything
        else (matches the compiled-side identity hash for non-interned
        struct keys)."""
        if isinstance(value, types.Int64):
            return types.Int64(value.value)
        if isinstance(value, types.Bool):
            return types.Int64(1 if value.value else 0)
        if isinstance(value, types.String):
            return types.Int64(hash(value.value))
        return types.Int64(id(value))

    def _coerce_to_str(self, module, value):
        """Convert a value to a Kod `str`. Used to implement the `str(x)`
        intrinsic: int → decimal, bool → "true"/"false", str → identity,
        struct with `to_str` method → call that method."""
        if isinstance(value, types.String):
            return value
        if isinstance(value, types.Int64):
            return types.String(str(value.value).encode("utf8"))
        if isinstance(value, types.Bool):
            return types.String(b"true" if value.value else b"false")
        methods = getattr(type(value), "methods", None) or {}
        if "to_str" in methods:
            return self.call_function(module, methods["to_str"], (value,))
        return types.String(str(value).encode("utf8"))

    def call_function(self, module, func, args=()):
        """Call a function"""
        if callable(func):
            if isinstance(func, type) and issubclass(func, types.StructType):
                arg_names = [field.name for field in dataclasses.fields(func)]
                kwargs = {name: value for name, value in zip(arg_names, args)}
                # Fill any field the construction omitted with its default
                # expression. struct_fields carries the ast.Variable for
                # each field, with `.default` set when declared `= expr`.
                for v in getattr(func, "struct_fields", []):
                    if v.id not in kwargs and v.default is not None:
                        kwargs[v.id] = self.evaluate_expression(module, v.default)
                return func(**kwargs)
            return func(*args)
        if isinstance(func, ast.ExternalFunctionDeclaration):
            if func.name == "read_file":
                path = args[0].value.decode("utf8")
                try:
                    return types.String(open(path, "rb").read())
                except OSError:
                    return types.String(b"")
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

        if (
            isinstance(func, ast.FunctionDeclaration)
            and func.name == "len"
            and len(args) == 1
            and isinstance(args[0], types.ArrayType)
        ):
            return types.Int64(len(args[0].value))
        if (
            isinstance(func, ast.FunctionDeclaration)
            and func.name == "len"
            and len(args) == 1
            and isinstance(args[0], types.String)
        ):
            # str's `len` used to live in builtins.kod as a wrapper
            # around the libc strlen extern. The compile path now reads
            # the str struct's header directly; we mirror it here so
            # the interpreter doesn't fall back to a vanished function.
            return types.Int64(len(args[0].value))

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
            explicit_params = list(func.params)[1:]  # skip self
            frame = {
                param.variable.id: (
                    self.lookup(module, arg) if isinstance(arg, ast.Variable) else arg
                )
                for param, arg in zip(explicit_params, args)
            }
            frame["self"] = receiver
            self.stack.append(frame)
            self.immutable_stack.append(set())
            try:
                for statement in func.body:
                    self.execute_statement(func.module, statement)
            except ReturnValue as return_value:
                return return_value.value
            finally:
                self.stack.pop()
                self.immutable_stack.pop()
            return None

        # Map args to params
        args = {
            param.variable.id: (
                self.lookup(module, arg) if isinstance(arg, ast.Variable) else arg
            )
            for param, arg in zip(func.params, args)
        }
        self.stack.append(args)
        self.immutable_stack.append(set())
        try:
            for statement in func.body:
                self.execute_statement(func.module, statement)
        except ReturnValue as return_value:
            return return_value.value
        finally:
            self.stack.pop()
            self.immutable_stack.pop()
