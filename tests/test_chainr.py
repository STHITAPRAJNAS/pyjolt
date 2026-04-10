"""Tests for Chainr orchestration."""

from __future__ import annotations

import pytest

from pyjolt import Chainr
from pyjolt.exceptions import SpecError
from pyjolt.transforms import Default, Remove, Shift, Sort


class TestChainrFromSpec:
    def test_single_shift(self):
        chain = Chainr.from_spec([{"operation": "shift", "spec": {"a": "b"}}])
        assert chain.apply({"a": 1}) == {"b": 1}

    def test_shift_then_default(self):
        spec = [
            {"operation": "shift", "spec": {"rating": "Rating"}},
            {"operation": "default", "spec": {"Rating": 0}},
        ]
        chain = Chainr.from_spec(spec)
        assert chain.apply({"rating": 4.5}) == {"Rating": 4.5}
        assert chain.apply({}) == {"Rating": 0}

    def test_shift_then_remove(self):
        spec = [
            {"operation": "shift", "spec": {"a": "x", "b": "y", "secret": "secret"}},
            {"operation": "remove", "spec": {"secret": ""}},
        ]
        chain = Chainr.from_spec(spec)
        result = chain.apply({"a": 1, "b": 2, "secret": "pass"})
        assert result == {"x": 1, "y": 2}

    def test_shift_then_sort(self):
        spec = [
            {"operation": "shift", "spec": {"c": "c", "a": "a", "b": "b"}},
            {"operation": "sort"},
        ]
        chain = Chainr.from_spec(spec)
        result = chain.apply({"c": 3, "a": 1, "b": 2})
        assert list(result.keys()) == ["a", "b", "c"]

    def test_modify_overwrite(self):
        spec = [
            {"operation": "shift", "spec": {"score": "score"}},
            {"operation": "modify-overwrite-beta", "spec": {"score": "=toInteger"}},
        ]
        chain = Chainr.from_spec(spec)
        assert chain.apply({"score": "42"}) == {"score": 42}

    def test_modify_default(self):
        spec = [
            {"operation": "shift", "spec": {"name": "name"}},
            {"operation": "modify-default-beta", "spec": {"status": "active"}},
        ]
        chain = Chainr.from_spec(spec)
        assert chain.apply({"name": "Alice"}) == {"name": "Alice", "status": "active"}

    def test_cardinality(self):
        spec = [
            {"operation": "shift", "spec": {"tags": "tags"}},
            {"operation": "cardinality", "spec": {"tags": "MANY"}},
        ]
        chain = Chainr.from_spec(spec)
        assert chain.apply({"tags": "python"}) == {"tags": ["python"]}
        assert chain.apply({"tags": ["a", "b"]}) == {"tags": ["a", "b"]}

    def test_sort_with_no_spec(self):
        chain = Chainr.from_spec([{"operation": "sort"}])
        result = chain.apply({"b": 2, "a": 1})
        assert list(result.keys()) == ["a", "b"]

    def test_empty_spec_list(self):
        chain = Chainr.from_spec([])
        assert chain.apply({"a": 1}) == {"a": 1}


class TestChainrInstantiation:
    def test_from_transform_instances(self):
        chain = Chainr([Shift({"x": "y"}), Default({"y": 0})])
        assert chain.apply({"x": 5}) == {"y": 5}
        assert chain.apply({}) == {"y": 0}

    def test_len(self):
        chain = Chainr([Shift({"a": "b"}), Sort({})])
        assert len(chain) == 2

    def test_repr(self):
        chain = Chainr([Shift({"a": "b"}), Sort({})])
        assert "Shift" in repr(chain)
        assert "Sort" in repr(chain)


class TestChainrErrors:
    def test_unknown_operation_raises(self):
        with pytest.raises(SpecError, match="Unknown operation"):
            Chainr.from_spec([{"operation": "fakeOp", "spec": {}}])

    def test_missing_operation_raises(self):
        with pytest.raises(SpecError, match="missing 'operation'"):
            Chainr.from_spec([{"spec": {"a": "b"}}])

    def test_non_list_spec_raises(self):
        with pytest.raises(SpecError):
            Chainr.from_spec({"operation": "shift"})  # type: ignore[arg-type]

    def test_non_dict_entry_raises(self):
        with pytest.raises(SpecError):
            Chainr.from_spec(["not a dict"])  # type: ignore[arg-type]


class TestChainrComplexPipeline:
    def test_full_etl_pipeline(self):
        """Simulate a realistic ETL pipeline."""
        spec = [
            {
                "operation": "shift",
                "spec": {
                    "user": {
                        "id": "userId",
                        "name": "userName",
                        "email": "contact.email",
                        "role": "permissions.role",
                    }
                },
            },
            {
                "operation": "default",
                "spec": {
                    "permissions": {"role": "viewer"},
                    "contact": {"email": ""},
                },
            },
            {
                "operation": "modify-overwrite-beta",
                "spec": {"userName": "=toUpperCase"},
            },
        ]
        chain = Chainr.from_spec(spec)

        result = chain.apply(
            {"user": {"id": 1, "name": "alice", "email": "alice@example.com", "role": "admin"}}
        )
        assert result["userId"] == 1
        assert result["userName"] == "ALICE"
        assert result["contact"]["email"] == "alice@example.com"
        assert result["permissions"]["role"] == "admin"

    def test_array_processing_pipeline(self):
        """Process a list of records through a pipeline."""
        spec = [
            {"operation": "shift", "spec": {"score": "score", "label": "label"}},
            {"operation": "modify-overwrite-beta", "spec": {"score": "=toDouble"}},
            {"operation": "default", "spec": {"label": "N/A"}},
        ]
        chain = Chainr.from_spec(spec)

        records = [
            {"score": "3.5", "label": "good"},
            {"score": "4"},
            {"score": "5", "label": "perfect"},
        ]
        results = [chain.apply(r) for r in records]
        assert results[0] == {"score": 3.5, "label": "good"}
        assert results[1] == {"score": 4.0, "label": "N/A"}
        assert results[2] == {"score": 5.0, "label": "perfect"}
