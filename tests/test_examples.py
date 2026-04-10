"""Real-world integration examples.

Each test class represents a distinct domain scenario.  Every example also
serves as live documentation — the input, spec, and expected output are all
explicit, so failures are self-explanatory.
"""

from __future__ import annotations

from pyjolt import Chainr
from pyjolt.transforms import (
    Cardinality,
    Default,
    ModifyOverwrite,
    Remove,
    Shift,
    Sort,
)


# ---------------------------------------------------------------------------
# 1. E-commerce order normalisation
#    External checkout API  →  internal order schema
# ---------------------------------------------------------------------------


class TestEcommerceOrder:
    """Transform a raw checkout payload into the internal order schema."""

    RAW_ORDER = {
        "orderId": "ORD-9921",
        "customer": {
            "firstName": "Jane",
            "lastName": "Doe",
            "emailAddress": "jane.doe@example.com",
        },
        "lineItems": [
            {"sku": "ABC-1", "qty": 2, "unitPrice": "19.99"},
            {"sku": "XYZ-7", "qty": 1, "unitPrice": "5.49"},
        ],
        "shippingMethod": "express",
        "couponCode": None,
    }

    SPEC = [
        {
            "operation": "shift",
            "spec": {
                "orderId": "id",
                "customer": {
                    "firstName": "customer.first",
                    "lastName": "customer.last",
                    "emailAddress": "customer.email",
                },
                "lineItems": {
                    "*": {
                        "sku": "items[].sku",
                        "qty": "items[].quantity",
                        "unitPrice": "items[].price",
                    }
                },
                "shippingMethod": "shipping.method",
            },
        },
        {
            # Normalise prices from strings to floats
            "operation": "modify-overwrite-beta",
            "spec": {
                "items": {
                    "*": {"price": "=toDouble"}
                }
            },
        },
        {
            "operation": "default",
            "spec": {"shipping": {"method": "standard"}},
        },
        {
            "operation": "remove",
            "spec": {"couponCode": ""},
        },
    ]

    def test_order_id_mapped(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_ORDER)
        assert result["id"] == "ORD-9921"

    def test_customer_fields_renamed(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_ORDER)
        assert result["customer"] == {
            "first": "Jane",
            "last": "Doe",
            "email": "jane.doe@example.com",
        }

    def test_line_items_flattened_and_typed(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_ORDER)
        items = result["items"]
        assert len(items) == 2
        skus = {i["sku"] for i in items}
        assert skus == {"ABC-1", "XYZ-7"}
        for item in items:
            assert isinstance(item["price"], float)

    def test_shipping_method_preserved(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_ORDER)
        assert result["shipping"]["method"] == "express"

    def test_default_shipping_when_absent(self):
        order = dict(self.RAW_ORDER)
        order.pop("shippingMethod")
        result = Chainr.from_spec(self.SPEC).apply(order)
        assert result["shipping"]["method"] == "standard"

    def test_coupon_code_removed(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_ORDER)
        assert "couponCode" not in result


# ---------------------------------------------------------------------------
# 2. API response normalisation
#    GitHub-style paginated search response → slim item list
# ---------------------------------------------------------------------------


class TestApiResponseNormalisation:
    """Flatten a paginated API envelope and normalise each result record."""

    RAW_RESPONSE = {
        "total_count": 3,
        "incomplete_results": False,
        "items": [
            {
                "id": 101,
                "full_name": "acme/widget",
                "stargazers_count": 540,
                "language": "Python",
                "private": False,
            },
            {
                "id": 202,
                "full_name": "acme/gadget",
                "stargazers_count": 120,
                "language": None,
                "private": True,
            },
            {
                "id": 303,
                "full_name": "acme/doohickey",
                "stargazers_count": 12,
                "language": "Go",
                "private": False,
            },
        ],
    }

    SPEC = [
        {
            "operation": "shift",
            "spec": {
                "total_count": "meta.total",
                "items": {
                    "*": {
                        "id": "repos[].id",
                        "full_name": "repos[].name",
                        "stargazers_count": "repos[].stars",
                        "language": "repos[].language",
                        "private": "repos[].private",
                    }
                },
            },
        },
        {
            "operation": "default",
            "spec": {
                "repos": {
                    "*": {"language": "unknown"}
                }
            },
        },
        {
            "operation": "sort",
        },
    ]

    def test_meta_total(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_RESPONSE)
        assert result["meta"]["total"] == 3

    def test_repos_length(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_RESPONSE)
        assert len(result["repos"]) == 3

    def test_field_renaming(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_RESPONSE)
        ids = {r["id"] for r in result["repos"]}
        assert ids == {101, 202, 303}
        names = {r["name"] for r in result["repos"]}
        assert "acme/widget" in names

    def test_null_language_gets_default(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_RESPONSE)
        gadget = next(r for r in result["repos"] if r["id"] == 202)
        assert gadget["language"] == "unknown"

    def test_top_level_keys_sorted(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_RESPONSE)
        assert list(result.keys()) == sorted(result.keys())

    def test_incomplete_results_dropped(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_RESPONSE)
        assert "incomplete_results" not in result


