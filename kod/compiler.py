#!/usr/bin/env python
"""An assembler for the Kod language."""

import sys

from kod.parser import (
    Assignment,
    ExternalFunctionDeclaration,
    FunctionCall,
    FunctionDeclaration,
    StringLiteral,
    Variable,
    VariableDeclaration,
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

    def __init__(self, module, builtins, output=sys.stdout):
        self.module = module
        self.builtins = builtins
        self.output = output
        self.functions = {}
        self.strings = {}
        self.stack = []

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
        for statement in self.builtins.ast.body:
            match statement:
                case ExternalFunctionDeclaration(name) | FunctionDeclaration(name):
                    self.functions[name] = statement

        for statement in self.module.ast.body:
            match statement:
                case ExternalFunctionDeclaration(name):
                    self.functions[name] = statement
                case FunctionDeclaration():
                    self.compile_function(statement)
                case _:
                    raise ValueError(f"Unexpected statement {statement}")
        self.emit(".data")
        for string in self.strings.values():
            print(f"{string.label}:", file=self.output)
            print(f'\t.asciz "{string.value.decode()}"', file=self.output)

    def compile_function(self, func):
        """Compile a function to assembly"""
        self.emit(".globl", f"_{func.name}")
        print(f"_{func.name}:", file=self.output)
        self.enter_stack_frame(func)
        self.stack.append({variable.id: variable for variable in func.variables})
        for statement in func.body:
            match statement:
                case FunctionCall():
                    self.compile_function_call(statement)
                case VariableDeclaration(variable, value):
                    self.compile_variable_declaration(variable, value)
                case Assignment(variable, value):
                    self.compile_variable_declaration(variable, value)
                case _:
                    raise ValueError(f"Unexpected statement {statement}")
        self.stack.pop()
        self.leave_stack_frame(func)
        self.functions[func.name] = func

    def _get_stack_frame_size(self, func):
        return sum(variable.type.width for variable in func.variables)

    def enter_stack_frame(self, func):
        """Emit the prologue for a function"""
        self.push("%rbp")
        self.mov("%rsp", "%rbp")
        if stack_frame_size := self._get_stack_frame_size(func):
            self.sub(f"${stack_frame_size}", "%rsp")
            if func.params:
                self.move_args_to_stack(func)

    def compile_variable_declaration(self, variable, value):
        """Compile a variable declaration to assembly"""
        if isinstance(value, StringLiteral):
            value = self.literal_string(value)
            offset = self.get_variable_offset(variable)
            self.lea(f"{value.label}(%rip)", "%rax")
            self.mov("%rax", f"{offset}(%rbp)")
        else:
            raise ValueError(f"Unexpected variable value {variable.value}")

    def compile_assignment(self, variable, value):
        """Compile an assignment to assembly"""
        if isinstance(value, StringLiteral):
            value = self.literal_string(value)
            offset = self.get_variable_offset(variable)
            self.lea(f"{value.label}(%rip)", "%rax")
            self.mov("%rax", f"{offset}(%rbp)")
        else:
            raise ValueError(f"Unexpected variable value {variable.value}")

    def move_args_to_stack(self, func):
        """Move arguments from registers to the stack"""
        offset = 0
        for param, register in zip(func.params, self._argregs):
            offset -= param.variable.type.width
            self.mov(f"%{register}", f"{offset}(%rbp)", size=param.variable.type.width)

    def leave_stack_frame(self, func):
        """Emit the epilogue for a function"""
        if stack_frame_size := self._get_stack_frame_size(func):
            self.add(f"${stack_frame_size}", "%rsp")
        self.mov("$0", "%rax")
        self.pop("%rbp")
        self.emit("ret")

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
        self.emit("callq", f"_{func.name}")

    def prepare_args(self, func, args):
        """Prepare arguments for a function call"""
        offset = 0
        for param, arg, register in zip(func.params, args, self._argregs):
            offset -= param.variable.type.width
            if isinstance(arg.expression, StringLiteral):
                arg = self.literal_string(arg.expression)
                self.lea(f"{arg.label}(%rip)", f"%{register}")
            elif isinstance(arg.expression, Variable):
                offset = self.get_variable_offset(arg.expression)
                if offset:
                    self.mov(f"{offset}(%rbp)", f"%{register}")
            else:
                self.mov(f"${arg.expression}", f"%{register}")

    def get_variable_offset(self, variable):
        """Get the offset of a variable in the stack frame"""
        offset = 0
        for var in self.stack[-1].values():
            offset -= var.type.width
            if var.id == variable.id:
                return offset
        raise ValueError(f"Unknown variable {variable!r}")

    def emit_sized(self, op, size, *args, comment=None):
        """Emit an instruction with a size suffix"""
        size = {8: "q", 4: "l", 2: "w", 1: "b"}[size]
        self.emit(f"{op}{size}", *args, comment=comment)

    def mov(self, src, dest, size=8, comment=None):
        """Move a value"""
        self.emit_sized("mov", size, src, dest, comment=comment)

    def lea(self, src, dest, size=8, comment=None):
        """Load the effective address"""
        self.emit_sized("lea", size, src, dest, comment=comment)

    def push(self, src, size=8, comment=None):
        """Push a value onto the stack"""
        self.emit_sized("push", size, src, comment=comment)

    def pop(self, dest, size=8, comment=None):
        """Pop a value from the stack"""
        self.emit_sized("pop", size, dest, comment=comment)

    def sub(self, src, dest, size=8, comment=None):
        """Subtract a value from another value"""
        self.emit_sized("sub", size, src, dest, comment=comment)

    def add(self, src, dest, size=8, comment=None):
        """Add a value to another value"""""
        self.emit_sized("add", size, src, dest, comment=comment)
