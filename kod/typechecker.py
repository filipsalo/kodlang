"""A typechecker for the kod language."""

from typing import Any

from kod import ast
from kod.exceptions import KodError
from kod.program import Program
from kod.span import Span


class TypeChecker:
    """A typechecker for the kod language."""

    def __init__(self, program: Program) -> None:
        self.program = program
        self.function_types: dict[str, ast.FunctionParamList] = {}
        self.stack: list[dict[str, Any]] = [{}]
        self.errors: list[KodError] = []

    def error(self, msg: str, span: Span) -> None:
        """Add an error to the list of errors."""
        err = KodError(msg, span)
        self.errors.append(err)

    def check(self) -> bool:
        """Check the program for type errors."""
        for module in self.program:
            self.check_module(module)
        return not self.errors

    def check_module(self, module: ast.Module) -> None:
        """Check a module for type errors."""
        for node in module.body + self.program.builtins.body:
            match node:
                case ast.FunctionDeclaration() | ast.ExternalFunctionDeclaration():
                    self.function_types[node.name] = node.params
        for statement in module.body:
            self.check_statement(statement)

    def check_statement(self, node: ast.Statement) -> None:
        """Check a statement for type errors."""
        match node:
            case ast.FunctionCall():
                self.check_function_call(node)
            case ast.FunctionDeclaration():
                self.stack.append(
                    {param.variable.id: param.variable for param in node.params}
                )
                for statement in node.body:
                    self.check_statement(statement)
            case ast.ExternalFunctionDeclaration():
                pass
            case ast.VariableDeclaration():
                self.check_variable_declaration(node)

    def check_variable_declaration(self, node: ast.VariableDeclaration) -> None:
        """Check a function declaration for type errors."""
        if node.variable.id in self.stack[-1]:
            self.error(f"Variable '{node.variable.id}' already declared", node.span)

        self.stack[-1][node.variable.id] = node

    def check_function_call(self, node) -> None:
        """Check a function call for type errors."""
        self.verify_arguments(node.callee.id, node.args)

    def verify_arguments(self, function_name, arguments) -> None:
        """Verify that the given arguments match the expected types."""
        if function_name not in self.function_types:
            self.error(
                f"Function '{function_name}' not found",
                function_name.span,
            )

        params = self.function_types[function_name]

        if len(arguments) != len(params):
            self.error(
                f"Expected {len(params)} arguments, but got {len(arguments)}",
                arguments.span,
            )

        for arg, param in zip(arguments, params):
            if not arg.label and not param.anonymous:
                self.error(
                    f"Expected argument '{param.variable.id}' to be labeled",
                    arg.span,
                )
            if isinstance(arg.expression, ast.Variable):
                if arg.expression.id not in self.stack[-1]:
                    self.error(
                        f"Variable '{arg.expression.id}' not found",
                        arg.span,
                    )
                arg_type = self.stack[-1][arg.expression.id].type
                if arg_type != param.variable.type:
                    self.error(
                        f"Expected argument of type '{param.variable.type}', "
                        f"but got '{arg.expression.type}'",
                        arg.span,
                    )
