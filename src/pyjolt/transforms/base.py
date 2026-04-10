"""Abstract base class for all transforms."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Transform(ABC):
    """Abstract base for all JOLT-style transforms."""

    @abstractmethod
    def apply(self, input_data: Any) -> Any:
        """Apply this transform to *input_data* and return the result.

        Parameters
        ----------
        input_data:
            The JSON-compatible Python object to transform.

        Returns
        -------
        Any
            A new JSON-compatible Python object (the transform never mutates
            its input).
        """
