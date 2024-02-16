"""Helper class for representing spans in source files."""
import dataclasses
from pathlib import Path


@dataclasses.dataclass
class Span:
    """A span between two positions in a source file."""

    filename: Path
    start: int
    end: int

    def __repr__(self):
        return f"<{self.filename}:{self.start}-{self.end}>"

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