# ---------------------------------------------------------------------------
# 3. User profile flattening
#    Nested CMS user  →  flat CRM record + PII strip
# ---------------------------------------------------------------------------


class TestUserProfileFlattening:
    """Flatten nested user data and strip PII before sending to CRM."""

    RAW_USER = {
        "userId": "U-42",
        "profile": {
            "displayName": "Bob Builder",
            "email": "bob@example.com",
            "phone": "+1-555-0100",
            "address": {
                "city": "Springfield",
                "country": "US",
            },
        },
        "account": {
            "plan": "pro",
            "trialEnds": None,
            "createdAt": "2023-01-15",
            "tags": ["beta", "early-adopter"],
        },
        "internal": {
            "passwordHash": "...",
            "sessionToken": "tok-xyz",
        },
    }

    SPEC = [
        {
            "operation": "shift",
            "spec": {
                "userId": "crm.id",
                "profile": {
                    "displayName": "crm.name",
                    "address": {
                        "city": "crm.city",
                        "country": "crm.country",
                    },
                },
                "account": {
                    "plan": "crm.plan",
                    "createdAt": "crm.joinDate",
                    "tags": "crm.tags",
                },
            },
        },
        {
            "operation": "default",
            "spec": {"crm": {"plan": "free", "tags": []}},
        },
        {
            "operation": "modify-overwrite-beta",
            "spec": {"crm": {"plan": "=toUpperCase"}},
        },
        {
            "operation": "cardinality",
            "spec": {"crm": {"tags": "MANY"}},
        },
    ]

    def test_id_and_name(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_USER)
        assert result["crm"]["id"] == "U-42"
        assert result["crm"]["name"] == "Bob Builder"

    def test_address_flattened(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_USER)
        assert result["crm"]["city"] == "Springfield"
        assert result["crm"]["country"] == "US"

    def test_plan_uppercased(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_USER)
        assert result["crm"]["plan"] == "PRO"

    def test_tags_always_list(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_USER)
        assert isinstance(result["crm"]["tags"], list)
        assert "beta" in result["crm"]["tags"]

    def test_pii_stripped(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_USER)
        # email, phone, passwordHash, sessionToken must not leak through
        import json
        flat = json.dumps(result)
        assert "bob@example.com" not in flat
        assert "+1-555-0100" not in flat
        assert "passwordHash" not in flat
        assert "sessionToken" not in flat

    def test_internal_block_stripped(self):
        result = Chainr.from_spec(self.SPEC).apply(self.RAW_USER)
        assert "internal" not in result

    def test_missing_tags_defaults_to_list(self):
        user = dict(self.RAW_USER)
        user["account"] = {"plan": "free", "createdAt": "2024-01-01"}
        result = Chainr.from_spec(self.SPEC).apply(user)
        assert result["crm"]["tags"] == []


# ---------------------------------------------------------------------------
# 4. IoT sensor log normalisation
#    Heterogeneous sensor readings  →  uniform time-series schema
# ---------------------------------------------------------------------------


