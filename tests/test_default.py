"""Tests for the Default transform."""

from __future__ import annotations

import pytest

from pyjolt.transforms import Default


def default(spec, data):
    return Default(spec).apply(data)


class TestDefault:
    def test_fills_missing_key(self):
        result = default({"status": "unknown"}, {"name": "test"})
        assert result == {"name": "test", "status": "unknown"}

    def test_does_not_overwrite_existing(self):
        result = default({"status": "unknown"}, {"status": "active"})
        assert result == {"status": "active"}

    def test_fills_null_value(self):
        result = default({"count": 0}, {"count": None})
        assert result == {"count": 0}

    def test_nested_default(self):
        spec = {"meta": {"version": 1, "author": "anon"}}
        data = {"meta": {"version": 2}}
        result = default(spec, data)
        assert result["meta"]["version"] == 2
        assert result["meta"]["author"] == "anon"

    def test_creates_nested_object_if_missing(self):
        spec = {"meta": {"version": 1}}
        result = default(spec, {"name": "foo"})
        assert result["meta"] == {"version": 1}

    def test_multiple_defaults(self):
        spec = {"a": 1, "b": 2, "c": 3}
        result = default(spec, {"b": 99})
        assert result == {"a": 1, "b": 99, "c": 3}

    def test_deep_nesting(self):
        spec = {"x": {"y": {"z": 42}}}
        result = default(spec, {})
        assert result["x"]["y"]["z"] == 42

    def test_list_input_applies_to_each_element(self):
        result = Default({"flag": False}).apply([{"a": 1}, {"a": 2, "flag": True}])
        assert result[0] == {"a": 1, "flag": False}
        assert result[1] == {"a": 2, "flag": True}

    def test_wildcard_applies_to_all_keys(self):
        spec = {"*": {"active": True}}
        data = {"alice": {"name": "Alice"}, "bob": {"name": "Bob", "active": False}}
        result = default(spec, data)
        assert result["alice"]["active"] is True
        assert result["bob"]["active"] is False  # not overwritten

    def test_non_dict_input_returned_unchanged(self):
        assert default({"a": 1}, 42) == 42
        assert default({"a": 1}, "hello") == "hello"

    def test_empty_spec(self):
        data = {"a": 1, "b": 2}
        assert default({}, data) == data

    def test_string_default_value(self):
        result = default({"label": "N/A"}, {})
        assert result == {"label": "N/A"}

    def test_list_default_value(self):
        result = default({"tags": []}, {"name": "x"})
        assert result == {"name": "x", "tags": []}
