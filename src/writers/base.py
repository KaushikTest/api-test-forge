from abc import ABC, abstractmethod

from models import TestCase


class Writer(ABC):
    """A Writer turns format-agnostic TestCases into a concrete output file."""

    @abstractmethod
    def write(self, cases: list[TestCase], out_dir: str) -> str:
        """Write cases to out_dir, return the path of the file(s) written."""
        raise NotImplementedError
