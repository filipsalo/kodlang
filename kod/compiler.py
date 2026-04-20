#!/usr/bin/env python
"""An assembler for the Kod language."""

import collections
import sys

from kod.ast import (
    ArrayLiteral,
    Assignment,
    BinaryOperator,
    BooleanLiteral,
    BreakStatement,
    ContinueStatement,
    EnumVariantPattern,
    ExternalFunctionDeclaration,
    ForEachStatement,
    ForStatement,
    FunctionCall,
    FunctionDeclaration,
    GenericInstantiation,
    IfStatement,
    Import,
    IntegerLiteral,
    IntegerPattern,
    MatchExpression,
    MatchStatement,
    Module,
    Name,
    NoneLiteral,
    OptionalNonePattern,
    OptionalSomePattern,
    Return,
    StringLiteral,
    StringPattern,
    StringSlice,
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
    OpenBracket,
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

    def __init__(self, variables, end_label, return_type=None):
        self.variables = {variable.id: variable for variable in variables}
        self.end_label = end_label
        self.return_type = return_type
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

    _allocatable = {f"x{n}" for n in [*range(8, 16), *range(19, 28)]}

    def release_register(self, register):
        """Release a register"""
        if register.name in self._allocatable:
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
        self.loop_labels = []
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
        from kod import values as _types

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
                case TypeDeclaration(_, type_):
                    if hasattr(type_, "methods") and not isinstance(
                        type_, _types.GenericTemplate
                    ):
                        for method in type_.methods.values():
                            self.compile_function(method, struct_type=type_)
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
            case Assignment(lhs, rhs) if isinstance(lhs, BinaryOperator) and isinstance(
                lhs.op, OpenBracket
            ):
                self.compile_subscript_write(lhs, rhs)
            case Assignment(variable, value):
                self.compile_variable_declaration(variable, value)
            case Return(value):
                self.compile_return(value)
                self.emit("b", self.stack[-1].end_label)
            case IfStatement(condition, true_branch, false_branch):
                self.compile_if_statement(condition, true_branch, false_branch)
            case ForStatement(condition, body):
                self.compile_for_statement(condition, body)
            case ForEachStatement(binding, iterable, body):
                self.compile_for_each_statement(binding, iterable, body)
            case MatchStatement(expression, arms):
                self.compile_match(expression, arms)
            case BreakStatement():
                self.emit("b", self.loop_labels[-1].end)
            case ContinueStatement():
                self.emit("b", self.loop_labels[-1].start)
            case _:
                raise ValueError(f"Unexpected statement {statement}")

    def compile_function(self, func, struct_type=None):
        """Compile a function to assembly"""
        self.enter_stack_frame(func)
        if func.struct_name and "self" in self.stack[-1].variables:
            if struct_type is None:
                struct_type = self.type_registry.get(func.struct_name)
            self.stack[-1].variables["self"].type = struct_type
        for statement in func.body:
            self.compile_statement(statement)
        # Implicit return 0 for functions that fall off the end
        self.mov(Register("x0"), Imm(0))
        self.leave_stack_frame()
        self.functions[func.name] = func

    def enter_stack_frame(self, func):
        """Emit the prologue for a function"""
        label = Label(func.label_name)
        self.emit(".globl", label)
        self.emit_label(label)
        frame = StackFrame(func.variables.values(), label.end, func.return_type)
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
            width = param.variable.type.width if param.variable.type else 8
            offset -= width
            self.emit("str", register, StackAddress(offset, "fp"))

    def compile_return(self, value):
        """Compile a return value into x0, handling optional wrapping."""
        from kod import values as _types

        return_type = self.stack[-1].return_type
        is_optional_return = (
            return_type is not None
            and isinstance(return_type, type)
            and issubclass(return_type, _types.OptionalType)
        )
        # If expression is already optional (e.g. returning result of another ?-returning func)
        expr_type = self._infer_type(value) if value is not None else None
        expr_already_optional = (
            expr_type is not None
            and isinstance(expr_type, type)
            and issubclass(expr_type, _types.OptionalType)
        )
        if (
            is_optional_return
            and not isinstance(value, NoneLiteral)
            and not expr_already_optional
        ):
            # Compile value first (may call bl), save to stack temp, then arena-alloc
            val = self.compile_expression(value)
            # Save to stack temp to survive any upcoming bl
            self.emit("sub", Register("sp"), Register("sp"), Imm(16))
            val_reg = self.stack[-1].allocate_register()
            self.mov(val_reg, val)
            if isinstance(val, Register):
                self.stack[-1].release_register(val)
            self.emit("str", val_reg, StackAddress(0, "sp"))
            self.stack[-1].release_register(val_reg)
            # Arena-alloc the slot
            self.mov(Register("x0"), Imm(return_type.data_width))
            self.emit("bl", "_arena_alloc")
            # Reload value from stack temp and store into arena slot
            tmp_reg = self.stack[-1].allocate_register()
            self.emit("ldr", tmp_reg, StackAddress(0, "sp"))
            self.emit("add", Register("sp"), Register("sp"), Imm(16))
            self.emit("str", tmp_reg, StackAddress(0, str(Register("x0"))))
            self.stack[-1].release_register(tmp_reg)
        elif isinstance(value, NoneLiteral) or value is None:
            self.mov(Register("x0"), Imm(0))
        elif self._is_enum_literal(value):
            self._compile_enum_literal_to_x0(value)
        else:
            addr = self.compile_expression(value)
            self.mov(Register("x0"), addr)
            if isinstance(addr, Register):
                self.stack[-1].release_register(addr)

    def _is_enum_literal(self, expression) -> bool:
        """Return True if expression is an enum unit or payload variant literal."""
        if (
            isinstance(expression, BinaryOperator)
            and isinstance(expression.op, Dot)
            and isinstance(expression.lhs, Name)
            and expression.lhs.id in self.type_registry
            and hasattr(self.type_registry[expression.lhs.id], "variants")
        ):
            return True
        if (
            isinstance(expression, FunctionCall)
            and isinstance(expression.callee, BinaryOperator)
            and isinstance(expression.callee.op, Dot)
            and isinstance(expression.callee.lhs, Name)
            and expression.callee.lhs.id in self.type_registry
            and hasattr(self.type_registry[expression.callee.lhs.id], "variants")
        ):
            return True
        return False

    def _compile_enum_literal_to_x0(self, expression):
        """Arena-alloc an enum struct from a literal and leave the pointer in x0."""
        if isinstance(expression, BinaryOperator):
            # Unit variant: Direction.North
            enum_type = self.type_registry[expression.lhs.id]
            variant_info = enum_type.variants[expression.rhs.id]
            self.mov(Register("x0"), Imm(enum_type.data_width))
            self.emit("bl", "_arena_alloc")
            ptr_reg = self.stack[-1].allocate_register()
            disc_reg = self.stack[-1].allocate_register()
            self.mov(ptr_reg, Register("x0"))
            self.emit("mov", disc_reg, Imm(variant_info.discriminant))
            self.emit("str", disc_reg, StackAddress(0, str(ptr_reg)))
            self.stack[-1].release_register(disc_reg)
            self.mov(Register("x0"), ptr_reg)
            self.stack[-1].release_register(ptr_reg)
        else:
            # Payload variant: Message.Text(content: "hello") — compile like a var decl
            # Use a stack temp to hold the pointer across field stores
            enum_type = self.type_registry[expression.callee.lhs.id]
            variant_info = enum_type.variants[expression.callee.rhs.id]
            self.mov(Register("x0"), Imm(enum_type.data_width))
            self.emit("bl", "_arena_alloc")
            # Save pointer on stack temp — field compilation may call bl
            self.emit("sub", Register("sp"), Register("sp"), Imm(16))
            tmp = self.stack[-1].allocate_register()
            self.mov(tmp, Register("x0"))
            self.emit("str", tmp, StackAddress(0, "sp"))
            self.stack[-1].release_register(tmp)
            disc_reg = self.stack[-1].allocate_register()
            self.emit("ldr", disc_reg, StackAddress(0, "sp"))
            self.emit(
                "mov",
                tmp := self.stack[-1].allocate_register(),
                Imm(variant_info.discriminant),
            )
            self.emit("str", tmp, StackAddress(0, str(disc_reg)))
            self.stack[-1].release_register(tmp)
            for arg in expression.args:
                field_offset = variant_info.field_offsets[arg.label.id]
                val = self.compile_expression(arg.expression)
                ptr = self.stack[-1].allocate_register()
                self.emit("ldr", ptr, StackAddress(0, "sp"))
                val_reg = self.stack[-1].allocate_register()
                self.mov(val_reg, val)
                if isinstance(val, Register):
                    self.stack[-1].release_register(val)
                self.emit("str", val_reg, StackAddress(8 + field_offset, str(ptr)))
                self.stack[-1].release_register(val_reg)
                self.stack[-1].release_register(ptr)
            self.stack[-1].release_register(disc_reg)
            self.emit("ldr", Register("x0"), StackAddress(0, "sp"))
            self.emit("add", Register("sp"), Register("sp"), Imm(16))

    def leave_stack_frame(self):
        """Emit the epilogue for a function (teardown only — return value already in x0)."""
        label = self.stack[-1].end_label
        print(f"{label}:", file=self.output)
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
        self.loop_labels.append(label)
        self.emit_label(label.start)
        register = self.compile_expression(condition)
        self.emit("cmp", register, Imm(0))
        self.emit("beq", label.end)
        for statement in body:
            self.compile_statement(statement)
        self.emit("b", label.start)
        self.emit_label(label.end)
        self.loop_labels.pop()

    def compile_for_each_statement(self, binding, iterable, body):
        """Compile a for-each loop over an array"""
        label = self.create_label("foreach")

        # for-each continue target is the increment, not the condition check
        class _ForeachLabel:
            start = label.incr
            end = label.end

        self.loop_labels.append(_ForeachLabel())
        frame = self.stack[-1]
        idx_name = f"__foreach_idx_{binding}"

        # Load array header ptr into a register, then read len and data ptr
        hdr_reg = frame.allocate_register()
        len_reg = frame.allocate_register()
        ptr_reg = frame.allocate_register()
        idx_reg = frame.allocate_register()
        elem_reg = frame.allocate_register()

        arr_reg = self.compile_expression(iterable)
        self.mov(hdr_reg, arr_reg)

        self.emit("ldr", len_reg, StackAddress(8, str(hdr_reg)))  # header.len
        self.emit("ldr", ptr_reg, StackAddress(0, str(hdr_reg)))  # header.ptr
        frame.release_register(hdr_reg)

        # index = 0, store to stack slot
        self.emit("mov", idx_reg, Imm(0))
        self.emit("str", idx_reg, frame.get_variable_address(frame.variables[idx_name]))

        self.emit_label(label.start)
        # reload index, compare with len
        self.emit("ldr", idx_reg, frame.get_variable_address(frame.variables[idx_name]))
        self.emit("cmp", idx_reg, len_reg)
        self.emit("bge", label.end)

        # load element: ptr[idx * 8]
        self.emit("lsl", elem_reg, idx_reg, Imm(3))
        self.emit("ldr", elem_reg, f"[{ptr_reg}, {elem_reg}]")
        self.emit("str", elem_reg, frame.get_variable_address(frame.variables[binding]))

        for stmt in body:
            self.compile_statement(stmt)

        # increment index and store back — continue jumps here
        self.emit_label(label.incr)
        self.emit("ldr", idx_reg, frame.get_variable_address(frame.variables[idx_name]))
        self.emit("add", idx_reg, idx_reg, Imm(1))
        self.emit("str", idx_reg, frame.get_variable_address(frame.variables[idx_name]))
        self.emit("b", label.start)
        self.emit_label(label.end)

        self.loop_labels.pop()
        frame.release_register(len_reg)
        frame.release_register(ptr_reg)
        frame.release_register(idx_reg)
        frame.release_register(elem_reg)

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

    def compile_subscript_read(self, expression: BinaryOperator) -> "Register":
        """Compile m[key] by calling op_index on the object."""
        obj_name = expression.lhs.id
        var = self.stack[-1].variables[obj_name]
        method = var.type.methods["op_index"]
        obj_addr = self.stack[-1].get_variable_address(expression.lhs)
        self.emit("ldr", self._argregs[0], obj_addr)
        key_reg = self.compile_expression(expression.rhs)
        self.mov(self._argregs[1], key_reg)
        if isinstance(key_reg, Register):
            self.stack[-1].release_register(key_reg)
        self.emit("bl", method.label_name)
        return Register("x0")

    def compile_subscript_write(self, lhs: BinaryOperator, rhs) -> None:
        """Compile m[key] = value by calling op_index_set on the object."""
        obj_name = lhs.lhs.id
        var = self.stack[-1].variables.get(obj_name)
        method = var.type.methods["op_index_set"]
        obj_addr = self.stack[-1].get_variable_address(lhs.lhs)
        self.emit("ldr", self._argregs[0], obj_addr)
        key_reg = self.compile_expression(lhs.rhs)
        self.mov(self._argregs[1], key_reg)
        if isinstance(key_reg, Register):
            self.stack[-1].release_register(key_reg)
        val_reg = self.compile_expression(rhs)
        self.mov(self._argregs[2], val_reg)
        if isinstance(val_reg, Register):
            self.stack[-1].release_register(val_reg)
        self.emit("bl", method.label_name)

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

    def _emit_strcmp_pattern(self, subject_reg, pattern: StringPattern) -> None:
        """Emit strcmp(subject, literal) and set flags; caller emits branch."""
        from kod import values as _types

        pat_lit = self.literal_string(
            StringLiteral(_types.String(pattern.value.encode()), span=pattern.span)
        )
        self.mov(Register("x0"), subject_reg)
        pat_reg = self.stack[-1].allocate_register()
        self.emit("adrp", pat_reg, f"{pat_lit.label}@PAGE")
        self.emit("add", pat_reg, pat_reg, f"{pat_lit.label}@PAGEOFF")
        self.mov(Register("x1"), pat_reg)
        self.stack[-1].release_register(pat_reg)
        self.emit("bl", "_strcmp")
        self.emit("cmp", Register("x0"), Imm(0))

    def compile_match(self, expression, arms):
        """Compile a match statement."""
        if not isinstance(expression, Name):
            raise ValueError(f"Match expression must be a Name, got {expression}")
        from kod import values as _types

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
        is_scalar = var is not None and var.type in (
            _types.Int64,
            _types.Bool,
            _types.String,
        )

        if not is_optional and not is_scalar:
            # For enums: load discriminant through pointer
            self.emit("ldr", disc_reg, StackAddress(0, str(disc_reg)))

        skip_labels = [self.create_label("skip") for _ in arms]

        for i, arm in enumerate(arms):
            if isinstance(arm.pattern, IntegerPattern):
                self.emit("cmp", disc_reg, Imm(arm.pattern.value))
                self.emit("bne", skip_labels[i])
                for stmt in arm.body:
                    self.compile_statement(stmt)
                self.emit("b", label.done)
                self.emit_label(skip_labels[i])
            elif isinstance(arm.pattern, StringPattern):
                self._emit_strcmp_pattern(disc_reg, arm.pattern)
                self.emit("bne", skip_labels[i])
                for stmt in arm.body:
                    self.compile_statement(stmt)
                self.emit("b", label.done)
                self.emit_label(skip_labels[i])
            elif isinstance(arm.pattern, WildcardPattern):
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

    def compile_match_expression(self, node: MatchExpression) -> Register:
        """Compile a match expression, returning a register with the result."""

        label = self.create_label("matchexpr")
        subject_val = self.compile_expression(node.expression)
        disc_reg = self.stack[-1].allocate_register()
        self.mov(disc_reg, subject_val)
        if isinstance(subject_val, Register):
            self.stack[-1].release_register(subject_val)

        result_reg = self.stack[-1].allocate_register()
        skip_labels = [self.create_label("skip") for _ in node.arms]

        for i, arm in enumerate(node.arms):
            if isinstance(arm.pattern, IntegerPattern):
                self.emit("cmp", disc_reg, Imm(arm.pattern.value))
                self.emit("bne", skip_labels[i])
                val = self.compile_expression(arm.body)
                self.mov(result_reg, val)
                if isinstance(val, Register):
                    self.stack[-1].release_register(val)
                self.emit("b", label.done)
                self.emit_label(skip_labels[i])
            elif isinstance(arm.pattern, StringPattern):
                self._emit_strcmp_pattern(disc_reg, arm.pattern)
                self.emit("bne", skip_labels[i])
                val = self.compile_expression(arm.body)
                self.mov(result_reg, val)
                if isinstance(val, Register):
                    self.stack[-1].release_register(val)
                self.emit("b", label.done)
                self.emit_label(skip_labels[i])
            elif isinstance(arm.pattern, WildcardPattern):
                val = self.compile_expression(arm.body)
                self.mov(result_reg, val)
                if isinstance(val, Register):
                    self.stack[-1].release_register(val)
                self.emit("b", label.done)
            elif isinstance(arm.pattern, EnumVariantPattern):
                enum_type = self.type_registry[arm.pattern.enum_name]
                variant_info = enum_type.variants[arm.pattern.variant_name]
                self.emit("cmp", disc_reg, Imm(variant_info.discriminant))
                self.emit("bne", skip_labels[i])
                val = self.compile_expression(arm.body)
                self.mov(result_reg, val)
                if isinstance(val, Register):
                    self.stack[-1].release_register(val)
                self.emit("b", label.done)
                self.emit_label(skip_labels[i])

        self.emit_label(label.done)
        self.stack[-1].release_register(disc_reg)
        return result_reg

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
        struct_type = None
        if isinstance(expression, FunctionCall) and isinstance(expression.callee, Name):
            type_name = expression.callee.id
            if type_name in self.type_registry and hasattr(
                self.type_registry[type_name], "field_offsets"
            ):
                struct_type = self.type_registry[type_name]
        elif isinstance(expression, FunctionCall) and isinstance(
            expression.callee, GenericInstantiation
        ):
            template = self.type_registry[expression.callee.name.id]
            struct_type = template.instantiate(tuple(expression.callee.type_args))
        if struct_type is not None:
            if getattr(variable, "type", None) is None:
                variable.type = struct_type
            destination = self.stack[-1].get_variable_address(variable)
            self.mov(Register("x0"), Imm(struct_type.data_width))
            self.emit("bl", "_arena_alloc")
            tmp = self.stack[-1].allocate_register()
            self.mov(tmp, Register("x0"))
            self.emit("str", tmp, destination)
            self.stack[-1].release_register(tmp)
            for arg in expression.args:
                field_offset = struct_type.field_offsets[arg.label.id]
                value = self.compile_expression(arg.expression)
                ptr_reg = self.stack[-1].allocate_register()
                self.emit("ldr", ptr_reg, destination)
                val_reg = self.stack[-1].allocate_register()
                self.mov(val_reg, value)
                if isinstance(value, Register):
                    self.stack[-1].release_register(value)
                self.emit("str", val_reg, StackAddress(field_offset, str(ptr_reg)))
                self.stack[-1].release_register(val_reg)
                self.stack[-1].release_register(ptr_reg)
            return

        # Optional Some: let x: T? = <non-none value> — wrap in heap allocation
        from kod import values as _types

        expr_type = self._infer_type(expression)
        rhs_already_optional = (
            expr_type is not None
            and isinstance(expr_type, type)
            and issubclass(expr_type, _types.OptionalType)
        )

        if (
            getattr(variable, "type", None) is not None
            and isinstance(variable.type, type)
            and issubclass(variable.type, _types.OptionalType)
            and not isinstance(expression, NoneLiteral)
            and not rhs_already_optional
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

        # Array literal: arena-alloc header {ptr, len, cap} + element buffer
        if isinstance(expression, ArrayLiteral):
            n = len(expression.elements)
            item_width = 8
            destination = self.stack[-1].get_variable_address(variable)
            # Alloc header first, save to stack slot immediately
            self.mov(Register("x0"), Imm(24))
            self.emit("bl", "_arena_alloc")
            tmp = self.stack[-1].allocate_register()
            self.mov(tmp, Register("x0"))
            self.emit("str", tmp, destination)
            self.stack[-1].release_register(tmp)
            # Alloc element buffer
            self.mov(Register("x0"), Imm(max(n, 1) * item_width))
            self.emit("bl", "_arena_alloc")
            buf_reg = self.stack[-1].allocate_register()
            self.mov(buf_reg, Register("x0"))
            # Fill elements into buffer (simple expressions only — no bl calls)
            for i, elem in enumerate(expression.elements):
                val = self.compile_expression(elem)
                val_reg = self.stack[-1].allocate_register()
                self.mov(val_reg, val)
                if isinstance(val, Register):
                    self.stack[-1].release_register(val)
                self.emit("str", val_reg, StackAddress(i * item_width, str(buf_reg)))
                self.stack[-1].release_register(val_reg)
            # Wire header: reload ptr, store buf_ptr/len/cap
            ptr_reg = self.stack[-1].allocate_register()
            self.emit("ldr", ptr_reg, destination)
            self.emit("str", buf_reg, StackAddress(0, str(ptr_reg)))
            len_reg = self.stack[-1].allocate_register()
            self.emit("mov", len_reg, Imm(n))
            self.emit("str", len_reg, StackAddress(8, str(ptr_reg)))
            self.emit("str", len_reg, StackAddress(16, str(ptr_reg)))
            self.stack[-1].release_register(len_reg)
            self.stack[-1].release_register(buf_reg)
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
        elif isinstance(expression, ArrayLiteral):
            return self.compile_array_literal_expr(expression)
        elif isinstance(expression, StringSlice):
            return self.compile_str_slice(expression)
        elif isinstance(expression, BinaryOperator):
            if isinstance(expression.op, Dot):
                if (
                    isinstance(expression.lhs, Name)
                    and expression.lhs.id in self.type_registry
                    and hasattr(self.type_registry[expression.lhs.id], "variants")
                ):
                    return self.compile_enum_unit_variant(expression)
                return self.compile_field_access(expression)
            elif isinstance(expression.op, OpenBracket):
                if (
                    isinstance(expression.lhs, Name)
                    and expression.lhs.id in self.stack[-1].variables
                    and hasattr(
                        self.stack[-1].variables[expression.lhs.id].type, "methods"
                    )
                    and "op_index"
                    in self.stack[-1].variables[expression.lhs.id].type.methods
                ):
                    return self.compile_subscript_read(expression)
                return self.compile_index(expression)
            return self.compile_binary_operator(expression)
        elif isinstance(expression, MatchExpression):
            return self.compile_match_expression(expression)
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

    def compile_index(self, expression):
        """Compile expr[i] — byte load for strings, 8-byte load for arrays."""
        from kod import values as _types

        lhs_type = self._infer_type(expression.lhs)

        ptr = self.compile_expression(expression.lhs)
        idx = self.compile_expression(expression.rhs)
        ptr_reg = self.stack[-1].allocate_register()
        idx_reg = self.stack[-1].allocate_register()
        self.mov(ptr_reg, ptr)
        self.mov(idx_reg, idx)
        if isinstance(ptr, Register):
            self.stack[-1].release_register(ptr)
        if isinstance(idx, Register):
            self.stack[-1].release_register(idx)
        result = self.stack[-1].allocate_register()

        if (
            lhs_type is not None
            and isinstance(lhs_type, type)
            and issubclass(lhs_type, _types.ArrayType)
        ):
            # Dereference header to get data_ptr, scale index by item_width (8)
            self.emit("ldr", ptr_reg, StackAddress(0, str(ptr_reg)))
            self.emit("lsl", idx_reg, idx_reg, Imm(3))
            self.emit("ldr", result, f"[{ptr_reg}, {idx_reg}]")
        else:
            self.emit("ldrb", f"w{result.name[1:]}", f"[{ptr_reg}, {idx_reg}]")

        self.stack[-1].release_register(idx_reg)
        self.stack[-1].release_register(ptr_reg)
        return result

    def compile_array_literal_expr(self, node):
        """Compile an array literal in expression context using a temp stack slot."""
        n = len(node.elements)
        item_width = 8
        # Push a temp slot below the frame to survive the arena_alloc calls
        self.emit("sub", Register("sp"), Register("sp"), Imm(16))
        # Alloc header, save ptr to temp slot
        self.mov(Register("x0"), Imm(24))
        self.emit("bl", "_arena_alloc")
        self.emit("str", Register("x0"), StackAddress(0, "sp"))
        # Alloc element buffer
        self.mov(Register("x0"), Imm(max(n, 1) * item_width))
        self.emit("bl", "_arena_alloc")
        buf_reg = self.stack[-1].allocate_register()
        self.mov(buf_reg, Register("x0"))
        # Fill elements
        for i, elem in enumerate(node.elements):
            val = self.compile_expression(elem)
            val_reg = self.stack[-1].allocate_register()
            self.mov(val_reg, val)
            if isinstance(val, Register):
                self.stack[-1].release_register(val)
            self.emit("str", val_reg, StackAddress(i * item_width, str(buf_reg)))
            self.stack[-1].release_register(val_reg)
        # Load header ptr from temp slot, restore sp
        hdr_reg = self.stack[-1].allocate_register()
        self.emit("ldr", hdr_reg, StackAddress(0, "sp"))
        self.emit("add", Register("sp"), Register("sp"), Imm(16))
        # Wire header: ptr, len, cap
        self.emit("str", buf_reg, StackAddress(0, str(hdr_reg)))
        len_reg = self.stack[-1].allocate_register()
        self.emit("mov", len_reg, Imm(n))
        self.emit("str", len_reg, StackAddress(8, str(hdr_reg)))
        self.emit("str", len_reg, StackAddress(16, str(hdr_reg)))
        self.stack[-1].release_register(len_reg)
        self.stack[-1].release_register(buf_reg)
        return hdr_reg

    def compile_str_concat(self, expression):
        """Compile str + str → _kod_str_concat(lhs, rhs)."""
        rhs = self.compile_expression(expression.rhs)
        rhs_reg = self.stack[-1].allocate_register()
        self.mov(rhs_reg, rhs)
        if isinstance(rhs, Register):
            self.stack[-1].release_register(rhs)
        lhs = self.compile_expression(expression.lhs)
        self.mov(Register("x0"), lhs)
        if isinstance(lhs, Register):
            self.stack[-1].release_register(lhs)
        self.mov(Register("x1"), rhs_reg)
        self.stack[-1].release_register(rhs_reg)
        self.emit("bl", "_kod_str_concat")
        return Register("x0")

    def compile_str_slice(self, expression: StringSlice):
        """Compile s[i:j] → _kod_str_slice(s, i, j)."""
        end = self.compile_expression(expression.end)
        end_reg = self.stack[-1].allocate_register()
        self.mov(end_reg, end)
        if isinstance(end, Register):
            self.stack[-1].release_register(end)
        start = self.compile_expression(expression.start)
        start_reg = self.stack[-1].allocate_register()
        self.mov(start_reg, start)
        if isinstance(start, Register):
            self.stack[-1].release_register(start)
        s = self.compile_expression(expression.string)
        self.mov(Register("x0"), s)
        if isinstance(s, Register):
            self.stack[-1].release_register(s)
        self.mov(Register("x1"), start_reg)
        self.mov(Register("x2"), end_reg)
        self.stack[-1].release_register(start_reg)
        self.stack[-1].release_register(end_reg)
        self.emit("bl", "_kod_str_slice")
        return Register("x0")

    def compile_str_eq(self, expression, negate: bool):
        """Compile str == str or str != str via strcmp."""
        rhs = self.compile_expression(expression.rhs)
        rhs_reg = self.stack[-1].allocate_register()
        self.mov(rhs_reg, rhs)
        if isinstance(rhs, Register):
            self.stack[-1].release_register(rhs)
        lhs = self.compile_expression(expression.lhs)
        self.mov(Register("x0"), lhs)
        if isinstance(lhs, Register):
            self.stack[-1].release_register(lhs)
        self.mov(Register("x1"), rhs_reg)
        self.stack[-1].release_register(rhs_reg)
        self.emit("bl", "_strcmp")
        result = self.stack[-1].allocate_register()
        self.emit("cmp", Register("x0"), Imm(0))
        self.emit("cset", result, "ne" if negate else "eq")
        return result

    def compile_array_concat(self, expression):
        """Compile [T] + [T] → _kod_array_concat(lhs, rhs)."""
        # Compile RHS first (may involve bl calls, e.g. ArrayLiteral)
        rhs = self.compile_expression(expression.rhs)
        rhs_reg = self.stack[-1].allocate_register()
        self.mov(rhs_reg, rhs)
        if isinstance(rhs, Register):
            self.stack[-1].release_register(rhs)
        # Compile LHS (Name → StackAddress, no bl)
        lhs = self.compile_expression(expression.lhs)
        self.mov(Register("x0"), lhs)
        if isinstance(lhs, Register):
            self.stack[-1].release_register(lhs)
        self.mov(Register("x1"), rhs_reg)
        self.stack[-1].release_register(rhs_reg)
        self.emit("bl", "_kod_array_concat")
        return Register("x0")

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

    def _infer_type(self, expression):
        """Infer the type of an expression, returning None if unknown."""
        from kod import values as _types

        if isinstance(expression, StringLiteral):
            return _types.String
        if isinstance(expression, IntegerLiteral):
            return _types.Int64
        if isinstance(expression, Name):
            var = self.stack[-1].variables.get(expression.id)
            if var is not None:
                return var.type
        if isinstance(expression, BinaryOperator) and isinstance(expression.op, Dot):
            obj_type = self._infer_type(expression.lhs)
            if obj_type is not None and hasattr(obj_type, "struct_fields"):
                field_name = (
                    expression.rhs.id if isinstance(expression.rhs, Name) else None
                )
                if field_name is not None:
                    for f in obj_type.struct_fields:
                        if f.id == field_name:
                            return f.type
        if isinstance(expression, BinaryOperator) and isinstance(
            expression.op, OpenBracket
        ):
            obj_type = self._infer_type(expression.lhs)
            if obj_type is not None and hasattr(obj_type, "methods"):
                method = obj_type.methods.get("op_index")
                if method is not None:
                    return getattr(method, "return_type", None)
        if isinstance(expression, FunctionCall):
            if isinstance(expression.callee, Name):
                func = self.functions.get(expression.callee.id)
                if func is not None:
                    return getattr(func, "return_type", None)
            if (
                isinstance(expression.callee, BinaryOperator)
                and isinstance(expression.callee.op, Dot)
                and isinstance(expression.callee.rhs, Name)
            ):
                obj_type = self._infer_type(expression.callee.lhs)
                if obj_type is not None and hasattr(obj_type, "methods"):
                    method = obj_type.methods.get(expression.callee.rhs.id)
                    if method is not None:
                        return getattr(method, "return_type", None)
        return None

    def compile_binary_operator(self, expression):
        """Compile a binary operator to assembly"""
        if isinstance(expression.op, (And, Or)):
            return self.compile_short_circuit(expression)

        if isinstance(expression.op, Plus):
            from kod import values as _types

            lhs_type = self._infer_type(expression.lhs)
            if lhs_type is _types.String:
                return self.compile_str_concat(expression)
            if (
                lhs_type is not None
                and isinstance(lhs_type, type)
                and issubclass(lhs_type, _types.ArrayType)
            ):
                return self.compile_array_concat(expression)

        if isinstance(expression.op, (EqualEqual, NotEqual)):
            from kod import values as _types

            lhs_type = self._infer_type(expression.lhs)
            if lhs_type is _types.String:
                return self.compile_str_eq(
                    expression, negate=isinstance(expression.op, NotEqual)
                )

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
        from kod import values as _types

        if (
            isinstance(func_call.callee, Name)
            and func_call.callee.id == "len"
            and len(func_call.args) == 1
        ):
            arg_expr = func_call.args.params[0].expression
            arg_type = self._infer_type(arg_expr)
            if (
                arg_type is not None
                and isinstance(arg_type, type)
                and issubclass(arg_type, _types.ArrayType)
            ):
                ptr_reg = self.stack[-1].allocate_register()
                if isinstance(arg_expr, Name):
                    addr = self.stack[-1].get_variable_address(arg_expr)
                    self.emit("ldr", ptr_reg, addr)
                else:
                    val = self.compile_expression(arg_expr)
                    self.mov(ptr_reg, val)
                    if isinstance(val, Register):
                        self.stack[-1].release_register(val)
                result = self.stack[-1].allocate_register()
                self.emit("ldr", result, StackAddress(8, str(ptr_reg)))
                self.stack[-1].release_register(ptr_reg)
                return result

        # Detect method call: obj.method(args)
        if (
            isinstance(func_call.callee, BinaryOperator)
            and isinstance(func_call.callee.op, Dot)
            and isinstance(func_call.callee.lhs, Name)
            and isinstance(func_call.callee.rhs, Name)
            and func_call.callee.lhs.id not in self.imports
            and self.stack
        ):
            obj_name = func_call.callee.lhs.id
            method_name = func_call.callee.rhs.id
            var = self.stack[-1].variables.get(obj_name)
            if (
                var is not None
                and hasattr(var.type, "methods")
                and method_name in var.type.methods
            ):
                method = var.type.methods[method_name]
                obj_addr = self.stack[-1].get_variable_address(func_call.callee.lhs)
                self.emit("ldr", self._argregs[0], obj_addr)
                for arg, arg_reg in zip(func_call.args, self._argregs[1:]):
                    reg = self.compile_expression(arg.expression)
                    self.mov(arg_reg, reg)
                    if isinstance(reg, Register):
                        self.stack[-1].release_register(reg)
                self.emit("bl", method.label_name)
                return Register("x0")

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
