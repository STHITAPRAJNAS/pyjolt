"""Tests for the ModifyOverwrite and ModifyDefault transforms."""

from __future__ import annotations

import pytest

from pyjolt.exceptions import SpecError
from pyjolt.transforms import ModifyDefault, ModifyOverwrite


def overwrite(spec, data):
    return ModifyOverwrite(spec).apply(data)


def default_mod(spec, data):
    return ModifyDefault(spec).apply(data)


# ---------------------------------------------------------------------------
# Type conversion functions
# ---------------------------------------------------------------------------


class TestToInteger:
    def test_string_to_int(self):
        assert overwrite({"n": "=toInteger"}, {"n": "42"}) == {"n": 42}

    def test_float_to_int(self):
        assert overwrite({"n": "=toInteger"}, {"n": 3.9}) == {"n": 3}

    def test_null_with_default(self):
        assert overwrite({"n": "=toInteger(0)"}, {"n": None}) == {"n": 0}

    def test_already_int(self):
        assert overwrite({"n": "=toInteger"}, {"n": 7}) == {"n": 7}


class TestToDouble:
    def test_string_to_float(self):
        assert overwrite({"x": "=toDouble"}, {"x": "3.14"}) == {"x": 3.14}

    def test_int_to_float(self):
        result = overwrite({"x": "=toDouble"}, {"x": 5})
        assert result == {"x": 5.0}
        assert isinstance(result["x"], float)


class TestToString:
    def test_int_to_string(self):
        assert overwrite({"n": "=toString"}, {"n": 42}) == {"n": "42"}

    def test_null_stays_null(self):
        assert overwrite({"n": "=toString"}, {"n": None}) == {"n": None}


class TestToBoolean:
    def test_true_string(self):
        assert overwrite({"flag": "=toBoolean"}, {"flag": "true"}) == {"flag": True}

    def test_false_string(self):
        assert overwrite({"flag": "=toBoolean"}, {"flag": "false"}) == {"flag": False}

    def test_bool_passthrough(self):
        assert overwrite({"flag": "=toBoolean"}, {"flag": True}) == {"flag": True}

    def test_one_is_true(self):
        assert overwrite({"flag": "=toBoolean"}, {"flag": "1"}) == {"flag": True}


# ---------------------------------------------------------------------------
# String functions
# ---------------------------------------------------------------------------


class TestStringFunctions:
    def test_trim(self):
        assert overwrite({"s": "=trim"}, {"s": "  hello  "}) == {"s": "hello"}

    def test_to_upper(self):
        assert overwrite({"s": "=toUpperCase"}, {"s": "hello"}) == {"s": "HELLO"}

    def test_to_lower(self):
        assert overwrite({"s": "=toLowerCase"}, {"s": "HELLO"}) == {"s": "hello"}

    def test_split(self):
        result = overwrite({"s": "=split(|)"}, {"s": "a|b|c"})
        assert result == {"s": ["a", "b", "c"]}

    def test_join(self):
        result = overwrite({"s": "=join(-)"}, {"s": ["a", "b", "c"]})
        assert result == {"s": "a-b-c"}

    def test_concat(self):
        # concat(current_value, *extra_args) — all joined as strings
        result = overwrite({"s": "=concat(-suffix)"}, {"s": "hello"})
        assert result == {"s": "hello-suffix"}


# ---------------------------------------------------------------------------
# Numeric functions
# ---------------------------------------------------------------------------


