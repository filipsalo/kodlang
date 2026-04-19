#!/usr/bin/env python
"""An assembler for the Kod language."""

import collections
import sys

from kod.ast import (
    Assignment,
    BinaryOperator,
    BooleanLiteral,
    EnumVariantPattern,
    ExternalFunctionDeclaration,
    ForStatement,
    FunctionCall,
    FunctionDeclaration,
    IfStatement,
    Import,
    IntegerLiteral,
    MatchStatement,
    Module,
    Name,
    NoneLiteral,
    OptionalNonePattern,
    OptionalSomePattern,
    Return,
    StringLiteral,
    TypeDeclaration,
    VariableDeclaration,
    WildcardPattern,
)
from kod.program import Program
from kod.tokens import (
    And,
    Dot,
    EqualEqual,
    GreaterEqual,
    GreaterThan,
    Is,
    LessEqual,
    LessThan,
    Minus,
    NotEqual,
    Or,
    Plus,
    Slash,
    Star,
)


class StringConstant:
    """A string constant"""

    def __init__(self, label, value):
        self.label = label
        self.value = value


class Operand:
    """An address"""


class Label(Operand):
    """A label"""

    def __init__(self, name):
        self.name = name

    def __getattr__(self, name):
        return Label(f"{self.name}${name}")

    def __str__(self):
        return self.name

    def __repr__(self):
        return f"Label({self.name!r})"


class Imm(Operand):
    """An immediate value"""

    def __init__(self, value: int):
        self.value = value

    def __str__(self):
        return f"#{self.value}"


class Register(Operand):
    """A register"""

    def __init__(self, name: str):
        self.name = name

    def __str__(self):
        return self.name


class StackAddress(Operand):
    """An address on the stack"""

    def __init__(self, offset: int, base: str = "fp"):
        self.offset = offset
        self.base = base

    def __str__(self):
        if not self.offset:
            return f"[{self.base}]"
        return f"[{self.base}, #{self.offset}]"


