#!/usr/bin/env python
"""An assembler for the Kod language."""

import sys

from kod import tokens
from kod.ast import (
    BinaryOperator,
    ParsedAssignment,
    ParsedExternalFunctionDeclaration,
    ParsedFunctionCall,
    ParsedFunctionDeclaration,
    ParsedIntegerLiteral,
    ParsedName,
    ParsedReturn,
    ParsedStringLiteral,
    ParsedVariableDeclaration,
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

    _argregs = ["x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7"]

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
        for statement in self.builtins.body:
            match statement:
                case ParsedExternalFunctionDeclaration(name) | ParsedFunctionDeclaration(name):
                    self.functions[name] = statement

        for statement in self.module.body:
            match statement:
                case ParsedExternalFunctionDeclaration(name):
                    self.functions[name] = statement
                case ParsedFunctionDeclaration():
                    self.compile_function(statement)
                case _:
                    raise ValueError(f"Unexpected statement {statement}")
        self.emit("\n.data")
        for string in self.strings.values():
            print(f"{string.label}:", file=self.output)
            print(f'\t.asciz "{string.value.value.decode()}"', file=self.output)

    def compile_function(self, func):
        """Compile a function to assembly"""
        self.emit(".globl", f"_{func.name}")
        print(f"_{func.name}:", file=self.output)
        self.enter_stack_frame(func)
        self.stack.append({variable.id: variable for variable in func.variables.values()})
        return_value = None
        for statement in func.body:
            match statement:
                case ParsedFunctionCall():
                    self.compile_function_call(statement)
                case ParsedVariableDeclaration(variable, value):
                    self.compile_variable_declaration(variable, value)
                case ParsedAssignment(variable, value):
                    self.compile_variable_declaration(variable, value)
                case ParsedReturn(value):
                    return_value = value
                case _:
                    raise ValueError(f"Unexpected statement {statement}")
        self.stack.pop()
        self.leave_stack_frame(func, return_value)
        self.functions[func.name] = func

    def _get_stack_frame_size(self, func):
        size = sum(variable.type.width for variable in func.variables.values())
        size += 16 - size % 16
        return size

    def enter_stack_frame(self, func):
        """Emit the prologue for a function"""
        stack_frame_size = self._get_stack_frame_size(func)
        self.emit("sub", "sp", "sp", f"#{stack_frame_size + 16}")
        self.emit("stp", "x29", "x30", f"[sp, #{stack_frame_size}]")
        self.emit("add", "x29", "sp", f"#{stack_frame_size}")
        if func.params:
            self.move_args_to_stack(func)

    def compile_variable_declaration(self, variable, value):
        """Compile a variable declaration to assembly"""
        if isinstance(value, ParsedStringLiteral):
            value = self.literal_string(value)
            offset = self.get_variable_offset(variable)
            self.emit("adrp", "x19", f"{value.label}@PAGE")
            self.emit("add", "x19", "x19", f"{value.label}@PAGEOFF")
            self.emit("str", "x19", f"[x29, #{offset}]")
        else:
            raise ValueError(f"Unexpected variable value {variable.value}")

    def move_args_to_stack(self, func):
        """Move arguments from registers to the stack"""
        offset = 0
        for param, register in zip(func.params, self._argregs):
            offset -= param.variable.type.width
            self.emit("str", register, f"[x29, #{offset}]")

    def leave_stack_frame(self, func, return_value):
        """Emit the epilogue for a function"""
        if return_value is None:
            self.mov("w0", "#0")
        else:
            self.emit("mov", "x0", f"#{return_value.value.value}")
        stack_frame_size = self._get_stack_frame_size(func)
        self.emit("ldp", "x29", "x30", f"[sp, #{stack_frame_size}]")
        self.emit("add", "sp", "sp", f"#{stack_frame_size + 16}")
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
        match func_call.callee:
            case ParsedName(id_):
                func = self.functions[id_]
            case _:
                raise ValueError(f"Unexpected function call {func_call.callee}")
        self.prepare_args(func, func_call.args)
        self.emit("bl", f"_{func.name}")

    def prepare_args(self, func, args):
        """Prepare arguments for a function call"""
        offset = 0
        for param, arg, register in zip(func.params, args, self._argregs):
            offset -= param.variable.type.width
            if isinstance(arg.expression, ParsedStringLiteral):
                arg = self.literal_string(arg.expression)
                self.emit("adrp", register, f"{arg.label}@PAGE")
                self.emit("add", register, register, f"{arg.label}@PAGEOFF")
            elif isinstance(arg.expression, ParsedIntegerLiteral):
                self.emit("mov", register, f"#{arg.expression.value.value}")
            elif isinstance(arg.expression, ParsedName):
                offset = self.get_variable_offset(arg.expression)
                if offset:
                    self.emit("ldr", register, f"[x29, #{offset}]")
            elif isinstance(arg.expression, ParsedFunctionCall):
                self.compile_function_call(arg.expression)
                self.mov("x0", {register})
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

    def mov(self, dest, src):
        """Move a value"""
        self.emit("mov", dest, src)