class TestNumericFunctions:
    def test_abs_positive(self):
        assert overwrite({"n": "=abs"}, {"n": 5}) == {"n": 5}

    def test_abs_negative(self):
        assert overwrite({"n": "=abs"}, {"n": -5}) == {"n": 5}

    def test_min(self):
        assert overwrite({"n": "=min(10)"}, {"n": 3}) == {"n": 3}
        assert overwrite({"n": "=min(10)"}, {"n": 15}) == {"n": 10}

    def test_max(self):
        assert overwrite({"n": "=max(5)"}, {"n": 3}) == {"n": 5}
        assert overwrite({"n": "=max(5)"}, {"n": 8}) == {"n": 8}

    def test_int_sum(self):
        assert overwrite({"n": "=intSum(10)"}, {"n": 5}) == {"n": 15}

    def test_double_sum(self):
        result = overwrite({"n": "=doubleSum(0.5)"}, {"n": 1.5})
        assert abs(result["n"] - 2.0) < 1e-9

    def test_size_string(self):
        assert overwrite({"s": "=size"}, {"s": "hello"}) == {"s": 5}

    def test_size_list(self):
        assert overwrite({"l": "=size"}, {"l": [1, 2, 3]}) == {"l": 3}


# ---------------------------------------------------------------------------
# Collection functions
# ---------------------------------------------------------------------------


class TestCollectionFunctions:
    def test_squash_nulls(self):
        result = overwrite({"l": "=squashNulls"}, {"l": [1, None, 2, None, 3]})
        assert result == {"l": [1, 2, 3]}

    def test_recursively_squash_nulls(self):
        result = overwrite(
            {"l": "=recursivelySquashNulls"},
            {"l": [1, None, [2, None, 3]]},
        )
        assert result == {"l": [1, [2, 3]]}

    def test_noop(self):
        result = overwrite({"x": "=noop"}, {"x": 42})
        assert result == {"x": 42}


# ---------------------------------------------------------------------------
# Literal replacement
# ---------------------------------------------------------------------------


class TestLiteralReplacement:
    def test_integer_literal(self):
        assert overwrite({"n": 0}, {"n": 99}) == {"n": 0}

    def test_string_literal(self):
        assert overwrite({"s": "hello"}, {"s": "world"}) == {"s": "hello"}

    def test_none_literal(self):
        assert overwrite({"x": None}, {"x": 42}) == {"x": None}


# ---------------------------------------------------------------------------
# ModifyDefault vs ModifyOverwrite behaviour
# ---------------------------------------------------------------------------


class TestDefaultVsOverwrite:
    def test_overwrite_always_applies(self):
        result = overwrite({"n": "=toInteger"}, {"n": "42"})
        assert result == {"n": 42}

    def test_default_skips_existing_non_null(self):
        result = default_mod({"n": "=toInteger"}, {"n": "42"})
        assert result == {"n": "42"}  # not converted — already present

    def test_default_applies_to_null(self):
        # modify-default applies literal values to absent keys only
        # (null values are left for function expressions, literals apply to absent)
        result = default_mod({"n": 99}, {"n": None})
        assert result == {"n": 99}  # literal applied since value was None

    def test_default_applies_to_absent_key(self):
        result = default_mod({"count": 0}, {})
        assert result == {"count": 0}

    def test_overwrite_nested(self):
        spec = {"data": {"score": "=toInteger"}}
        data = {"data": {"score": "7"}}
        result = overwrite(spec, data)
        assert result == {"data": {"score": 7}}


# ---------------------------------------------------------------------------
# Wildcard spec key
# ---------------------------------------------------------------------------


class TestWildcard:
    def test_wildcard_converts_all(self):
        result = overwrite({"*": "=toInteger"}, {"a": "1", "b": "2", "c": "3"})
        assert result == {"a": 1, "b": 2, "c": 3}


# ---------------------------------------------------------------------------
# Edge cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    def test_unknown_function_raises(self):
        with pytest.raises(SpecError, match="Unknown modify function"):
            overwrite({"x": "=nonExistentFn"}, {"x": 1})

    def test_list_input_each_element_modified(self):
        result = ModifyOverwrite({"n": "=toInteger"}).apply([{"n": "1"}, {"n": "2"}])
        assert result == [{"n": 1}, {"n": 2}]

    def test_non_dict_passthrough(self):
        assert overwrite({"a": "=toInteger"}, 42) == 42

    def test_function_list_first_non_null_wins(self):
        spec = {"n": ["=toInteger", 0]}
        result = overwrite(spec, {"n": "5"})
        assert result == {"n": 5}
