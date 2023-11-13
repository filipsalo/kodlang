#!/usr/bin/env python
"""Simple interpreter for the Kod language"""

from kod.parser import (
    FunctionDeclaration,
    ExternalFunctionDeclaration,
    FunctionCall,
    VariableExpr,
)

externals = {
    "strlen": len,
    "write": lambda fd, s, n: print(s)
}


class Interpreter:
    """Simple interpreter for the Kod language"""
    def __init__(self, prog):
        self.prog = prog
        self.stack = [{}]

    def run(self):
        """Run the program"""
        for statement in self.prog:
            if isinstance(statement, FunctionDeclaration):
                self.stack[-1][statement.name] = statement
                # print('stack', self.stack)
            else:
                raise ValueError(f"Unexpected statement {statement}")
        main = self.lookup("main")
        self.call_function(main)

    def lookup(self, variable):
        """Look up a variable in the stack"""
        for frame in reversed(self.stack):
            if variable in frame:
                return frame[variable]
        raise ValueError(f"Unknown variable {variable!r}")

    def resolve_names(self, args):
        """Resolve variable names to values"""
        return [
            self.lookup(arg.name)
            if isinstance(arg, VariableExpr) else arg
            for arg in args]

    def execute_statement(self, statement):
        """Execute a statement"""
        if isinstance(statement, FunctionCall):
            func = self.lookup(statement.callee.name)
            args = self.resolve_names(statement.args)
            self.call_function(func, args)
        else:
            raise ValueError(f"Unexpected statement {statement}")

    def call_function(self, func, args=()):
        """Call a function"""
        self.stack.append({})
        # Map args to params
        for param, arg in zip(func.params, args):
            value = self.lookup(arg) if isinstance(arg, VariableExpr) else arg
            self.stack[-1][param.name] = value
        if isinstance(func, ExternalFunctionDeclaration):
            externals[func.name](*args)
        for statement in func.body:
            self.execute_statement(statement)
        self.stack.pop()
