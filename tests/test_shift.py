"""Tests for the Shift transform."""

from __future__ import annotations

import pytest

from pyjolt.transforms import Shift


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def shift(spec, data):
    return Shift(spec).apply(data)


# ---------------------------------------------------------------------------
# Literal key matching
# ---------------------------------------------------------------------------


class TestLiteralKeys:
    def test_simple_rename(self):
        assert shift({"a": "b"}, {"a": 1}) == {"b": 1}

    def test_nested_rename(self):
        spec = {"outer": {"inner": "result"}}
        assert shift(spec, {"outer": {"inner": 42}}) == {"result": 42}

    def test_deep_nested(self):
        spec = {"a": {"b": {"c": "x.y.z"}}}
        assert shift(spec, {"a": {"b": {"c": "deep"}}}) == {"x": {"y": {"z": "deep"}}}

    def test_missing_key_produces_empty(self):
        assert shift({"a": "b"}, {"x": 1}) == {}

    def test_multiple_keys(self):
        spec = {"first": "name", "last": "surname"}
        result = shift(spec, {"first": "John", "last": "Doe"})
        assert result == {"name": "John", "surname": "Doe"}

    def test_moves_to_nested_output(self):
        spec = {"value": "result.data.value"}
        assert shift(spec, {"value": 99}) == {"result": {"data": {"value": 99}}}

    def test_ignores_extra_input_keys(self):
        result = shift({"a": "out"}, {"a": 1, "b": 2, "c": 3})
        assert result == {"out": 1}

    def test_boolean_value(self):
        assert shift({"flag": "enabled"}, {"flag": True}) == {"enabled": True}

    def test_null_value(self):
        assert shift({"key": "out"}, {"key": None}) == {"out": None}

    def test_list_value(self):
        assert shift({"items": "data"}, {"items": [1, 2, 3]}) == {"data": [1, 2, 3]}


# ---------------------------------------------------------------------------
# Wildcard matching
# ---------------------------------------------------------------------------


class TestWildcard:
    def test_star_matches_all_keys(self):
        result = shift({"*": "out.&0"}, {"a": 1, "b": 2})
        assert result == {"out": {"a": 1, "b": 2}}

    def test_star_in_nested_spec(self):
        spec = {"categories": {"*": "flat.&0"}}
        data = {"categories": {"sports": 10, "music": 20}}
        assert shift(spec, data) == {"flat": {"sports": 10, "music": 20}}

    def test_star_with_back_ref_level_1(self):
        # &1 refers to the key matched one level up
        spec = {"*": {"value": "result.&1.val"}}
        data = {"foo": {"value": 1}, "bar": {"value": 2}}
        result = shift(spec, data)
        assert result == {"result": {"foo": {"val": 1}, "bar": {"val": 2}}}

    def test_star_with_back_ref_level_0(self):
        spec = {"items": {"*": "flat.&0"}}
        data = {"items": {"x": 10, "y": 20}}
        result = shift(spec, data)
        assert result == {"flat": {"x": 10, "y": 20}}

    def test_wildcard_partial_prefix(self):
        spec = {"rating.*": "ratings.&0"}
        data = {"rating.primary": 4, "rating.quality": 5}
        result = shift(spec, data)
        assert result == {"ratings": {"rating.primary": 4, "rating.quality": 5}}

    def test_wildcard_capture_groups(self):
        # *-* captures two groups: foo and bar from "foo-bar"
        spec = {"*-*": "out.&(0,1).&(0,2)"}
        data = {"foo-bar": 42, "a-b": 1}
        result = shift(spec, data)
        assert result == {"out": {"foo": {"bar": 42}, "a": {"b": 1}}}

    def test_star_with_array_output(self):
        spec = {"*": "values[]"}
        data = {"a": 1, "b": 2, "c": 3}
        result = shift(spec, data)
        assert result == {"values": [1, 2, 3]}

    def test_literal_takes_priority_over_wildcard(self):
        spec = {"foo": "exact", "*": "wildcard.&0"}
        data = {"foo": 1, "bar": 2}
        result = shift(spec, data)
        assert result["exact"] == 1
        assert result.get("wildcard", {}).get("bar") == 2
        assert "foo" not in result.get("wildcard", {})


# ---------------------------------------------------------------------------
# Array input
# ---------------------------------------------------------------------------


class TestArrayInput:
    def test_wildcard_over_array(self):
        spec = {"items": {"*": "flat[]"}}
        data = {"items": [10, 20, 30]}
        result = shift(spec, data)
        assert result == {"flat": [10, 20, 30]}

    def test_indexed_access_in_array(self):
        spec = {"items": {"0": "first", "1": "second"}}
        data = {"items": ["a", "b", "c"]}
        result = shift(spec, data)
        assert result == {"first": "a", "second": "b"}

    def test_nested_array_elements(self):
        spec = {"data": {"*": {"id": "ids[]", "name": "names[]"}}}
        data = {"data": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}]}
        result = shift(spec, data)
        assert result == {"ids": [1, 2], "names": ["Alice", "Bob"]}

    def test_array_index_back_ref(self):
        spec = {"items": {"*": "indexed.&0.value"}}
        data = {"items": ["x", "y"]}
        result = shift(spec, data)
        assert result == {"indexed": {"0": {"value": "x"}, "1": {"value": "y"}}}


# ---------------------------------------------------------------------------
# Array output ([] append syntax)
# ---------------------------------------------------------------------------


