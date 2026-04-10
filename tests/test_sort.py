"""Tests for the Sort transform."""

from __future__ import annotations

import pytest

from pyjolt.transforms import Sort


def sort(data):
    return Sort({}).apply(data)


class TestSort:
    def test_sorts_top_level_keys(self):
        result = sort({"b": 2, "a": 1, "c": 3})
        assert list(result.keys()) == ["a", "b", "c"]

    def test_sorts_nested_keys(self):
        result = sort({"z": {"b": 2, "a": 1}, "a": 1})
        assert list(result.keys()) == ["a", "z"]
        assert list(result["z"].keys()) == ["a", "b"]

    def test_leaves_list_order_unchanged(self):
        result = sort({"items": [3, 1, 2]})
        assert result["items"] == [3, 1, 2]

    def test_sorts_dicts_inside_lists(self):
        result = sort({"data": [{"b": 2, "a": 1}, {"z": 26, "a": 1}]})
        assert list(result["data"][0].keys()) == ["a", "b"]
        assert list(result["data"][1].keys()) == ["a", "z"]

    def test_empty_dict(self):
        assert sort({}) == {}

    def test_scalar_passthrough(self):
        assert sort(42) == 42
        assert sort("hello") == "hello"
        assert sort(None) is None

    def test_deeply_nested(self):
        data = {"c": {"b": {"a": 1, "z": 2}}, "a": 0}
        result = sort(data)
        assert list(result.keys()) == ["a", "c"]
        assert list(result["c"]["b"].keys()) == ["a", "z"]

    def test_list_of_scalars(self):
        assert sort([3, 1, 2]) == [3, 1, 2]  # order preserved for lists

    def test_sort_with_no_spec(self):
        s = Sort()
        result = s.apply({"b": 1, "a": 2})
        assert list(result.keys()) == ["a", "b"]
