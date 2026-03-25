"""Sample Python module for testing tree-sitter parser."""

import os
from typing import List, Optional
from dataclasses import dataclass


@dataclass
class Person:
    """A person class."""

    name: str
    age: int

    def greet(self) -> str:
        """Return a greeting message."""
        return f"Hello, my name is {self.name}"

    def celebrate_birthday(self) -> None:
        """Increment age by 1."""
        self.age += 1


class Calculator:
    """A simple calculator class."""

    def __init__(self) -> None:
        self.history: List[float] = []

    def add(self, a: float, b: float) -> float:
        """Add two numbers."""
        result = a + b
        self.history.append(result)
        return result

    def subtract(self, a: float, b: float) -> float:
        """Subtract b from a."""
        result = a - b
        self.history.append(result)
        return result

    def get_history(self) -> List[float]:
        """Get calculation history."""
        return self.history.copy()


def standalone_function(x: int) -> int:
    """A standalone function."""
    return x * 2


def process_data(data: Optional[List[str]]) -> List[str]:
    """Process data with optional input."""
    if data is None:
        return []
    return [item.upper() for item in data]
