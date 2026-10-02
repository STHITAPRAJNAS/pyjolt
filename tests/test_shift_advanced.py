"""Tests for advanced Shift features: $N (key-as-value) and #constant."""

from __future__ import annotations

from pyjolt.transforms import Shift


def shift(spec, data):
    return Shift(spec).apply(data)


# ---------------------------------------------------------------------------
# $  /  $N  —  key name as value
# ---------------------------------------------------------------------------


class TestDollarKeyAsValue:
    def test_dollar_collects_key_names(self):
        """$ writes the matched key name to the output path."""
        result = shift({"*": {"$": "keys[]"}}, {"foo": 1, "bar": 2, "baz": 3})
        assert set(result["keys"]) == {"foo", "bar", "baz"}

    def test_dollar_zero_is_current_key(self):
        result = shift({"*": {"$0": "names[]"}}, {"alpha": 10, "beta": 20})
        assert set(result["names"]) == {"alpha", "beta"}

    def test_dollar_one_is_parent_key(self):
        """$1 writes the key matched one level above."""
        result = shift({"section": {"*": {"$1": "sectionNames[]"}}}, {"section": {"a": 1, "b": 2}})
        # $1 at depth of "*" match = key matched by literal "section" = "section"
        assert result["sectionNames"] == ["section", "section"]

    def test_dollar_alongside_regular_shift(self):
        """$ and regular field moves can coexist at the same spec level."""
        result = shift(
            {"items": {"*": {"name": "out[&1].name", "$": "out[&1].key"}}},
            {"items": [{"name": "Alice"}, {"name": "Bob"}]},
        )
        elements = result["out"]
        assert len(elements) == 2
        keys_found = {e.get("key") for e in elements}
        assert keys_found == {"0", "1"}

    def test_dollar_on_nested_wildcard(self):
        result = shift(
            {"*": {"*": {"$0": "inner[]", "$1": "outer[]"}}},
            {"a": {"x": 1}, "b": {"y": 2}},
        )
        assert set(result["inner"]) == {"x", "y"}
        assert set(result["outer"]) == {"a", "b"}

    def test_dollar_with_non_wildcard_literal(self):
        """$ also fires when the parent is a literal key (not wildcard)."""
        result = shift({"name": {"$": "fieldName"}}, {"name": "Alice"})
        # ctx[-1].key = "name"
        assert result["fieldName"] == "name"


# ---------------------------------------------------------------------------
# #constant  —  literal constant as value
# ---------------------------------------------------------------------------


class TestHashConstantAsValue:
    def test_hash_writes_literal_string(self):
        """#constant writes the literal string 'constant' to the output."""
        result = shift({"*": {"#photo": "types[]"}}, {"a": 1, "b": 2})
        # One "#photo" per wildcard match → two "photo" entries
        assert result["types"] == ["photo", "photo"]

    def test_hash_single_key(self):
        result = shift({"name": {"#person": "entityType"}}, {"name": "Alice"})
        assert result["entityType"] == "person"

    def test_hash_alongside_data_fields(self):
        """#type and regular field moves coexist."""
        result = shift(
            {"items": {"*": {"id": "out[&1].id", "#item": "out[&1].type"}}},
            {"items": [{"id": 1}, {"id": 2}]},
        )
        for elem in result["out"]:
            assert elem["type"] == "item"
        ids = {e["id"] for e in result["out"]}
        assert ids == {1, 2}

    def test_hash_constant_with_back_ref_in_output_path(self):
        """#constant can write to a path that uses &N back-references."""
        result = shift(
            {"*": {"#widget": "catalog.&1.kind"}},
            {"foo": {"x": 1}, "bar": {"x": 2}},
        )
        assert result["catalog"]["foo"]["kind"] == "widget"
        assert result["catalog"]["bar"]["kind"] == "widget"

    def test_hash_multiple_constants(self):
        result = shift(
            {"*": {"#typeA": "a[]", "#typeB": "b[]"}},
            {"x": 1},
        )
        assert result["a"] == ["typeA"]
        assert result["b"] == ["typeB"]


# ---------------------------------------------------------------------------
# Combined $  +  #  scenarios
# ---------------------------------------------------------------------------


class TestDollarAndHashCombined:
    def test_enrich_records_with_key_and_type(self):
        """Realistic: enrich each array element with its original key name
        and a literal type marker."""
        spec = {
            "sensors": {
                "*": {
                    "value": "readings[#2].value",
                    "$0": "readings[#2].sensorId",
                    "#sensor": "readings[#2].kind",
                }
            }
        }
        data = {"sensors": {"temp01": {"value": 22.5}, "hum03": {"value": 60}}}
        result = Shift(spec).apply(data)
        readings = result["readings"]
        assert len(readings) == 2
        ids = {r["sensorId"] for r in readings}
        assert ids == {"temp01", "hum03"}
        for r in readings:
            assert r["kind"] == "sensor"
            assert "value" in r


class TestExplicitArrayIndex:
    """Output paths with an explicit array index, e.g. ``items.[&2]`` or ``items[&1]``."""

    def test_issue_8_dot_bracket_backref(self):
        spec = {
            "items": {
                "*": {
                    "snippet": {
                        "title": "items.[&2].&",
                        "channelId": "items.[&2].&",
                        "resourceId": {"videoId": "items.[&3].&"},
                    }
                }
            }
        }
        data = {
            "kind": "list",
            "items": [
                {"snippet": {"title": "A", "channelId": "c1", "resourceId": {"videoId": "v1"}}},
                {"snippet": {"title": "B", "channelId": "c2", "resourceId": {"videoId": "v2"}}},
            ],
        }
        assert shift(spec, data) == {
            "items": [
                {"title": "A", "channelId": "c1", "videoId": "v1"},
                {"title": "B", "channelId": "c2", "videoId": "v2"},
            ]
        }

    def test_bracket_attached_to_key(self):
        spec = {"rows": {"*": {"id": "out[&1].key", "name": "out[&1].label"}}}
        data = {"rows": [{"id": 1, "name": "x"}, {"id": 2, "name": "y"}]}
        assert shift(spec, data) == {"out": [{"key": 1, "label": "x"}, {"key": 2, "label": "y"}]}

    def test_literal_index_pads_with_none(self):
        assert shift({"a": "arr[2]"}, {"a": 5}) == {"arr": [None, None, 5]}

    def test_index_as_leaf(self):
        spec = {"*": {"v": "vals[&1]"}}
        assert shift(spec, [{"v": "a"}, {"v": "b"}]) == {"vals": ["a", "b"]}

    def test_nested_indices(self):
        spec = {"m": {"*": {"*": "grid[&1][&0]"}}}
        assert shift(spec, {"m": [[1, 2], [3, 4]]}) == {"grid": [[1, 2], [3, 4]]}

    def test_non_integer_index_is_skipped(self):
        assert shift({"*": "out[&0]"}, {"foo": 1}) is None
