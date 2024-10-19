"""Helper class for representing spans in source files."""

import dataclasses
from pathlib import Path


@dataclasses.dataclass
class Span:
    """A span between two positions in a source file."""

    filename: Path
    start: int
    end: int

    @property
    def length(self) -> int:
        """Return the length of the span."""
        return self.end - self.start

    def __repr__(self):
        filename = self.filename
        if filename.is_relative_to(Path.cwd()):
            filename = self.filename.relative_to(Path.cwd())
        return f"<{filename}:{self.start}-{self.end}>"

    def __or__(self, other: "Span") -> "Span":
        """Return the span that covers both self and other."""
        return Span(
            self.filename, min(self.start, other.start), max(self.end, other.end)
        )

    def __ior__(self, other: "Span") -> "Span":
        """Update self to cover both self and other."""
        self.start = min(self.start, other.start)
        self.end = max(self.end, other.end)
        return self
