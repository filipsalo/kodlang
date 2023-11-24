"""A typechecker for the kod language."""

from kod import ast


class TypeChecker:
    """A typechecker for the kod language."""
    def __init__(self):
        self.function_types = {}

    def check_module(self, module):
        """Check a module for type errors."""
        for node in module.body:
            match node:
                case ast.FunctionDeclaration() | ast.ExternalFunctionDeclaration():
                    self.function_types[node.name] = [
                        param.type for param in node.params
                    ]
        for statement in module.body:
            self.check_statement(statement)

    def check_statement(self, node):
        """Check a statement for type errors."""
        match node:
            case ast.FunctionCall():
                self.check_function_call(node)
            case ast.FunctionDeclaration():
                for statement in node.body:
                    self.check_statement(statement)
            case ast.ExternalFunctionDeclaration():
                pass
            case ast.VariableDeclaration():
                pass
            case ast.Assignment():
                pass
            case _:
                raise ValueError(f"Don't know how to type check a {type(node)}")

    def check_function_call(self, node):
        """Check a function call for type errors."""
        self.verify_arguments(node.callee.id, node.args)

    def verify_arguments(self, function_name, arguments):
        """Verify that the given arguments match the expected types."""
        if function_name not in self.function_types:
            raise ValueError(f"Function '{function_name}' not found")

        expected_arg_types = self.function_types[function_name]

        if len(arguments) != len(expected_arg_types):
            raise ValueError(
                f"Expected {len(expected_arg_types)} arguments, but got {len(arguments)}"
            )

        for arg, expected_type in zip(arguments, expected_arg_types):
            if arg.type is None:
                arg.type = expected_type
            if arg.type != expected_type:
                raise TypeError(
                    f"Expected argument of type '{expected_type.name}', but got '{arg.type.name}'"
                )
