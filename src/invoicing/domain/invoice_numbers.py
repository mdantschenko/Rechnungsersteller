"""Consecutive invoice numbers shared by all customers.

A number is handed out when an invoice is released, not when a draft is
created, so discarded drafts leave no gap in the sequence.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class NumberSequence:
    """Tracks which invoice number comes next."""

    start: int
    last_assigned: int | None = None

    def peek(self) -> int:
        """The number the next release will get, without consuming it."""
        if self.last_assigned is None:
            return self.start
        return max(self.start, self.last_assigned + 1)

    def assign(self) -> int:
        """Consume and return the next number."""
        self.last_assigned = self.peek()
        return self.last_assigned

    def restart_at(self, number: int) -> None:
        """Move the starting number.

        Raises:
            ValueError: if ``number`` was already handed out, which would make
                two invoices carry the same number.
        """
        if self.last_assigned is not None and number <= self.last_assigned:
            raise ValueError(
                f"cannot restart at {number}: {self.last_assigned} is already assigned"
            )
        self.start = number
