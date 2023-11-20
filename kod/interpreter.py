#!/usr/bin/env python
"""Simple interpreter for the Kod language"""

from kod.ast import (
    FunctionDeclaration,
    ExternalFunctionDeclaration,
    FunctionCall,
    StringLiteral,
    Variable,
)

externals = {"puts": print}


class Interpreter:
    """Simple interpreter for the Kod language"""

    def __init__(self, prog):
        self.prog = prog
        self.stack = [{}]

    def run(self):
        """Run the program"""
        for statement in self.prog.body:
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
        if isinstance(statement, FunctionCall):
            func = self.lookup(statement.callee)
            args = self.resolve_names(statement.args)
            self.call_function(func, args)
        else:
            raise ValueError(f"Unexpected statement {statement}")

    def call_function(self, func, args=()):
        """Call a function"""
        # Map args to params
        args = {
            param.name.id: self.lookup(arg) if isinstance(arg, Variable) else arg
            for param, arg in zip(func.params, args)
        }
        if isinstance(func, ExternalFunctionDeclaration):
            externals[func.name](*args.values())
        for statement in func.body:
            self.stack.append(args)
            self.execute_statement(statement)
        self.stack.pop()
