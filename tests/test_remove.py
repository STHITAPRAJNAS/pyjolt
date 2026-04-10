"""Tests for the Remove transform."""

from __future__ import annotations

from pyjolt.transforms import Remove


def remove(spec, data):
    return Remove(spec).apply(data)


class TestRemove:
    def test_removes_single_key(self):
        result = remove({"secret": ""}, {"name": "alice", "secret": "xyz"})
        assert result == {"name": "alice"}

    def test_keeps_unspecified_keys(self):
        result = remove({"a": ""}, {"a": 1, "b": 2, "c": 3})
        assert result == {"b": 2, "c": 3}

    def test_nested_remove(self):
        spec = {"meta": {"internal": ""}}
        data = {"value": 1, "meta": {"internal": True, "public": "yes"}}
        result = remove(spec, data)
        assert result == {"value": 1, "meta": {"public": "yes"}}

    def test_remove_all_with_wildcard(self):
        result = remove({"*": ""}, {"a": 1, "b": 2})
        assert result == {}

    def test_wildcard_removes_nested_keys(self):
        spec = {"items": {"*": {"_private": ""}}}
        data = {"items": {"x": {"_private": 1, "pub": 2}, "y": {"_private": 3, "pub": 4}}}
        result = remove(spec, data)
        assert result == {"items": {"x": {"pub": 2}, "y": {"pub": 4}}}

    def test_missing_key_is_harmless(self):
        result = remove({"nonexistent": ""}, {"a": 1})
        assert result == {"a": 1}

    def test_deep_nesting(self):
        spec = {"a": {"b": {"c": ""}}}
        data = {"a": {"b": {"c": 99, "d": 100}}}
        result = remove(spec, data)
        assert result == {"a": {"b": {"d": 100}}}

    def test_remove_multiple_keys(self):
        spec = {"pw": "", "token": ""}
        data = {"user": "bob", "pw": "s3cr3t", "token": "abc123"}
        result = remove(spec, data)
        assert result == {"user": "bob"}

    def test_non_dict_input_unchanged(self):
        assert remove({"a": ""}, 42) == 42
        assert remove({"a": ""}, [1, 2, 3]) == [1, 2, 3]

    def test_empty_spec(self):
        data = {"a": 1, "b": 2}
        assert remove({}, data) == data
