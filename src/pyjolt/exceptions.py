"""Exceptions for the pyjolt library."""

from __future__ import annotations


class PyJoltError(Exception):
    """Base exception for all pyjolt errors."""


class SpecError(PyJoltError):
    """Raised when a transform specification is invalid."""


class TransformError(PyJoltError):
    """Raised when a transform cannot be applied to the input."""
