"""A typechecker for the kod language."""

from typing import Any

from kod import ast, tokens
from kod.exceptions import KodError
from kod.program import Program
from kod.span import Span


class TypeChecker:
    """A typechecker for the kod language."""

    def __init__(self, program: Program) -> None:
        self.program = program
        self.function_types: dict[str, ast.FunctionParamList] = {}
        self.stack: list[dict[str, Any]] = []
        self.errors: list[KodError] = []
        self._collected_modules: set[str] = set()
        self.current_module: ast.Module | None = None

    def error(self, msg: str, span: Span) -> None:
        """Add an error to the list of errors."""
        err = KodError(msg, span)
        self.errors.append(err)

    def check(self) -> bool:
        """Check the program for type errors."""
        for module in self.program:
            self.collect_functions(module)
        for module in self.program:
            self.check_module(module)
        return not self.errors

    def collect_functions(self, module: ast.Module) -> None:
        """Collect all function declarations."""
        key = str(module.canonical_name)
        if key in self._collected_modules:
            return
        self._collected_modules.add(key)
        for node in module.body:
            match node:
                case ast.FunctionDeclaration() | ast.ExternalFunctionDeclaration():
                    self.function_types[node.name] = node.params
                case ast.Import():
                    path = module.canonical_name.parent / node.module_name
                    self.collect_functions(self.program.get_module(path))

    def check_module(self, module: ast.Module) -> None:
        """Check a module for type errors."""
        self.current_module = module
        self.stack.append({})
        for statement in module.body:
            self.check_statement(statement)
        self.stack.pop()
        self.current_module = None

    def check_statement(self, node: ast.Statement) -> None:
        """Check a statement for type errors."""
        dbg("node", node)
        match node:
            case ast.FunctionCall():
                self.check_function_call(node)
            case ast.FunctionDeclaration():
                self.stack.append(
                    {param.variable.id: param.variable for param in node.params}
                )
                for statement in node.body:
                    self.check_statement(statement)
                self.stack.pop()
            case ast.ExternalFunctionDeclaration():
                pass
            case ast.VariableDeclaration():
                self.check_variable_declaration(node)
            case ast.IfStatement(_, true_branch, false_branch):
                for statement in true_branch:
                    self.check_statement(statement)
                for statement in false_branch:
                    self.check_statement(statement)
            case ast.ForStatement(_, body):
                for statement in body:
                    self.check_statement(statement)
            case ast.Return(expression):
                self.check_expression(expression)
            case ast.Assignment(_, rhs):
                self.check_expression(rhs)
            case ast.Import():
                pass

    def check_expression(self, node: ast.ASTNode) -> None:
        """Check an expression for type errors."""
        match node:
            case ast.FunctionCall():
                self.check_function_call(node)
            case ast.BinaryOperator(lhs, _, rhs):
                self.check_expression(lhs)
                self.check_expression(rhs)

    def check_variable_declaration(self, node: ast.VariableDeclaration) -> None:
        """Check a function declaration for type errors."""
        if node.variable.id in self.stack[-1]:
            self.error(f"Variable '{node.variable.id}' already declared", node.span)

        self.stack[-1][node.variable.id] = node

    def check_function_call(self, node) -> None:
        """Check a function call for type errors."""
        dbg(type(node.callee), node.callee)
        match node.callee:
            case ast.Name() as callee:
                dbg("got name", callee.id)
                self.verify_arguments(callee, node.args)
            case ast.BinaryOperator(lhs, op, rhs) if isinstance(op, tokens.Dot):
                import_node = self.current_module.names.get(lhs.id)
                if not isinstance(import_node, ast.Import):
                    self.error(f"'{lhs.id}' is not an imported module", lhs.span)
                    return
                path = self.current_module.resolve_import(import_node.module_name)
                imported_module = self.program.get_module(path)
                declaration = imported_module.names[rhs.id]
                self.verify_arguments(declaration, node.args)

    def lookup(self, name: ast.Name) -> Any:
        """Look up a name in the current scope."""
        for scope in reversed(self.stack):
            if name.id in scope:
                return scope[name.id]
        self.error(f"Name '{name.id}' not found", name.span)

    def verify_arguments(self, function, arguments) -> None:
        """Verify that the given arguments match the expected types."""
        params = self.function_types.get(
            function.name
            if isinstance(function, ast.FunctionDeclaration)
            else function.id
        )
        if params is None:
            return self.error(
                "Callee is not a function",
                function.span,
            )

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
            if isinstance(arg.expression, ast.Name):
                declaration = self.lookup(arg.expression)
                if declaration is not None:
                    arg_type = (
                        declaration.type
                        if isinstance(declaration, ast.Variable)
                        else None
                    )
                    if arg_type is not None and arg_type != param.variable.type:
                        self.error(
                            f"Expected argument of type '{param.variable.type}', "
                            f"but got '{arg_type}'",
                            arg.span,
                        )
