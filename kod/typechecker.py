"""A typechecker for the kod language."""

from kod import ast

from kod.exceptions import KodSyntaxError


class TypeChecker:
    """A typechecker for the kod language."""

    def __init__(self, program):
        self.program = program
        self.function_types = {}
        self.stack = [{}]

    def check(self):
        """Check the program for type errors."""
        for module in self.program:
            self.check_module(module.ast)

    def check_module(self, module):
        """Check a module for type errors."""
        builtins = self.program.get_module("builtins")
        for node in module.body + builtins.ast.body:
            match node:
                case (
                    ast.ParsedFunctionDeclaration()
                    | ast.ParsedExternalFunctionDeclaration()
                ):
                    self.function_types[node.name] = node.params
        for statement in module.body:
            self.check_statement(statement)

    def check_statement(self, node):
        """Check a statement for type errors."""
        match node:
            case ast.ParsedFunctionCall():
                self.check_function_call(node)
            case ast.ParsedFunctionDeclaration():
                self.stack.append(
                    {param.variable.id: param.variable for param in node.params}
                )
                for statement in node.body:
                    self.check_statement(statement)
            case ast.ParsedExternalFunctionDeclaration():
                pass
            case ast.ParsedVariableDeclaration(node):
                self.check_variable_declaration(node)
            case ast.ParsedAssignment():
                pass
            case _:
                raise ValueError(f"Don't know how to type check a {type(node)}")

    def check_variable_declaration(self, node):
        """Check a function declaration for type errors."""
        if node.id in self.stack[-1]:
            raise ValueError(f"Variable '{node.name}' already declared")
        self.stack[-1][node.id] = node

    def check_function_call(self, node):
        """Check a function call for type errors."""
        self.verify_arguments(node.callee.id, node.args)

    def verify_arguments(self, function_name, arguments):
        """Verify that the given arguments match the expected types."""
        if function_name not in self.function_types:
            raise KodSyntaxError(
                f"Function '{function_name}' not found", function_name.span
            )

        params = self.function_types[function_name]

        if len(arguments) != len(params):
            raise KodSyntaxError(
                f"Expected {len(params)} arguments, but got {len(arguments)}",
                arguments[0].span | arguments[-1].span,
            )

        for arg, param in zip(arguments, params):
            if not arg.label and not param.anonymous:
                raise ValueError(
                    f"Expected argument '{param.variable.id}' to be labeled"
                )
            if isinstance(arg.expression, ast.ParsedVariable):
                if arg.expression.id not in self.stack[-1]:
                    raise KodSyntaxError(
                        f"Variable '{arg.expression.id}' not found",
                        arg.span,
                    )
                arg_type = self.stack[-1][arg.expression.id].type
                if arg_type != param.variable.type:
                    raise KodSyntaxError(
                        f"Expected argument of type '{param.variable.type.name}', "
                        f"but got '{arg.expression.type}'",
                        arg.span,
                    )
