#!/usr/bin/env python
"""Simple interpreter for the Kod language"""

import ctypes
import sys

from functools import partial

from kod import ast, tokens, types

libc = ctypes.cdll.LoadLibrary("libSystem.dylib")


class ReturnValue(Exception):
    """Return from a function"""
    def __init__(self, value):
        self.value = value


class Interpreter:
    """Simple interpreter for the Kod language"""

    def __init__(self, program):
        self.program = program
        self.stack = [{}]
        self.builtins_module = self.program.get_module("builtins").module

    def run(self, entry_module_name="main", argv=()):
        """Run the program"""
        for module in self.program.modules.values():
            # fixme: these shouldn't be buildmodules
            module = module.module
            for statement in module.body:
                self.execute_statement(module, statement)
        entry_module_name = self.program.get_module(entry_module_name).module
        main = self.lookup(entry_module_name, "main")
        string_array = types.ArrayType.make(types.String)
        argv = string_array([types.String(arg.encode("utf8")) for arg in argv])
        exit_code = self.call_function(entry_module_name, main, [argv])
        sys.exit(exit_code.value)

    def lookup(self, module, name):
        """Look up a variable in the stack"""
        match name:
            case ast.ParsedVariable() | ast.ParsedName():
                name = name.id
        for frame in self.stack[-1], module.names, self.builtins_module.names:
            if name in frame:
                value = frame[name]
                if isinstance(value, ast.ParsedStringLiteral):
                    value = value.value
                return value
        for statement in module.body:
            match statement:
                case (ast.ParsedExternalFunctionDeclaration()
                      | ast.ParsedFunctionDeclaration()) as func:
                    if func.name == name:
                        return statement
                case ast.ParsedVariableDeclaration(variable, value):
                    if variable.id == name:
                        return value
        raise ValueError(f"Unknown name {name!r}")

    def evaluate_expression(self, module, expression, as_lvalue=False):
        """Resolve an expression"""
        match expression:
            case ast.BinaryOperator(lhs, op, rhs):
                match op:
                    case tokens.Dot():
                        lhs = self.evaluate_expression(module, lhs, as_lvalue)
                        return lhs.names[rhs.value.id]
                    case tokens.OpenBracket():
                        lhs = self.evaluate_expression(module, lhs)
                        rhs = self.evaluate_expression(module, rhs.value)
                        return lhs.op_index(rhs)
                raise ValueError(f"Don't know how to evaluate binary operator {op}")
            case ast.ParsedName() | ast.ParsedVariable() as name:
                return name if as_lvalue else self.lookup(module, name)
            case ast.ParsedStringLiteral(value) | ast.ParsedIntegerLiteral(value):
                return value
            case ast.ParsedExpression(value):
                return self.evaluate_expression(module, value, as_lvalue)
            case ast.ParsedFunctionCallParam() as param:
                return self.evaluate_expression(module, param.expression, as_lvalue)
            case _:
                raise ValueError(f"Don't know how to evaluate expression {expression!r}")

    def execute_statement(self, module, statement):
        """Execute a statement"""
        match statement:
            case ast.ParsedReturn(expression):
                value = self.evaluate_expression(module, expression)
                raise ReturnValue(value)
            case ast.ParsedImport(module_name):
                name = module_name.value.to_py_str()
                module.names[name.lstrip("./")] = self.program.get_module(name).module
            case ast.ParsedFunctionDeclaration(name) | ast.ParsedExternalFunctionDeclaration(name):
                module.names[name] = statement
                statement.module = module
            case ast.ParsedFunctionCall():
                callee = self.evaluate_expression(module, statement.callee)
                args = list(map(partial(self.evaluate_expression, module), statement.args))
                self.call_function(module, callee, args)
            case ast.ParsedVariableDeclaration(variable, value):
                lhs = self.evaluate_expression(module, variable, as_lvalue=True)
                module.names[lhs.id] = self.evaluate_expression(module, value.value)
            case ast.ParsedAssignment(lhs, rhs):
                lhs = self.evaluate_expression(module, lhs, as_lvalue=True)
                module.names[lhs.id] = self.evaluate_expression(module, rhs.value)
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
        if isinstance(func, ast.ParsedExternalFunctionDeclaration):
            c_func = getattr(libc, func.name)
            c_func.argtypes = [self.c_type(p.variable.type) for p in func.params]
            args = [arg.value for arg in args]
            return getattr(libc, func.name)(*args)

        # Map args to params
        args = {
            param.variable.id: (
                self.lookup(module, arg)
                if isinstance(arg, ast.ParsedVariable)
                else arg
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
