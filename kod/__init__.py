import builtins
import sys


def debug_print(*things):
    """Print to stderr."""
    print("\033[94m", file=sys.stderr, end="")
    try:
        print(*things, file=sys.stderr, end="")
    finally:
        print("\033[00m", file=sys.stderr)


setattr(builtins, "dbg", debug_print)
