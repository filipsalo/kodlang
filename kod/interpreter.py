#!/usr/bin/env python
"""Simple interpreter for the Kod language"""

import ctypes
import dataclasses
import sys
from functools import partial
from pathlib import Path
from typing import Any

from kod import ast, tokens, types
from kod.program import Program

libc = ctypes.cdll.LoadLibrary("libSystem.dylib")


class ReturnValue(Exception):
    """Return from a function"""

    def __init__(self, value):
        self.value = value


class Interpreter:
    """Simple interpreter for the Kod language"""

    def __init__(self, program: Program):
        self.program = program
        self.stack = [{}]

    def run(self, file, argv=()):
        """Run the program"""
        for module in self.program:
            for statement in module.body:
                self.execute_statement(module, statement)
        entry_module = self.program.get_module(file.canonical_path.with_suffix(""))
        main = self.lookup(entry_module, "main")
        string_array = types.ArrayType.make(types.String)
        argv = string_array([types.String(arg.encode("utf8")) for arg in argv])
        exit_code = self.call_function(entry_module, main, [argv])
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
                    path = module.source_file.path.parent / Path(value.module_name)
                    path = path.relative_to(module.source_file.fs.root_path)
                    return self.program.get_module(path)
                return value
        raise ValueError(f"Unknown name {name!r}")

    def evaluate_binary_operator(self, module, op, lhs, rhs, as_lvalue=False):
        """Evaluate a binary operator"""
        match op:
            case tokens.Dot():
                lhs = self.evaluate_expression(module, lhs, as_lvalue)
                if isinstance(lhs, ast.Module):
                    return lhs.names[rhs.id]
                return getattr(lhs, rhs.id)
            case tokens.OpenBracket():
                op_func_name = "op_index"
            case tokens.Plus():
                op_func_name = "op_plus"
            case tokens.Minus():
                op_func_name = "op_minus"
            case tokens.LessThan():
                op_func_name = "op_lt"
            case tokens.GreaterThan():
                op_func_name = "op_gt"
            case tokens.EqualEqual():
                op_func_name = "op_eq"
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
            case types.Type() as instance:
                return instance
            case ast.BinaryOperator(lhs, op, rhs):
                return self.evaluate_binary_operator(module, op, lhs, rhs, as_lvalue)
            case ast.Name() | ast.Variable() as name:
                return name if as_lvalue else self.lookup(module, name)
            case ast.Literal(value):
                return value
            case ast.Expression(value):
                return self.evaluate_expression(module, value, as_lvalue)
            case ast.FunctionCallParam() as param:
                return self.evaluate_expression(module, param.expression, as_lvalue)
            case ast.FunctionCall(callee, args):
                func = self.evaluate_expression(module, callee)
                args = [self.evaluate_expression(module, arg) for arg in args]
                return self.call_function(module, func, args)
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
            case ast.Import(name, local_name):
                path = module.source_file.path.parent / Path(name)
                path = path.relative_to(module.source_file.fs.root_path)
                module.names[local_name] = self.program.get_module(path)
            case ast.FunctionDeclaration(name) | ast.ExternalFunctionDeclaration(name):
                module.names[name] = statement
                setattr(statement, "module", module)
            case ast.FunctionCall():
                callee = self.evaluate_expression(module, statement.callee)
                args = list(
                    map(partial(self.evaluate_expression, module), statement.args)
                )
                self.call_function(module, callee, args)
            case ast.VariableDeclaration(variable, value):
                lhs = self.evaluate_expression(module, variable, as_lvalue=True)
                value = self.evaluate_expression(module, value)
                if len(self.stack) > 1:
                    self.stack[-1][lhs.id] = self.evaluate_expression(module, value)
                else:
                    module.names[lhs.id] = self.evaluate_expression(module, value)
            case ast.TypeDeclaration(variable, value):
                lhs = self.evaluate_expression(module, variable, as_lvalue=True)
                value = self.evaluate_expression(module, value)
                module.names[lhs.id] = self.evaluate_expression(module, value)
            case ast.Assignment(lhs, rhs):
                rhs_val = self.evaluate_expression(module, rhs)
                if isinstance(lhs, ast.BinaryOperator) and isinstance(
                    lhs.op, tokens.Dot
                ):
                    obj = self.evaluate_expression(module, lhs.lhs)
                    setattr(obj, lhs.rhs.id, rhs_val)
                else:
                    lhs_val = self.evaluate_expression(module, lhs, as_lvalue=True)
                    self.assign(module, lhs_val.id, rhs_val)
            case ast.IfStatement(condition, true_branch, false_branch):
                matched = (
                    self.evaluate_expression(module, condition).to_bool().value is True
                )
                for statement in true_branch if matched else false_branch:
                    self.execute_statement(module, statement)
            case ast.ForStatement(condition, body):
                while (
                    self.evaluate_expression(module, condition).to_bool().value is True
                ):
                    for stmt in body:
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

    def call_function(self, module, func, args=()):
        """Call a function"""
        if callable(func):
            if isinstance(func, type) and issubclass(func, types.StructType):
                arg_names = [field.name for field in dataclasses.fields(func)]
                return func(**{name: value for name, value in zip(arg_names, args)})
            return func(*args)
        if isinstance(func, ast.ExternalFunctionDeclaration):
            c_func = getattr(libc, func.name)
            c_func.argtypes = [self.c_type(p.variable.type) for p in func.params]
            args = [arg.value for arg in args]
            return getattr(libc, func.name)(*args)

        # Map args to params
        args = {
            param.variable.id: (
                self.lookup(module, arg) if isinstance(arg, ast.Variable) else arg
            )
            for param, arg in zip(func.params, args)
        }
        self.stack.append(args)
        try:
            for statement in func.body:
                self.execute_statement(func.module, statement)
        except ReturnValue as return_value:
            return return_value.value
        finally:
            self.stack.pop()
