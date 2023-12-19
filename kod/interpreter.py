#!/usr/bin/env python
"""Simple interpreter for the Kod language"""

import ctypes

from kod.ast import (
    ParsedFunctionDeclaration,
    ParsedExternalFunctionDeclaration,
    ParsedFunctionCall,
    ParsedImport,
    ParsedStringLiteral,
    ParsedVariable,
    ParsedVariableDeclaration,
    ParsedAssignment,
)

libc = ctypes.cdll.LoadLibrary("libSystem.dylib")


class Interpreter:
    """Simple interpreter for the Kod language"""

    def __init__(self, program):
        self.program = program
        self.stack = [{}]

    def get_builtins(self):
        """Return a dictionary of builtins"""

    def run(self, entry_module="main"):
        """Run the program"""
        for default_module in ["builtins", entry_module]:
            module = self.program.get_module(default_module).module
            for statement in module.body:
                if isinstance(statement, (ParsedFunctionDeclaration, ParsedExternalFunctionDeclaration)):
                    self.stack[-1][statement.name] = statement
                elif isinstance(statement, ParsedImport):
                    name = statement.module_name.value.decode("ascii")
                    self.stack[0][name] = self.program.get_module(name).module
                elif isinstance(statement, ParsedVariableDeclaration):
                    self.stack[-1][statement.variable.id] = statement.value
                else:
                    raise ValueError(f"Unexpected statement {statement}")
        main = self.lookup(entry_module, "main")
        self.call_function(entry_module, main)

    def lookup(self, module, name):
        """Look up a variable in the stack"""
        if isinstance(name, ParsedVariable):
            name = name.id
        for frame in self.stack[-1], self.stack[0]:
            if name in frame:
                value = frame[name]
                if isinstance(value, ParsedStringLiteral):
                    value = value.value
                return value
        for statement in module:
            if isinstance(statement, (ParsedExternalFunctionDeclaration, ParsedFunctionDeclaration)):
                if statement.name == name:
                    return statement
            if isinstance(statement, ParsedVariableDeclaration):
                if statement.variable.id == name:
                    return statement.value
        raise ValueError(f"Unknown name {name!r}")

    def resolve_names(self, module, args):
        """Resolve variable names to values"""
        return [
            self.lookup(module, arg.expression)
            if isinstance(arg.expression, ParsedVariable)
            else arg.expression
            for arg in args
        ]

    def execute_statement(self, module, statement):
        """Execute a statement"""
        match statement:
            case ParsedFunctionCall(callee, args):
                func = self.lookup(module, callee)
                args = self.resolve_names(module, args)
                self.call_function(module, func, args)
            case ParsedVariableDeclaration(variable, value):
                self.stack[-1][variable.id] = value
            case ParsedAssignment(variable, value):
                self.stack[-1][variable.id] = value
            case _:
                raise ValueError(f"Unexpected statement {statement}")

    def call_function(self, module, func, args=()):
        """Call a function"""
        if isinstance(func, ParsedExternalFunctionDeclaration):
            return getattr(libc, func.name)(*args)

        # Map args to params
        args = {
            param.variable.id: self.lookup(module, arg) if isinstance(arg, ParsedVariable) else arg
            for param, arg in zip(func.params, args)
        }
        self.stack.append(args)
        for statement in func.body:
            self.execute_statement(module, statement)
        self.stack.pop()
