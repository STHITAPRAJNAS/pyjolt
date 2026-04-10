"""Tests for the Cardinality transform."""

from __future__ import annotations

import pytest

from pyjolt.exceptions import SpecError
from pyjolt.transforms import Cardinality


def cardinality(spec, data):
    return Cardinality(spec).apply(data)


class TestCardinalityOne:
    def test_list_becomes_first_element(self):
        result = cardinality({"tags": "ONE"}, {"tags": ["a", "b", "c"]})
        assert result == {"tags": "a"}

    def test_scalar_stays_scalar(self):
        result = cardinality({"tag": "ONE"}, {"tag": "single"})
        assert result == {"tag": "single"}

    def test_empty_list_becomes_none(self):
        result = cardinality({"tags": "ONE"}, {"tags": []})
        assert result == {"tags": None}

    def test_one_element_list_unwrapped(self):
        result = cardinality({"x": "ONE"}, {"x": [42]})
        assert result == {"x": 42}


class TestCardinalityMany:
    def test_scalar_wrapped_in_list(self):
        result = cardinality({"tag": "MANY"}, {"tag": "python"})
        assert result == {"tag": ["python"]}

    def test_list_stays_list(self):
        result = cardinality({"tags": "MANY"}, {"tags": ["a", "b"]})
        assert result == {"tags": ["a", "b"]}

    def test_none_wrapped_in_list(self):
        result = cardinality({"x": "MANY"}, {"x": None})
        assert result == {"x": [None]}


class TestCardinalityMixed:
    def test_mixed_spec(self):
        spec = {"primary": "ONE", "tags": "MANY"}
        data = {"primary": ["first", "second"], "tags": "python"}
        result = cardinality(spec, data)
        assert result == {"primary": "first", "tags": ["python"]}

    def test_unspecified_keys_unchanged(self):
        result = cardinality({"a": "ONE"}, {"a": [1, 2], "b": [3, 4]})
        assert result["b"] == [3, 4]

    def test_wildcard_applies_to_all(self):
        result = cardinality({"*": "MANY"}, {"x": 1, "y": 2, "z": [3]})
        assert result == {"x": [1], "y": [2], "z": [3]}

    def test_nested_spec(self):
        spec = {"data": {"value": "ONE"}}
        data = {"data": {"value": [10, 20]}}
        result = cardinality(spec, data)
        assert result == {"data": {"value": 10}}


class TestCardinalityEdgeCases:
    def test_case_insensitive_one(self):
        result = cardinality({"x": "one"}, {"x": [1, 2]})
        assert result == {"x": 1}

    def test_case_insensitive_many(self):
        result = cardinality({"x": "many"}, {"x": 5})
        assert result == {"x": [5]}

    def test_invalid_mode_raises(self):
        with pytest.raises(SpecError):
            cardinality({"x": "INVALID"}, {"x": 1})

    def test_empty_spec(self):
        data = {"a": [1, 2], "b": "hello"}
        assert cardinality({}, data) == data

    def test_list_input_applies_to_each_element(self):
        spec = {"*": {"val": "ONE"}}
        data = [{"val": [1, 2]}, {"val": [3]}]
        result = cardinality(spec, data)
        assert result == [{"val": 1}, {"val": 3}]
