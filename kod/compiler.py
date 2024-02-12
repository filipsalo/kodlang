#!/usr/bin/env python
"""An assembler for the Kod language."""

import collections
import sys

from kod.ast import (
    BinaryOperator,
    ParsedAssignment,
    ParsedBooleanLiteral,
    ParsedExternalFunctionDeclaration,
    ParsedForStatement,
    ParsedFunctionCall,
    ParsedFunctionDeclaration,
    ParsedIfStatement,
    ParsedIntegerLiteral,
    ParsedName,
    ParsedReturn,
    ParsedStringLiteral,
    ParsedVariableDeclaration,
)
from kod.tokens import GreaterThan, LessThan, Minus, Plus, Slash, Star


class StringConstant:
    """A string constant"""

    def __init__(self, label, value):
        self.label = label
        self.value = value


class Label:
    """A label"""

    def __init__(self, name):
        self.name = name

    def __getattr__(self, name):
        return Label(f"{self.name}${name}")

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"Label({self.name!r})"


class Imm(int):
    """An immediate value"""

    def __str__(self):
        return f"#{int(self)}"


class StackFrame:
    """A stack frame"""

    def __init__(self, variables):
        self.variables = {variable.id: variable for variable in variables}
        self.return_value = None
        self.registers = [
            "x8", "x9", "x10", "x11", "x12", "x13", "x14", "x15",
            # todo: handle the below as non-volatile
            "x19", "x20", "x21", "x22", "x23", "x24", "x25", "x26", "x27", "x28",
        ]

    def declare_variable(self, variable):
        """Declare a variable"""
        self.variables[variable.id] = variable

    def get_variable_address(self, variable):
        """Get the offset of a variable in the stack frame"""
        offset = 0
        for var in self.variables.values():
            offset -= var.type.width
            if var.id == variable.id:
                break
        else:
            raise ValueError(f"Unknown variable {variable!r}")
        return f"[fp, #{offset}]" if offset else "[fp]"

    def size(self):
        """Return the size of the stack frame"""
        return sum(variable.type.width for variable in self.variables.values())

    def aligned_size(self):
        """Return the aligned size of the stack frame"""
        size = self.size()
        return size + 16 - size % 16

    def allocate_register(self):
        """Allocate a register"""
        return self.registers.pop(0)

    def release_register(self, register):
        """Release a register"""
        self.registers.insert(0, register)


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
        return Label(f"{base_name}${self.label_counters[base_name]}")

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
                self.stack[-1].return_value = value
            case ParsedIfStatement(condition, true_branch, false_branch):
                self.compile_if_statement(condition, true_branch, false_branch)
            case ParsedForStatement(condition, body):
                self.compile_for_statement(condition, body)
            case _:
                raise ValueError(f"Unexpected statement {statement}")

    def compile_function(self, func):
        """Compile a function to assembly"""
        self.emit(".globl", f"_{func.name}")
        print(f"_{func.name}:", file=self.output)
        self.enter_stack_frame(func)
        for statement in func.body:
            self.compile_statement(statement)
        self.leave_stack_frame()
        self.functions[func.name] = func

    def enter_stack_frame(self, func):
        """Emit the prologue for a function"""
        frame = StackFrame(func.variables.values())
        self.stack.append(frame)
        self.emit("sub", "sp", "sp", Imm(frame.aligned_size() + 16))
        self.emit("stp", "fp", "lr", f"[sp, #{frame.aligned_size()}]")
        self.emit("add", "fp", "sp", Imm(frame.aligned_size()))
        if func.params:
            self.move_args_to_stack(func)

    def move_args_to_stack(self, func):
        """Move arguments from registers to the stack"""
        offset = 0
        for param, register in zip(func.params, self._argregs):
            offset -= param.variable.type.width
            self.emit("str", register, f"[fp, #{offset}]")

    def leave_stack_frame(self):
        """Emit the epilogue for a function"""
        return_value = self.stack[-1].return_value
        if return_value is None:
            self.mov("w0", Imm(0))
        else:
            addr = self.compile_expression(return_value)
            self.mov("x0", addr)
        frame = self.stack.pop()
        self.emit("ldp", "fp", "lr", f"[sp, #{frame.aligned_size()}]")
        self.emit("add", "sp", "sp", Imm(frame.aligned_size() + 16))
        self.emit("ret")

    def compile_for_statement(self, condition, body):
        """Compile a for statement to assembly"""
        label = self.create_label("for")
        self.emit_label(label.start)
        register = self.compile_expression(condition)
        self.emit("cmp", register, Imm(0))
        self.emit("beq", label.end)
        for statement in body:
            self.compile_statement(statement)
        self.emit("b", label.start)
        self.emit_label(label.end)

    def compile_if_statement(self, condition, true_branch, false_branch):
        """Compile an if statement to assembly"""
        assert isinstance(condition, ParsedBooleanLiteral)
        label = self.create_label("if")
        register = self.stack[-1].allocate_register()
        self.mov(register, Imm(condition.value.value))
        self.emit("cmp", register, Imm(0))
        self.stack[-1].release_register(register)
        self.emit("beq", label.false)
        for statement in true_branch:
            self.compile_statement(statement)
        self.emit("b", label.end)
        self.emit_label(label.false)
        for statement in false_branch:
            self.compile_statement(statement)
        self.emit_label(label.end)

    def compile_variable_declaration(self, variable, expression):
        """Compile a variable declaration to assembly"""
        destination = self.stack[-1].get_variable_address(variable)
        address = self.compile_expression(expression)
        if isinstance(address, (Imm, str)):
            register = self.stack[-1].allocate_register()
            self.mov(register, address)
            self.emit("str", register, destination)
            self.stack[-1].release_register(register)
        else:
            self.emit("str", address, destination)

    def compile_expression(self, expression):
        """Parse an expression"""
        if isinstance(expression, ParsedStringLiteral):
            value = self.literal_string(expression)
            register = self.stack[-1].allocate_register()
            self.emit("adrp", register, f"{value.label}@PAGE")
            self.emit("add", register, register, f"{value.label}@PAGEOFF")
            return register
        elif isinstance(expression, ParsedIntegerLiteral):
            return Imm(expression.value.value)
        elif isinstance(expression, ParsedName):
            return self.stack[-1].get_variable_address(expression)
        elif isinstance(expression, ParsedFunctionCall):
            return self.compile_function_call(expression)
        elif isinstance(expression, BinaryOperator):
            return self.compile_binary_operator(expression)
        else:
            raise ValueError(f"Unexpected expression {expression}")

    def compile_binary_operator(self, expression):
        """Compile a binary operator to assembly"""
        if not isinstance(expression.op, (Plus, Minus, Slash, Star, LessThan, GreaterThan)):
            raise ValueError(f"Unknown operator: {expression.op}")
        left = self.compile_expression(expression.lhs)
        right = self.compile_expression(expression.rhs)
        try:
            lhs_register = self.stack[-1].allocate_register()
            rhs_register = self.stack[-1].allocate_register()
            self.mov(lhs_register, left)
            self.mov(rhs_register, right)
            if isinstance(expression.op, (LessThan, GreaterThan)):
                self.emit("cmp", lhs_register, rhs_register)
                op = {LessThan: "lt", GreaterThan: "gt"}[type(expression.op)]
                self.emit("cset", lhs_register, op)
            else:
                op = {Plus: "add", Minus: "sub", Slash: "sdiv", Star: "mul"}[type(expression.op)]
                self.emit(op, lhs_register, lhs_register, rhs_register)
            self.stack[-1].release_register(rhs_register)
            return lhs_register
        finally:
            if isinstance(left, str) and left[0] == "x":
                self.stack[-1].release_register(left)
            if isinstance(right, str) and right[0] == "x":
                self.stack[-1].release_register(right)

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
        return "x0"

    def prepare_args(self, func, args):
        """Prepare arguments for a function call"""
        offset = 0
        for param, arg, arg_register in zip(func.params, args, self._argregs):
            offset -= param.variable.type.width
            register = self.compile_expression(arg.expression)
            self.mov(arg_register, register)

    def mov(self, dest, src):
        """Move a value"""
        if isinstance(src, str) and src.startswith("["):
            self.emit("ldr", dest, src)
        else:
            self.emit("mov", dest, src)
