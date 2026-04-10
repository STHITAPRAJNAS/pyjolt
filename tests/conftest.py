"""Shared pytest fixtures and helpers."""

from __future__ import annotations


def assert_transform(transform_fn, input_data, expected):
    """Apply *transform_fn* to *input_data* and compare with *expected*."""
    result = transform_fn(input_data)
    assert result == expected, f"\nInput:    {input_data}\nExpected: {expected}\nGot:      {result}"
