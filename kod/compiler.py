#!/usr/bin/env python
"""An assembler for the Kod language."""

import collections
import sys

from kod.ast import (
    ParsedAssignment,
    ParsedBooleanLiteral,
    ParsedExternalFunctionDeclaration,
    ParsedFunctionCall,
    ParsedFunctionDeclaration,
    ParsedIfStatement,
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


RETURN_VALUE = object()


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
        self.label_counters = collections.defaultdict(int)

    def create_label(self, base_name):
        """Create a label"""
        self.label_counters[base_name] += 1
        return f"{base_name}${self.label_counters[base_name]}"

    def literal_string(self, s):
        """Return a string constant for the given string"""
        if s.value not in self.strings:
            label = self.create_label("str")
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

    def compile_statement(self, statement):
        """Compile a statement to assembly"""
        match statement:
            case ParsedFunctionCall():
                self.compile_function_call(statement)
            case ParsedVariableDeclaration(variable, value):
                self.compile_variable_declaration(variable, value)
            case ParsedAssignment(variable, value):
                self.compile_variable_declaration(variable, value)
            case ParsedReturn(value):
                self.stack[-1][RETURN_VALUE] = value
            case ParsedIfStatement(condition, true_branch, false_branch):
                self.compile_if_statement(condition, true_branch, false_branch)
            case _:
                raise ValueError(f"Unexpected statement {statement}")

    def compile_function(self, func):
        """Compile a function to assembly"""
        self.emit(".globl", f"_{func.name}")
        print(f"_{func.name}:", file=self.output)
        self.enter_stack_frame(func)
        for statement in func.body:
            self.compile_statement(statement)
        self.leave_stack_frame(func)
        self.functions[func.name] = func

    def _get_stack_frame_size(self, func):
        size = sum(variable.type.width for variable in func.variables.values())
        size += 16 - size % 16
        return size

    def enter_stack_frame(self, func):
        """Emit the prologue for a function"""
        stack_frame_size = self._get_stack_frame_size(func)
        self.emit("sub", "sp", "sp", f"#{stack_frame_size + 16}")
        self.emit("stp", "fp", "lr", f"[sp, #{stack_frame_size}]")
        self.emit("add", "fp", "sp", f"#{stack_frame_size}")
        self.stack.append({variable.id: variable for variable in func.variables.values()})
        if func.params:
            self.move_args_to_stack(func)

    def move_args_to_stack(self, func):
        """Move arguments from registers to the stack"""
        offset = 0
        for param, register in zip(func.params, self._argregs):
            offset -= param.variable.type.width
            self.emit("str", register, f"[fp, #{offset}]")

    def leave_stack_frame(self, func):
        """Emit the epilogue for a function"""
        return_value = self.stack[-1].get(RETURN_VALUE)
        self.stack.pop()
        if return_value is None:
            self.mov("w0", "#0")
        else:
            self.emit("mov", "x0", f"#{return_value.value.value}")
        stack_frame_size = self._get_stack_frame_size(func)
        self.emit("ldp", "fp", "lr", f"[sp, #{stack_frame_size}]")
        self.emit("add", "sp", "sp", f"#{stack_frame_size + 16}")
        self.emit("ret")

    def compile_if_statement(self, condition, true_branch, false_branch):
        """Compile an if statement to assembly"""
        assert isinstance(condition, ParsedBooleanLiteral)
        label_base = self.create_label("if")
        false_label = f"{label_base}$false"
        end_label = f"{label_base}$end"
        self.emit("mov", "w0", f"#{int(condition.value.value)}")
        self.emit("cmp", "w0", "#0")
        self.emit("beq", false_label)
        for statement in true_branch:
            self.compile_statement(statement)
        self.emit("b", end_label)
        self.emit_label(false_label)
        for statement in false_branch:
            self.compile_statement(statement)
        self.emit_label(end_label)

    def compile_variable_declaration(self, variable, value):
        """Compile a variable declaration to assembly"""
        if isinstance(value, ParsedStringLiteral):
            value = self.literal_string(value)
            offset = self.get_variable_offset(variable)
            self.emit("adrp", "x19", f"{value.label}@PAGE")
            self.emit("add", "x19", "x19", f"{value.label}@PAGEOFF")
            self.emit("str", "x19", f"[fp, #{offset}]")
        else:
            raise ValueError(f"Unexpected variable value {variable.value}")

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
                    self.emit("ldr", register, f"[fp, #{offset}]")
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