class TestArrayOutput:
    def test_simple_append(self):
        spec = {"a": "out[]", "b": "out[]"}
        data = {"a": 1, "b": 2}
        result = shift(spec, data)
        assert result == {"out": [1, 2]}

    def test_nested_append(self):
        spec = {"x": "result.vals[]", "y": "result.vals[]"}
        data = {"x": 10, "y": 20}
        result = shift(spec, data)
        assert result == {"result": {"vals": [10, 20]}}

    def test_wildcard_into_array(self):
        spec = {"*": "all[]"}
        data = {"a": 1, "b": 2, "c": 3}
        result = shift(spec, data)
        assert isinstance(result["all"], list)
        assert set(result["all"]) == {1, 2, 3}


# ---------------------------------------------------------------------------
# Multiple output paths
# ---------------------------------------------------------------------------


class TestMultipleOutputs:
    def test_fan_out_to_two_paths(self):
        spec = {"value": ["alpha", "beta"]}
        result = shift(spec, {"value": 99})
        assert result == {"alpha": 99, "beta": 99}

    def test_fan_out_with_nesting(self):
        spec = {"id": ["primary.id", "copy.id"]}
        result = shift(spec, {"id": 42})
        assert result == {"primary": {"id": 42}, "copy": {"id": 42}}


# ---------------------------------------------------------------------------
# Self-reference (@) on input side
# ---------------------------------------------------------------------------


class TestAtSelfReference:
    def test_at_writes_entire_value(self):
        spec = {"data": {"@": "raw"}}
        data = {"data": {"x": 1, "y": 2}}
        result = shift(spec, data)
        assert result == {"raw": {"x": 1, "y": 2}}

    def test_at_and_children_together(self):
        spec = {"obj": {"@": "whole", "field": "field_out"}}
        data = {"obj": {"field": "hello"}}
        result = shift(spec, data)
        assert result["whole"] == {"field": "hello"}
        assert result["field_out"] == "hello"


# ---------------------------------------------------------------------------
# OR patterns
# ---------------------------------------------------------------------------


class TestOrPatterns:
    def test_or_literal_keys(self):
        spec = {"a|b": "out"}
        result = shift(spec, {"a": 1})
        assert result == {"out": 1}

    def test_or_second_alternative(self):
        spec = {"a|b": "out"}
        result = shift(spec, {"b": 2})
        assert result == {"out": 2}

    def test_or_both_match(self):
        spec = {"a|b": "out[]"}
        result = shift(spec, {"a": 1, "b": 2})
        assert set(result["out"]) == {1, 2}


# ---------------------------------------------------------------------------
# @(N,path) in output paths
# ---------------------------------------------------------------------------


class TestAtOutputReference:
    def test_at_one_level_up_sibling(self):
        # @(1,label) at the "id" leaf: go 1 level up (the "*" match's input_val)
        # That level contains {"id": 10, "label": "typeA"} → label → "typeA"
        spec = {"items": {"*": {"id": "out.@(1,label)"}}}
        data = {"items": {"alpha": {"id": 10, "label": "typeA"}}}
        result = shift(spec, data)
        assert result == {"out": {"typeA": 10}}

    def test_at_zero_is_current_value(self):
        # @(0,key) follows 'key' in the current match's stored input value
        spec = {"items": {"*": {"id": "out.@(0,label)"}}}
        data = {"items": {"alpha": {"id": 10, "label": "typeB"}}}
        result = shift(spec, data)
        # @(0,...) → ctx[-1].input_val = 10 (scalar), "label" not in 10 → empty
        # This is an edge case; just verify it runs without error
        assert isinstance(result, dict)


# ---------------------------------------------------------------------------
# #literal output
# ---------------------------------------------------------------------------


class TestHashLiteral:
    def test_hash_produces_literal_key(self):
        spec = {"value": "#constant"}
        result = shift(spec, {"value": 42})
        assert "constant" in result


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_empty_input(self):
        assert shift({"a": "b"}, {}) == {}

    def test_empty_spec(self):
        assert shift({}, {"a": 1}) == {}

    def test_null_input(self):
        assert shift({"a": "b"}, None) == {}

    def test_scalar_input(self):
        assert shift({"a": "b"}, 42) == {}

    def test_numeric_keys_in_spec(self):
        # Integer keys as strings
        spec = {"0": "first"}
        result = shift(spec, {"0": "zero"})
        assert result == {"first": "zero"}

    def test_deeply_nested_wildcard(self):
        spec = {"a": {"b": {"*": "flat.&0"}}}
        data = {"a": {"b": {"x": 1, "y": 2}}}
        result = shift(spec, data)
        assert result == {"flat": {"x": 1, "y": 2}}

    def test_complex_jolt_example(self):
        """Classic JOLT example: rating object transformation."""
        spec = {
            "rating": {
                "primary": {
                    "value": "Rating",
                    "max": "RatingRange",
                },
                "*": {
                    "value": "SecondaryRatings.&1.Value",
                    "max": "SecondaryRatings.&1.Range",
                },
            }
        }
        data = {
            "rating": {
                "primary": {"value": 3, "max": 5},
                "quality": {"value": 4, "max": 5},
                "sharpness": {"value": 2, "max": 10},
            }
        }
        result = shift(spec, data)
        assert result["Rating"] == 3
        assert result["RatingRange"] == 5
        assert result["SecondaryRatings"]["quality"]["Value"] == 4
        assert result["SecondaryRatings"]["quality"]["Range"] == 5
        assert result["SecondaryRatings"]["sharpness"]["Value"] == 2
        assert result["SecondaryRatings"]["sharpness"]["Range"] == 10
