#!/usr/bin/env python
"""An assembler for the Kod language."""

import sys
from kod.parser import (
    ExternalFunctionDeclaration,
    FunctionDeclaration,
    FunctionCall,
    Name,
    StringLiteral,
)


class StringConstant:
    """A string constant"""

    def __init__(self, label, value):
        self.label = label
        self.value = value


class CompiledFunction:
    """A compiled function"""

    def __init__(self, name, params):
        self.name = name
        self.params = params
        self.locals = []


class Compiler:
    """An assembler for the Kod language."""

    _argregs = ["rdi", "rsi", "rdx", "rcx", "r8", "r9"]

    def __init__(self, program, output=sys.stdout):
        self.program = program
        self.output = output
        self.functions = {}
        self.strings = {}

    def literal_string(self, s, label=None):
        """Return a string constant for the given string"""
        if not label:
            label = f"s${len(self.strings)}"
        if s.value not in self.strings:
            self.strings[s.value] = StringConstant(label, s.value)
        return self.strings[s.value]

    def compile(self):
        """Compile the program to assembly"""
        self.emit(".text")
        self.emit(".globl", "_main")
        for statement in self.program.body:
            if isinstance(statement, ExternalFunctionDeclaration):
                self.functions[statement.name] = statement
            elif isinstance(statement, FunctionDeclaration):
                self.compile_function(statement)
            else:
                raise ValueError(f"Unexpected statement {statement}")
        self.emit(".data")
        for string in self.strings.values():
            print(f"{string.label}:", file=self.output)
            print(f'\t.asciz "{string.value}"', file=self.output)

    def compile_function(self, func):
        """Compile a function to assembly"""
        print(f"_{func.name}:", file=self.output)
        self.enter_stack_frame(func)
        for statement in func.body:
            if isinstance(statement, FunctionCall):
                self.compile_function_call(statement)
            else:
                raise ValueError(f"Unexpected statement {statement}")
        self.leave_stack_frame(func)
        self.functions[func.name] = func

    def _get_stack_frame_size(self, params):
        return sum(param.type.width for param in params)

    def enter_stack_frame(self, func):
        """Emit the prologue for a function"""
        self.emit("pushq", "%rbp")
        self.emit("movq", "%rsp", "%rbp")
        if func.params:
            self.move_args_to_stack(func)

    def move_args_to_stack(self, func):
        """Move arguments from registers to the stack"""
        stack_frame_size = self._get_stack_frame_size(func.params)
        self.emit("subq", f"${stack_frame_size}", "%rsp")
        offset = 0
        for param, register in zip(func.params, self._argregs):
            offset -= param.type.width
            self.emit("movq", f"%{register}", f"{offset}(%rbp)")

    def leave_stack_frame(self, func):
        """Emit the epilogue for a function"""
        if stack_frame_size := self._get_stack_frame_size(func.params):
            self.emit("addq", f"${stack_frame_size}", "%rsp")
        self.emit("popq", "%rbp")
        self.emit("ret")

    def emit_comment(self, comment):
        """Emit a comment"""
        self.emit("##", comment)

    def emit_label(self, label):
        """Emit a label"""
        print(f"{label}:", file=self.output)

    def emit(self, op, *args, comment=None):
        """Emit an instruction"""
        print(f"\t{op}", end="", file=self.output)
        if args:
            args = ", ".join(str(arg) for arg in args)
            print(f"\t{args}", end="", file=self.output)
        if comment:
            print(f"\t# {comment}", end="", file=self.output)
        print(file=self.output)

    def compile_function_call(self, func_call):
        """Compile a function call to assembly"""
        func = self.functions[func_call.callee.id]
        self.prepare_args(func, func_call.args)
        print(f"\tcallq\t_{func.name}", file=self.output)

    def prepare_args(self, func, args):
        """Prepare arguments for a function call"""
        offset = 0
        for param, arg, register in zip(func.params, args, self._argregs):
            offset -= param.type.width
            if isinstance(arg, StringLiteral):
                arg = self.literal_string(arg)
                self.emit("leaq", f"{arg.label}(%rip)", f"%{register}")
            elif isinstance(arg, Name):
                self.emit("movq", f"{offset}(%rbp)", f"%{register}")
            else:
                self.emit("movq", f"${arg}", f"%{register}")
