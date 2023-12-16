#!/usr/bin/env python
"""Simple interpreter for the Kod language"""

import ctypes

from kod.ast import (
    FunctionDeclaration,
    ExternalFunctionDeclaration,
    FunctionCall,
    StringLiteral,
    Variable,
    VariableDeclaration,
    Assignment,
)

libc = ctypes.cdll.LoadLibrary("libSystem.dylib")


class Interpreter:
    """Simple interpreter for the Kod language"""

    def __init__(self, program):
        self.program = program
        self.stack = [{}]

    def get_builtins(self):
        """Return a dictionary of builtins"""

    def run(self):
        """Run the program"""
        for default_module in ["builtins", "__main"]:
            module = self.program.get_module(default_module)
            for statement in module.ast.body:
                if isinstance(statement, (FunctionDeclaration, ExternalFunctionDeclaration)):
                    self.stack[-1][statement.name] = statement
                else:
                    raise ValueError(f"Unexpected statement {statement}")
        main = self.lookup(Variable("main", None))
        self.call_function(main)

    def lookup(self, variable):
        """Look up a variable in the stack"""
        for frame in reversed(self.stack):
            if variable.id in frame:
                value = frame[variable.id]
                if isinstance(value, StringLiteral):
                    value = value.value
                return value
        raise ValueError(f"Unknown variable {variable!r}")

    def resolve_names(self, args):
        """Resolve variable names to values"""
        return [
            self.lookup(arg) if isinstance(arg, Variable) else arg
            for arg in args
        ]

    def execute_statement(self, statement):
        """Execute a statement"""
        match statement:
            case FunctionCall(callee, args):
                func = self.lookup(callee)
                args = self.resolve_names(args)
                self.call_function(func, args)
            case VariableDeclaration(variable, value):
                self.stack[-1][variable.id] = value
            case Assignment(variable, value):
                self.stack[-1][variable.id] = value
            case _:
                raise ValueError(f"Unexpected statement {statement}")

    def call_function(self, func, args=()):
        """Call a function"""
        if isinstance(func, ExternalFunctionDeclaration):
            return getattr(libc, func.name)(*args)

        # Map args to params
        args = {
            param.id: self.lookup(arg) if isinstance(arg, Variable) else arg
            for param, arg in zip(func.params, args)
        }
        self.stack.append(args)
        for statement in func.body:
            self.execute_statement(statement)
        self.stack.pop()