class StackFrame:
    """A stack frame"""

    def __init__(self, variables, end_label):
        self.variables = {variable.id: variable for variable in variables}
        self.end_label = end_label
        self.return_value = None
        self.registers = [Register(f"x{n}") for n in [*range(8, 16), *range(19, 28)]]

    def declare_variable(self, variable):
        """Declare a variable"""
        self.variables[variable.id] = variable

    def get_variable_address(self, variable):
        """Get the offset of a variable in the stack frame"""
        offset = 0
        for var in self.variables.values():
            width = var.type.width if var.type is not None else 8
            offset -= width
            if var.id == variable.id:
                break
        else:
            raise ValueError(f"Unknown variable {variable!r}")
        return StackAddress(offset, "fp")

    def size(self):
        """Return the size of the stack frame"""
        return sum(
            (v.type.width if v.type is not None else 8) for v in self.variables.values()
        )

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

    _argregs = [*map(Register, ["x0", "x1", "x2", "x3", "x4", "x5", "x6", "x7"])]

    def __init__(self, module: Module, program: Program, output=sys.stdout):
        self.module = module
        self.program = program
        self.output = output
        self.imports: dict[str, Import] = {}
        self.functions = {}
        self.type_registry: dict[str, type] = {}
        self.strings = {}
        self.stack = []
        self.label_counters = collections.defaultdict(int)

    def create_global_label(self, base_name):
        """Create a global label"""
        parts = [
            "",
            *self.module.canonical_name.parent.parts,
            self.module.canonical_name.stem,
            base_name,
        ]
        return Label("$".join(parts))

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
        for statement in self.program.builtins.body:
            match statement:
                case ExternalFunctionDeclaration(name) | FunctionDeclaration(name):
                    self.functions[name] = statement

        # Pre-pass: collect type declarations
        for statement in self.module.body:
            match statement:
                case TypeDeclaration(name, type_):
                    self.type_registry[name.id] = type_

        for statement in self.module.body:
            match statement:
                case ExternalFunctionDeclaration(name):
                    self.functions[name] = statement
                case FunctionDeclaration():
                    self.compile_function(statement)
                case Import(_, local_name):
                    self.imports[local_name] = statement
                case TypeDeclaration():
                    pass
                case _:
                    raise ValueError(f"Unexpected statement {statement}")
        self.emit("\n.data")
        for string in self.strings.values():
            print(f"{string.label}:", file=self.output)
            print(f'\t.asciz "{string.value.value.decode()}"', file=self.output)

    def compile_statement(self, statement):
        """Compile a statement to assembly"""
        match statement:
            case FunctionCall():
                self.compile_function_call(statement)
            case VariableDeclaration(variable, value):
                self.compile_variable_declaration(variable, value)
            case Assignment(lhs, rhs) if isinstance(lhs, BinaryOperator) and isinstance(
                lhs.op, Dot
            ):
                self.compile_field_write(lhs, rhs)
            case Assignment(variable, value):
                self.compile_variable_declaration(variable, value)
            case Return(value):
                self.stack[-1].return_value = value
                self.emit("b", self.stack[-1].end_label)
            case IfStatement(condition, true_branch, false_branch):
                self.compile_if_statement(condition, true_branch, false_branch)
            case ForStatement(condition, body):
                self.compile_for_statement(condition, body)
            case MatchStatement(expression, arms):
                self.compile_match(expression, arms)
            case _:
                raise ValueError(f"Unexpected statement {statement}")

    def compile_function(self, func):
        """Compile a function to assembly"""
        self.enter_stack_frame(func)
        for statement in func.body:
            self.compile_statement(statement)
        self.leave_stack_frame()
        self.functions[func.name] = func

    def enter_stack_frame(self, func):
        """Emit the prologue for a function"""
        label = Label(func.label_name)
        self.emit(".globl", label)
        self.emit_label(label)
        frame = StackFrame(func.variables.values(), label.end)
        self.stack.append(frame)
        self.emit("sub", Register("sp"), Register("sp"), Imm(frame.aligned_size() + 16))
        self.emit(
            "stp",
            Register("fp"),
            Register("lr"),
            StackAddress(frame.aligned_size(), "sp"),
        )
        self.emit("add", Register("fp"), Register("sp"), Imm(frame.aligned_size()))
        if func.params:
            self.move_args_to_stack(func)

    def move_args_to_stack(self, func):
        """Move arguments from registers to the stack"""
        offset = 0
        for param, register in zip(func.params, self._argregs):
            offset -= param.variable.type.width
            self.emit("str", register, StackAddress(offset, "fp"))

    def leave_stack_frame(self):
        """Emit the epilogue for a function"""
        label = self.stack[-1].end_label
        return_value = self.stack[-1].return_value
        print(f"{label}:", file=self.output)
        if return_value is None:
            self.mov(Register("w0"), Imm(0))
        else:
            addr = self.compile_expression(return_value)
            self.mov(Register("x0"), addr)
        frame = self.stack.pop()
        self.emit(
            "ldp",
            Register("fp"),
            Register("lr"),
            StackAddress(frame.aligned_size(), "sp"),
        )
        self.emit("add", Register("sp"), Register("sp"), Imm(frame.aligned_size() + 16))
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
        label = self.create_label("if")
        register = self.stack[-1].allocate_register()
        value = self.compile_expression(condition)
        self.mov(register, value)
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

    def compile_field_access(self, expression: BinaryOperator) -> Register:
        """Compile a struct field read via pointer indirection, returning a register."""
        obj_addr = self.stack[-1].get_variable_address(expression.lhs)
        struct_type = self.stack[-1].variables[expression.lhs.id].type
        field_offset = struct_type.field_offsets[expression.rhs.id]
        reg = self.stack[-1].allocate_register()
        self.emit("ldr", reg, obj_addr)  # load pointer from stack slot
        self.emit(
            "ldr", reg, StackAddress(field_offset, str(reg))
        )  # load field through pointer
        return reg

    def compile_field_write(self, lhs: BinaryOperator, rhs) -> None:
        """Compile a struct field write via pointer indirection."""
        obj_addr = self.stack[-1].get_variable_address(lhs.lhs)
        struct_type = self.stack[-1].variables[lhs.lhs.id].type
        field_offset = struct_type.field_offsets[lhs.rhs.id]
        # Compute RHS value first (may call functions — pointer is safe on stack)
        value = self.compile_expression(rhs)
        # Load pointer, then store value through it
        ptr_reg = self.stack[-1].allocate_register()
        self.emit("ldr", ptr_reg, obj_addr)
        val_reg = self.stack[-1].allocate_register()
        self.mov(val_reg, value)
        if isinstance(value, Register):
            self.stack[-1].release_register(value)
        self.emit("str", val_reg, StackAddress(field_offset, str(ptr_reg)))
        self.stack[-1].release_register(val_reg)
        self.stack[-1].release_register(ptr_reg)

    def compile_enum_unit_variant(self, expression) -> "Register":
        """Compile a unit enum variant access (e.g. Direction.North) to its discriminant."""
        enum_type = self.type_registry[expression.lhs.id]
        variant_info = enum_type.variants[expression.rhs.id]
        register = self.stack[-1].allocate_register()
        self.emit("mov", register, Imm(variant_info.discriminant))
        return register

    def _load_enum_discriminant(self, expr, operand):
        """For enum variable operands, load discriminant through pointer; others unchanged."""
        if isinstance(expr, Name):
            var = self.stack[-1].variables.get(expr.id)
            if var is not None and hasattr(getattr(var, "type", None), "variants"):
                # operand is StackAddress pointing to pointer slot — load ptr then discriminant
                reg = self.stack[-1].allocate_register()
                self.mov(reg, operand)
                self.emit("ldr", reg, StackAddress(0, str(reg)))
                return reg
        return operand

    def compile_match(self, expression, arms):
        """Compile a match statement."""
        if not isinstance(expression, Name):
            raise ValueError(f"Match expression must be a Name, got {expression}")
        from kod import types as _types

        label = self.create_label("match")
        enum_addr = self.stack[-1].get_variable_address(expression)
        disc_reg = self.stack[-1].allocate_register()
        self.emit("ldr", disc_reg, enum_addr)  # load pointer from stack slot

        var = self.stack[-1].variables.get(expression.id)
        is_optional = (
            var is not None
            and var.type is not None
            and isinstance(var.type, type)
            and issubclass(var.type, _types.OptionalType)
        )

        if not is_optional:
            # For enums: load discriminant through pointer
            self.emit("ldr", disc_reg, StackAddress(0, str(disc_reg)))

        skip_labels = [self.create_label("skip") for _ in arms]

        for i, arm in enumerate(arms):
            if isinstance(arm.pattern, WildcardPattern):
                for stmt in arm.body:
                    self.compile_statement(stmt)
                self.emit("b", label.done)
            elif isinstance(arm.pattern, OptionalNonePattern):
                # None: pointer == 0
                self.emit("cmp", disc_reg, Imm(0))
                self.emit("bne", skip_labels[i])
                for stmt in arm.body:
                    self.compile_statement(stmt)
                self.emit("b", label.done)
                self.emit_label(skip_labels[i])
            elif isinstance(arm.pattern, OptionalSomePattern):
                # Some: pointer != 0
                self.emit("cmp", disc_reg, Imm(0))
                self.emit("beq", skip_labels[i])
                if arm.pattern.binding:
                    ptr_reg = self.stack[-1].allocate_register()
                    self.emit("ldr", ptr_reg, enum_addr)
                    binding_addr = self.stack[-1].get_variable_address(
                        Name(arm.pattern.binding, span=arm.pattern.span)
                    )
                    val_reg = self.stack[-1].allocate_register()
                    self.emit("ldr", val_reg, StackAddress(0, str(ptr_reg)))
                    self.emit("str", val_reg, binding_addr)
                    self.stack[-1].release_register(val_reg)
                    self.stack[-1].release_register(ptr_reg)
                for stmt in arm.body:
                    self.compile_statement(stmt)
                self.emit("b", label.done)
                self.emit_label(skip_labels[i])
            elif isinstance(arm.pattern, EnumVariantPattern):
                enum_type = self.type_registry[arm.pattern.enum_name]
                variant_info = enum_type.variants[arm.pattern.variant_name]
                self.emit("cmp", disc_reg, Imm(variant_info.discriminant))
                self.emit("bne", skip_labels[i])
                # bind fields to pre-allocated stack slots via pointer
                for binding_name, field in zip(
                    arm.pattern.bindings, variant_info.fields
                ):
                    field_offset = variant_info.field_offsets[field.id]
                    ptr_reg = self.stack[-1].allocate_register()
                    self.emit("ldr", ptr_reg, enum_addr)  # reload pointer from stack
                    field_addr = StackAddress(8 + field_offset, str(ptr_reg))
                    binding_addr = self.stack[-1].get_variable_address(
                        Name(binding_name, span=arm.pattern.span)
                    )
                    val_reg = self.stack[-1].allocate_register()
                    self.emit("ldr", val_reg, field_addr)
                    self.emit("str", val_reg, binding_addr)
                    self.stack[-1].release_register(val_reg)
                    self.stack[-1].release_register(ptr_reg)
                for stmt in arm.body:
                    self.compile_statement(stmt)
                self.emit("b", label.done)
                self.emit_label(skip_labels[i])

        self.emit_label(label.done)
        self.stack[-1].release_register(disc_reg)

    def compile_variable_declaration(self, variable, expression):
        """Compile a variable declaration to assembly"""
        # Enum unit variant: let d: Direction = Direction.North
        if (
            isinstance(expression, BinaryOperator)
            and isinstance(expression.op, Dot)
            and isinstance(expression.lhs, Name)
            and expression.lhs.id in self.type_registry
            and hasattr(self.type_registry[expression.lhs.id], "variants")
        ):
            enum_type = self.type_registry[expression.lhs.id]
            variant_info = enum_type.variants[expression.rhs.id]
            if getattr(variable, "type", None) is None:
                variable.type = enum_type
            destination = self.stack[-1].get_variable_address(variable)
            # arena-allocate, store pointer, write discriminant through pointer
            self.mov(Register("x0"), Imm(enum_type.data_width))
            self.emit("bl", "_arena_alloc")
            ptr_reg = self.stack[-1].allocate_register()
            disc_reg = self.stack[-1].allocate_register()
            self.mov(ptr_reg, Register("x0"))
            self.emit("str", ptr_reg, destination)
            self.emit("mov", disc_reg, Imm(variant_info.discriminant))
            self.emit("str", disc_reg, StackAddress(0, str(ptr_reg)))
            self.stack[-1].release_register(disc_reg)
            self.stack[-1].release_register(ptr_reg)
            return

        # Enum payload variant: let m: Message = Message.Text(content: "hello")
        if (
            isinstance(expression, FunctionCall)
            and isinstance(expression.callee, BinaryOperator)
            and isinstance(expression.callee.op, Dot)
            and isinstance(expression.callee.lhs, Name)
            and expression.callee.lhs.id in self.type_registry
            and hasattr(self.type_registry[expression.callee.lhs.id], "variants")
        ):
            enum_type = self.type_registry[expression.callee.lhs.id]
            variant_info = enum_type.variants[expression.callee.rhs.id]
            if getattr(variable, "type", None) is None:
                variable.type = enum_type
            destination = self.stack[-1].get_variable_address(variable)
            # arena-allocate, store pointer, write discriminant and fields through pointer
            self.mov(Register("x0"), Imm(enum_type.data_width))
            self.emit("bl", "_arena_alloc")
            ptr_reg = self.stack[-1].allocate_register()
            disc_reg = self.stack[-1].allocate_register()
            self.mov(ptr_reg, Register("x0"))
            self.emit("str", ptr_reg, destination)
            self.emit("mov", disc_reg, Imm(variant_info.discriminant))
            self.emit("str", disc_reg, StackAddress(0, str(ptr_reg)))
            self.stack[-1].release_register(disc_reg)
            self.stack[-1].release_register(ptr_reg)
            # Store payload fields: compute value first, then reload pointer and store
            for arg in expression.args:
                field_offset = variant_info.field_offsets[arg.label.id]
                val = self.compile_expression(arg.expression)
                ptr_reg2 = self.stack[-1].allocate_register()
                self.emit("ldr", ptr_reg2, destination)  # reload pointer (safe)
                val_reg = self.stack[-1].allocate_register()
                self.mov(val_reg, val)
                if isinstance(val, Register):
                    self.stack[-1].release_register(val)
                self.emit("str", val_reg, StackAddress(8 + field_offset, str(ptr_reg2)))
                self.stack[-1].release_register(val_reg)
                self.stack[-1].release_register(ptr_reg2)
            return

        # Struct constructor: arena-allocate, store pointer, store fields via pointer
        if isinstance(expression, FunctionCall) and isinstance(expression.callee, Name):
            type_name = expression.callee.id
            if type_name in self.type_registry and hasattr(
                self.type_registry[type_name], "field_offsets"
            ):
                struct_type = self.type_registry[type_name]
                if getattr(variable, "type", None) is None:
                    variable.type = struct_type
                destination = self.stack[-1].get_variable_address(variable)
                # Call arena_alloc(data_width) — returns pointer in x0
                self.mov(Register("x0"), Imm(struct_type.data_width))
                self.emit("bl", "_arena_alloc")
                # Save pointer to variable's stack slot immediately
                tmp = self.stack[-1].allocate_register()
                self.mov(tmp, Register("x0"))
                self.emit("str", tmp, destination)
                self.stack[-1].release_register(tmp)
                # Store each field: compute value first, then reload pointer and store
                for arg in expression.args:
                    field_offset = struct_type.field_offsets[arg.label.id]
                    value = self.compile_expression(arg.expression)
                    ptr_reg = self.stack[-1].allocate_register()
                    self.emit("ldr", ptr_reg, destination)  # reload pointer (safe)
                    val_reg = self.stack[-1].allocate_register()
                    self.mov(val_reg, value)
                    if isinstance(value, Register):
                        self.stack[-1].release_register(value)
                    self.emit("str", val_reg, StackAddress(field_offset, str(ptr_reg)))
                    self.stack[-1].release_register(val_reg)
                    self.stack[-1].release_register(ptr_reg)
                return

        # Optional Some: let x: T? = <non-none value> — wrap in heap allocation
        from kod import types as _types

        if (
            getattr(variable, "type", None) is not None
            and isinstance(variable.type, type)
            and issubclass(variable.type, _types.OptionalType)
            and not isinstance(expression, NoneLiteral)
        ):
            destination = self.stack[-1].get_variable_address(variable)
            self.mov(Register("x0"), Imm(variable.type.data_width))
            self.emit("bl", "_arena_alloc")
            ptr_reg = self.stack[-1].allocate_register()
            self.mov(ptr_reg, Register("x0"))
            self.emit("str", ptr_reg, destination)
            val = self.compile_expression(expression)
            ptr_reg2 = self.stack[-1].allocate_register()
            self.emit("ldr", ptr_reg2, destination)
            val_reg = self.stack[-1].allocate_register()
            self.mov(val_reg, val)
            if isinstance(val, Register):
                self.stack[-1].release_register(val)
            self.emit("str", val_reg, StackAddress(0, str(ptr_reg2)))
            self.stack[-1].release_register(val_reg)
            self.stack[-1].release_register(ptr_reg2)
            self.stack[-1].release_register(ptr_reg)
            return

        destination = self.stack[-1].get_variable_address(variable)
        address = self.compile_expression(expression)
        register = self.stack[-1].allocate_register()
        self.mov(register, address)
        self.emit("str", register, destination)
        self.stack[-1].release_register(register)

    def compile_expression(self, expression):
        """Parse an expression"""
        if isinstance(expression, StringLiteral):
            value = self.literal_string(expression)
            register = self.stack[-1].allocate_register()
            self.emit("adrp", register, f"{value.label}@PAGE")
            self.emit("add", register, register, f"{value.label}@PAGEOFF")
            return register
        elif isinstance(expression, IntegerLiteral):
            return Imm(expression.value.value)
        elif isinstance(expression, BooleanLiteral):
            return Imm(int(expression.value.value))
        elif isinstance(expression, NoneLiteral):
            return Imm(0)
        elif isinstance(expression, Name):
            return self.stack[-1].get_variable_address(expression)
        elif isinstance(expression, FunctionCall):
            return self.compile_function_call(expression)
        elif isinstance(expression, BinaryOperator):
            if isinstance(expression.op, Dot):
                if (
                    isinstance(expression.lhs, Name)
                    and expression.lhs.id in self.type_registry
                    and hasattr(self.type_registry[expression.lhs.id], "variants")
                ):
                    return self.compile_enum_unit_variant(expression)
                return self.compile_field_access(expression)
            return self.compile_binary_operator(expression)
        else:
            raise ValueError(f"Unexpected expression {expression}")

    def compile_short_circuit(self, expression) -> Register:
        """Compile a short-circuit 'and'/'or' expression."""
        label = self.create_label("sc")
        result = self.stack[-1].allocate_register()

        lhs_val = self.compile_expression(expression.lhs)
        self.mov(result, lhs_val)
        if isinstance(lhs_val, Register):
            self.stack[-1].release_register(lhs_val)

        self.emit("cmp", result, Imm(0))
        self.emit("cset", result, "ne")

        if isinstance(expression.op, And):
            self.emit("beq", label.done)
        else:
            self.emit("bne", label.done)

        rhs_val = self.compile_expression(expression.rhs)
        self.mov(result, rhs_val)
        if isinstance(rhs_val, Register):
            self.stack[-1].release_register(rhs_val)

        self.emit("cmp", result, Imm(0))
        self.emit("cset", result, "ne")

        self.emit_label(label.done)
        return result

    def compile_is_check(self, expression):
        """Compile an `is None` / `is Some` check for optional types."""
        ptr = self.compile_expression(expression.lhs)
        reg = self.stack[-1].allocate_register()
        self.mov(reg, ptr)
        if isinstance(ptr, Register):
            self.stack[-1].release_register(ptr)
        self.emit("cmp", reg, Imm(0))
        if isinstance(expression.rhs, NoneLiteral):
            self.emit("cset", reg, "eq")
        else:
            self.emit("cset", reg, "ne")
        return reg

    def compile_binary_operator(self, expression):
        """Compile a binary operator to assembly"""
        if isinstance(expression.op, (And, Or)):
            return self.compile_short_circuit(expression)

        if isinstance(expression.op, Is):
            return self.compile_is_check(expression)

        cmp_ops = (LessThan, GreaterThan, EqualEqual, NotEqual, LessEqual, GreaterEqual)
        arith_ops = (Plus, Minus, Slash, Star)
        if not isinstance(expression.op, cmp_ops + arith_ops):
            raise ValueError(f"Unknown operator: {expression.op}")
        left = self.compile_expression(expression.lhs)
        right = self.compile_expression(expression.rhs)
        # For enum comparisons, load discriminants through pointers
        if isinstance(expression.op, cmp_ops):
            left = self._load_enum_discriminant(expression.lhs, left)
            right = self._load_enum_discriminant(expression.rhs, right)
        try:
            lhs_register = self.stack[-1].allocate_register()
            rhs_register = self.stack[-1].allocate_register()
            self.mov(lhs_register, left)
            self.mov(rhs_register, right)
            if isinstance(expression.op, cmp_ops):
                self.emit("cmp", lhs_register, rhs_register)
                op = {
                    LessThan: "lt",
                    GreaterThan: "gt",
                    EqualEqual: "eq",
                    NotEqual: "ne",
                    LessEqual: "le",
                    GreaterEqual: "ge",
                }[type(expression.op)]
                self.emit("cset", lhs_register, op)
            else:
                op = {Plus: "add", Minus: "sub", Slash: "sdiv", Star: "mul"}[
                    type(expression.op)
                ]
                self.emit(op, lhs_register, lhs_register, rhs_register)
            self.stack[-1].release_register(rhs_register)
            return lhs_register
        finally:
            if isinstance(left, Register):
                self.stack[-1].release_register(left)
            if isinstance(right, Register):
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

    def resolve_function(self, callee):
        """Resolve a function"""
        match callee:
            case Name(id_):
                return self.functions[id_]
            case BinaryOperator(lhs, op, rhs):
                if (
                    isinstance(op, Dot)
                    and isinstance(lhs, Name)
                    and lhs.id in self.imports
                ):
                    module_name = self.module.resolve_import(
                        self.imports[lhs.id].module_name
                    )
                    module = self.program.get_module(module_name)
                    return module.names[rhs.id]
                else:
                    raise ValueError(
                        "LHS of dotted callable is not an import",
                        op,
                        lhs.id,
                        self.imports,
                    )
            case _:
                raise ValueError(f"Unexpected function {callee}")

    def compile_function_call(self, func_call):
        """Compile a function call to assembly"""
        func = self.resolve_function(func_call.callee)
        self.prepare_args(func, func_call.args)
        self.emit("bl", func.label_name)
        return Register("x0")

    def prepare_args(self, func, args):
        """Prepare arguments for a function call"""
        offset = 0
        for param, arg, arg_register in zip(func.params, args, self._argregs):
            offset -= param.variable.type.width
            register = self.compile_expression(arg.expression)
            self.mov(arg_register, register)

    def mov(self, dest, src):
        """Move a value"""
        if isinstance(src, StackAddress):
            self.emit("ldr", dest, src)
        else:
            self.emit("mov", dest, src)