class TestIoTSensorNormalisation:
    """Normalise sensor readings from three device types into one schema."""

    # Three device types emit subtly different payloads
    TEMP_SENSOR = {
        "device_id": "TEMP-01",
        "type": "temperature",
        "ts": "2024-03-10T12:00:00Z",
        "reading": {"celsius": "21.5", "unit": "C"},
        "battery_pct": "87",
    }

    HUMIDITY_SENSOR = {
        "device_id": "HUM-03",
        "type": "humidity",
        "ts": "2024-03-10T12:01:00Z",
        "reading": {"percent": "65", "unit": "%"},
        "battery_pct": "42",
    }

    PRESSURE_SENSOR = {
        "device_id": "PRES-07",
        "type": "pressure",
        "ts": "2024-03-10T12:02:00Z",
        "reading": {"hpa": "1013", "unit": "hPa"},
        # battery absent on older firmware
    }

    SPEC = [
        {
            "operation": "shift",
            "spec": {
                "device_id": "deviceId",
                "type": "sensorType",
                "ts": "timestamp",
                "reading": {
                    # temperature
                    "celsius": "value",
                    # humidity
                    "percent": "value",
                    # pressure
                    "hpa": "value",
                    "unit": "unit",
                },
                "battery_pct": "batteryPercent",
            },
        },
        {
            "operation": "modify-overwrite-beta",
            "spec": {
                "value": "=toDouble",
                "batteryPercent": "=toInteger",
            },
        },
        {
            "operation": "default",
            "spec": {"batteryPercent": -1},
        },
    ]

    def _transform(self, raw):
        return Chainr.from_spec(self.SPEC).apply(raw)

    def test_temperature_value_and_type(self):
        r = self._transform(self.TEMP_SENSOR)
        assert r["deviceId"] == "TEMP-01"
        assert r["sensorType"] == "temperature"
        assert r["value"] == 21.5
        assert r["unit"] == "C"
        assert r["batteryPercent"] == 87

    def test_humidity_value_and_unit(self):
        r = self._transform(self.HUMIDITY_SENSOR)
        assert r["value"] == 65.0
        assert r["unit"] == "%"
        assert r["batteryPercent"] == 42

    def test_pressure_value_and_unit(self):
        r = self._transform(self.PRESSURE_SENSOR)
        assert r["value"] == 1013.0
        assert r["unit"] == "hPa"

    def test_missing_battery_defaults_to_sentinel(self):
        r = self._transform(self.PRESSURE_SENSOR)
        assert r["batteryPercent"] == -1

    def test_timestamp_preserved(self):
        r = self._transform(self.TEMP_SENSOR)
        assert r["timestamp"] == "2024-03-10T12:00:00Z"

    def test_raw_reading_block_gone(self):
        r = self._transform(self.TEMP_SENSOR)
        assert "reading" not in r
        assert "celsius" not in r


# ---------------------------------------------------------------------------
# 5. README quick-start example (regression guard)
# ---------------------------------------------------------------------------


class TestReadmeQuickStart:
    """Ensure every code block shown in the README produces the stated output."""

    def test_rating_pipeline(self):
        spec = [
            {
                "operation": "shift",
                "spec": {
                    "rating": {
                        "primary": {"value": "Rating", "max": "RatingRange"},
                        "*": {
                            "value": "SecondaryRatings.&1.Value",
                            "max": "SecondaryRatings.&1.Range",
                        },
                    }
                },
            },
            {"operation": "default", "spec": {"Rating": 0}},
        ]
        result = Chainr.from_spec(spec).apply(
            {
                "rating": {
                    "primary": {"value": 3, "max": 5},
                    "quality": {"value": 4, "max": 5},
                    "sharpness": {"value": 2, "max": 10},
                }
            }
        )
        assert result["Rating"] == 3
        assert result["RatingRange"] == 5
        assert result["SecondaryRatings"]["quality"]["Value"] == 4
        assert result["SecondaryRatings"]["quality"]["Range"] == 5
        assert result["SecondaryRatings"]["sharpness"]["Value"] == 2
        assert result["SecondaryRatings"]["sharpness"]["Range"] == 10

    def test_shift_basic(self):
        s = Shift({"user": {"name": "profile.fullName", "age": "profile.years"}})
        assert s.apply({"user": {"name": "Alice", "age": 30}}) == {
            "profile": {"fullName": "Alice", "years": 30}
        }

    def test_shift_wildcard_capture(self):
        s = Shift({"*-*": "out.&(0,1).&(0,2)"})
        assert s.apply({"foo-bar": 42}) == {"out": {"foo": {"bar": 42}}}

    def test_shift_array_output(self):
        s = Shift({"a": "vals[]", "b": "vals[]"})
        assert s.apply({"a": 1, "b": 2}) == {"vals": [1, 2]}

    def test_shift_fan_out(self):
        s = Shift({"id": ["primary.id", "backup.id"]})
        assert s.apply({"id": 7}) == {"primary": {"id": 7}, "backup": {"id": 7}}

    def test_chainr_score_pipeline(self):
        chain = Chainr.from_spec(
            [
                {"operation": "shift", "spec": {"score": "score"}},
                {"operation": "modify-overwrite-beta", "spec": {"score": "=toDouble"}},
                {"operation": "default", "spec": {"score": 0.0}},
            ]
        )
        assert chain.apply({"score": "3.14"}) == {"score": 3.14}
        assert chain.apply({}) == {"score": 0.0}
