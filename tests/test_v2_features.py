"""Tests for behaviour added in 2.0: define mode, context, custom functions, aliases."""

from __future__ import annotations

import copy

import pytest

from pyjolt import MISSING, Chainr, ModifyDefault, ModifyDefine, ModifyOverwrite, Shift
from pyjolt.exceptions import SpecError


class TestModifyDefine:
    def test_only_writes_missing_keys(self):
        result = ModifyDefine({"a": 1, "b": 2}).apply({"a": None})
        assert result == {"a": None, "b": 2}

    def test_default_writes_null_keys_too(self):
        result = ModifyDefault({"a": 1, "b": 2}).apply({"a": None})
        assert result == {"a": 1, "b": 2}

    def test_chainr_operation_name(self):
        chain = Chainr.from_spec([{"operation": "modify-define-beta", "spec": {"x": "new"}}])
        assert chain.apply({"x": "kept"}) == {"x": "kept"}
        assert chain.apply({}) == {"x": "new"}

    def test_per_key_mode_prefix(self):
        # "+" overwrites even inside a define spec
        result = ModifyDefine({"+a": 1, "b": 2}).apply({"a": 0, "b": 0})
        assert result == {"a": 1, "b": 0}


class TestContext:
    def test_caret_reads_from_context(self):
        result = ModifyOverwrite({"currency": "^defaults.currency"}).apply(
            {"currency": None}, {"defaults": {"currency": "EUR"}}
        )
        assert result == {"currency": "EUR"}

    def test_chainr_passes_context_to_modify(self):
        chain = Chainr.from_spec(
            [
                {"operation": "shift", "spec": {"price": "amount"}},
                {"operation": "modify-overwrite-beta", "spec": {"unit": "^unit"}},
            ]
        )
        assert chain.apply({"price": 5}, context={"unit": "kg"}) == {"amount": 5, "unit": "kg"}

    def test_missing_context_leaves_value(self):
        assert ModifyOverwrite({"a": "^nope"}).apply({"a": 1}) == {"a": 1}


class TestCustomFunctions:
    def test_custom_function(self):
        double = ModifyOverwrite({"n": "=double"}, functions={"double": lambda x: x * 2})
        assert double.apply({"n": 21}) == {"n": 42}

    def test_custom_function_with_args(self):
        spec = {"full": "=fullName(@(1,first),@(1,last))"}
        fns = {"fullName": lambda first, last: f"{first} {last}"}
        result = ModifyOverwrite(spec, functions=fns).apply({"first": "Ada", "last": "Lovelace"})
        assert result["full"] == "Ada Lovelace"

    def test_returning_missing_leaves_value(self):
        fn = ModifyOverwrite({"n": "=skip"}, functions={"skip": lambda *_: MISSING})
        assert fn.apply({"n": 1}) == {"n": 1}


class TestJavaOperationNames:
    @pytest.mark.parametrize(
        "operation",
        ["com.bazaarvoice.jolt.Shiftr", "shift"],
    )
    def test_shift_aliases(self, operation):
        chain = Chainr.from_spec([{"operation": operation, "spec": {"a": "b"}}])
        assert chain.apply({"a": 1}) == {"b": 1}

    def test_unknown_operation(self):
        with pytest.raises(SpecError):
            Chainr.from_spec([{"operation": "com.example.Nope", "spec": {}}])


class TestNoInputMutation:
    def test_chainr_does_not_mutate_input(self):
        data = {"items": [{"n": "1", "tags": None}], "drop": True}
        before = copy.deepcopy(data)
        Chainr.from_spec(
            [
                {"operation": "shift", "spec": {"items": "items", "drop": "drop"}},
                {
                    "operation": "modify-overwrite-beta",
                    "spec": {"items": {"*": {"n": "=toInteger"}}},
                },
                {"operation": "default", "spec": {"items[]": {"*": {"tags": []}}}},
                {"operation": "cardinality", "spec": {"items": {"*": {"tags": "MANY"}}}},
                {"operation": "remove", "spec": {"drop": ""}},
                {"operation": "sort"},
            ]
        ).apply(data)
        assert data == before

    def test_shift_does_not_alias_input_lists(self):
        data = {"a": [1], "b": 2}
        result = Shift({"a": "x", "b": "x"}).apply(data)
        assert result == {"x": [1, 2]}
        assert data == {"a": [1], "b": 2}
