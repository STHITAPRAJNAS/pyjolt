# pyjolt

A high-performance, pure-Python implementation of the [JOLT](https://github.com/bazaarvoice/jolt) JSON-to-JSON transformation library.

[![PyPI version](https://img.shields.io/pypi/v/pyjolt.svg)](https://pypi.org/project/pyjolt/)
[![Python](https://img.shields.io/pypi/pyversions/pyjolt.svg)](https://pypi.org/project/pyjolt/)
[![CI](https://github.com/sthitaprajnas/pyjolt/actions/workflows/ci.yml/badge.svg)](https://github.com/sthitaprajnas/pyjolt/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/license-Apache%202.0-green)](LICENSE)
[![Typed](https://img.shields.io/badge/typing-py.typed-informational)](src/pyjolt/py.typed)

## Features

| Transform | Operation name | Description |
|-----------|---------------|-------------|
| `Shift` | `shift` | Re-map fields from input paths to output paths |
| `Default` | `default` | Fill in missing or `null` fields |
| `Remove` | `remove` | Delete specified fields |
| `Sort` | `sort` | Sort all dict keys alphabetically |
| `Cardinality` | `cardinality` | Enforce `ONE` or `MANY` cardinality on fields |
| `ModifyOverwrite` | `modify-overwrite-beta` | Apply functions, always overwriting |
| `ModifyDefault` | `modify-default-beta` | Apply functions only to absent fields |
| `Chainr` | — | Chain multiple transforms sequentially |

## Installation

```bash
pip install pyjolt
```

## Quick Start

The canonical JOLT example — re-shape a nested rating object:

```python
from pyjolt import Chainr

spec = [
    {
        "operation": "shift",
        "spec": {
            "rating": {
                "primary": {
                    "value": "Rating",
                    "max":   "RatingRange"
                },
                "*": {
                    "value": "SecondaryRatings.&1.Value",
                    "max":   "SecondaryRatings.&1.Range"
                }
            }
        }
    },
    {
        "operation": "default",
        "spec": {"Rating": 0}
    }
]

input_data = {
    "rating": {
        "primary":  {"value": 3, "max": 5},
        "quality":  {"value": 4, "max": 5},
        "sharpness":{"value": 2, "max": 10}
    }
}

result = Chainr.from_spec(spec).apply(input_data)
# {
#   "Rating": 3,
#   "RatingRange": 5,
#   "SecondaryRatings": {
#     "quality":   {"Value": 4, "Range": 5},
#     "sharpness": {"Value": 2, "Range": 10}
#   }
# }
```

## Real-World Examples

### E-commerce order normalisation

Transform a raw checkout payload into an internal order schema — renaming
fields, typing prices, and stripping sensitive data:

```python
from pyjolt import Chainr

spec = [
    {
        "operation": "shift",
        "spec": {
            "orderId": "id",
            "customer": {
                "firstName": "customer.first",
                "lastName":  "customer.last",
                "emailAddress": "customer.email",
            },
            "lineItems": {
                "*": {
                    "sku":       "items[].sku",
                    "qty":       "items[].quantity",
                    "unitPrice": "items[].price",
                }
            },
            "shippingMethod": "shipping.method",
        },
    },
    {
        # Convert price strings to floats inside each item
        "operation": "modify-overwrite-beta",
        "spec": {"items": {"*": {"price": "=toDouble"}}},
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

raw_order = {
    "orderId": "ORD-9921",
    "customer": {
        "firstName": "Jane", "lastName": "Doe",
        "emailAddress": "jane.doe@example.com",
    },
    "lineItems": [
        {"sku": "ABC-1", "qty": 2, "unitPrice": "19.99"},
        {"sku": "XYZ-7", "qty": 1, "unitPrice": "5.49"},
    ],
    "shippingMethod": "express",
    "couponCode": None,
}

result = Chainr.from_spec(spec).apply(raw_order)
# {
#   "id": "ORD-9921",
#   "customer": {"first": "Jane", "last": "Doe", "email": "jane.doe@example.com"},
#   "items": [
#     {"sku": "ABC-1", "quantity": 2, "price": 19.99},
#     {"sku": "XYZ-7", "quantity": 1, "price":  5.49}
#   ],
#   "shipping": {"method": "express"}
# }
```

> **Note** — the `items[].field` syntax builds an array of objects where each
> wildcard iteration (`*` over `lineItems`) contributes one element.  Multiple
> fields from the same iteration (`sku`, `qty`, `price`) all land in the same
> array slot automatically.

---

### API response normalisation

Flatten a paginated search response, rename fields, and default missing values:

```python
spec = [
    {
        "operation": "shift",
        "spec": {
            "total_count": "meta.total",
            "items": {
                "*": {
                    "id":               "repos[].id",
                    "full_name":        "repos[].name",
                    "stargazers_count": "repos[].stars",
                    "language":         "repos[].language",
                    "private":          "repos[].private",
                }
            },
        },
    },
    {
        "operation": "default",
        "spec": {"repos": {"*": {"language": "unknown"}}},
    },
    {"operation": "sort"},
]
```

---

### User profile flattening + PII scrub

Flatten a nested CMS user object into a flat CRM record and strip PII before
export:

```python
spec = [
    {
        "operation": "shift",
        "spec": {
            "userId": "crm.id",
            "profile": {
                "displayName": "crm.name",
                "address": {
                    "city":    "crm.city",
                    "country": "crm.country",
                },
            },
            "account": {
                "plan":      "crm.plan",
                "createdAt": "crm.joinDate",
                "tags":      "crm.tags",
            },
            # profile.email, profile.phone, internal.* are intentionally
            # omitted from the spec and therefore dropped from the output
        },
    },
    {"operation": "default",         "spec": {"crm": {"plan": "free", "tags": []}}},
    {"operation": "modify-overwrite-beta", "spec": {"crm": {"plan": "=toUpperCase"}}},
    {"operation": "cardinality",     "spec": {"crm": {"tags": "MANY"}}},
]
```

---

### IoT sensor normalisation

Three device types emit subtly different payloads — one pipeline normalises
them into a uniform time-series schema:

```python
spec = [
    {
        "operation": "shift",
        "spec": {
            "device_id": "deviceId",
            "type":      "sensorType",
            "ts":        "timestamp",
            "reading": {
                "celsius": "value",   # temperature devices
                "percent": "value",   # humidity devices
                "hpa":     "value",   # pressure devices
                "unit":    "unit",
            },
            "battery_pct": "batteryPercent",
        },
    },
    {
        "operation": "modify-overwrite-beta",
        "spec": {
            "value":          "=toDouble",
            "batteryPercent": "=toInteger",
        },
    },
    {
        "operation": "default",
        "spec": {"batteryPercent": -1},   # sentinel for older firmware
    },
]
```

## Transform Reference

### Shift

Re-map fields by specifying where each input field should go in the output.

```python
from pyjolt.transforms import Shift

s = Shift({"user": {"name": "profile.fullName", "age": "profile.years"}})
s.apply({"user": {"name": "Alice", "age": 30}})
# → {"profile": {"fullName": "Alice", "years": 30}}
```

**Spec tokens — input side:**

| Token | Meaning |
|-------|---------|
| `*` | Match any key (combinable: `prefix_*_suffix`) |
| `a\|b` | Match key `a` OR `b` |
| `@` | Self-reference — use the current input node directly |
| `$` / `$N` | Emit the matched key name N levels up as the value |
| `#literal` | Emit the literal string `literal` as a constant value |

**Spec tokens — output path:**

| Token | Meaning |
|-------|---------|
| `literal` | Literal key name |
| `&` / `&N` | Key matched N levels up (`&0` = current, `&1` = parent, …) |
| `&(N,M)` | M-th wildcard capture group at N levels up |
| `@(N,path)` | Value found at N levels up following dot-separated path |
| `[]` suffix | Array-append: append value, or share a slot across fields |

**Wildcard back-references:**

```python
# *-* matches "foo-bar"; &(0,1)="foo", &(0,2)="bar"
s = Shift({"*-*": "out.&(0,1).&(0,2)"})
s.apply({"foo-bar": 42})  # → {"out": {"foo": {"bar": 42}}}
```

**Array of objects:**

```python
# Each "*" iteration creates one element; multiple fields share the same slot
s = Shift({"items": {"*": {"id": "out[].id", "name": "out[].name"}}})
s.apply({"items": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]})
# → {"out": [{"id": 1, "name": "a"}, {"id": 2, "name": "b"}]}
```

**Array flatten (append scalars):**

```python
s = Shift({"a": "vals[]", "b": "vals[]"})
s.apply({"a": 1, "b": 2})  # → {"vals": [1, 2]}
```

**Multiple output paths:**

```python
s = Shift({"id": ["primary.id", "backup.id"]})
s.apply({"id": 7})  # → {"primary": {"id": 7}, "backup": {"id": 7}}
```

**Key-as-value (`$` / `$N`):**

```python
# $ writes the matched key name as the value
s = Shift({"*": {"$": "keys[]"}})
s.apply({"foo": 1, "bar": 2})  # → {"keys": ["foo", "bar"]}

# $1 writes the key matched one level up
s = Shift({"sensors": {"*": {"value": "out[].v", "$1": "out[].section"}}})
s.apply({"sensors": {"temp": {"value": 22}}})
# → {"out": [{"v": 22, "section": "sensors"}]}
```

**Constant-as-value (`#literal`):**

```python
# #literal writes the fixed string "literal" as the value
s = Shift({"*": {"#photo": "types[]"}})
s.apply({"a": 1, "b": 2})  # → {"types": ["photo", "photo"]}

# Combine with back-references in the output path
s = Shift({"*": {"#widget": "catalog.&1.kind"}})
s.apply({"foo": {}, "bar": {}})
# → {"catalog": {"foo": {"kind": "widget"}, "bar": {"kind": "widget"}}}
```

### Default

Fill in absent or `null` fields.

```python
from pyjolt.transforms import Default

d = Default({"status": "unknown", "meta": {"version": 1}})
d.apply({"name": "test"})
# → {"name": "test", "status": "unknown", "meta": {"version": 1}}
```

Apply a default to every element of an array:

```python
Default({"items": {"*": {"active": True}}}).apply(
    {"items": [{"name": "x"}, {"name": "y", "active": False}]}
)
# → {"items": [{"name": "x", "active": True}, {"name": "y", "active": False}]}
```

### Remove

Delete specified fields.

```python
from pyjolt.transforms import Remove

r = Remove({"password": "", "token": ""})
r.apply({"user": "alice", "password": "s3cr3t", "token": "xyz"})
# → {"user": "alice"}
```

Use `"*"` to remove all keys at a level:

```python
Remove({"*": ""}).apply({"a": 1, "b": 2})  # → {}
```

### Sort

Recursively sort all dict keys alphabetically.

```python
from pyjolt.transforms import Sort

Sort().apply({"b": 2, "a": 1, "c": {"z": 26, "a": 1}})
# → {"a": 1, "b": 2, "c": {"a": 1, "z": 26}}
```

### Cardinality

Ensure fields are a single value (`ONE`) or a list (`MANY`).

```python
from pyjolt.transforms import Cardinality

c = Cardinality({"tags": "MANY", "primary": "ONE"})
c.apply({"tags": "python", "primary": ["first", "second"]})
# → {"tags": ["python"], "primary": "first"}
```

### ModifyOverwrite / ModifyDefault

Apply built-in functions to field values.

```python
from pyjolt.transforms import ModifyOverwrite, ModifyDefault

m = ModifyOverwrite({"score": "=toInteger", "label": "=toUpperCase"})
m.apply({"score": "42", "label": "hello"})
# → {"score": 42, "label": "HELLO"}
```

`ModifyDefault` only touches fields that are absent:

```python
m = ModifyDefault({"count": 0, "active": True})
m.apply({"count": 5})  # → {"count": 5, "active": True}
```

Apply a function to every element of an array:

```python
ModifyOverwrite({"prices": {"*": {"amount": "=toDouble"}}}).apply(
    {"prices": [{"amount": "9.99"}, {"amount": "4.49"}]}
)
# → {"prices": [{"amount": 9.99}, {"amount": 4.49}]}
```

**Built-in functions:**

| Function | Description |
|----------|-------------|
| `=toInteger` / `=toLong` | Convert to `int` |
| `=toDouble` / `=toFloat` | Convert to `float` |
| `=toString` | Convert to `str` |
| `=toBoolean` | Convert to `bool` |
| `=trim` | Strip whitespace |
| `=toUpperCase` / `=toLowerCase` | Change case |
| `=abs` | Absolute value |
| `=min(N)` / `=max(N)` | Clamp to min/max |
| `=intSum(N)` / `=doubleSum(N)` / `=longSum(N)` / `=floatSum(N)` | Add N to value |
| `=sum` | Sum all elements of a numeric list |
| `=avg` | Average of a numeric list |
| `=sqrt` | Square root |
| `=not` | Boolean negation |
| `=size` | Length of string/list |
| `=concat(suffix)` | Append suffix to string value |
| `=join(sep)` | Join list with separator |
| `=split(sep)` | Split string by separator |
| `=leftPad(width,char)` / `=rightPad(width,char)` | Pad string to width |
| `=substring(start,end)` | Slice a string |
| `=startsWith(prefix)` / `=endsWith(suffix)` | Predicate on string |
| `=contains(item)` | True if item is in string or list |
| `=squashNulls` | Remove `null` entries from list |
| `=recursivelySquashNulls` | Recursively remove `null` entries |
| `=toList` | Wrap value in a list if not already one |
| `=firstElement` / `=lastElement` | First or last list element |
| `=elementAt(N)` | Nth list element |
| `=indexOf(item)` | Index of item in list/string |
| `=coalesce(fallback,…)` | First non-null from value + args |
| `=noop` | Identity (leave value unchanged) |

### Chainr

Chain multiple transforms, applying them in order.

```python
from pyjolt import Chainr

chain = Chainr.from_spec([
    {"operation": "shift",                "spec": {"score": "score"}},
    {"operation": "modify-overwrite-beta","spec": {"score": "=toDouble"}},
    {"operation": "default",              "spec": {"score": 0.0}},
])

chain.apply({"score": "3.14"})  # → {"score": 3.14}
chain.apply({})                  # → {"score": 0.0}
```

Compose transform instances directly:

```python
from pyjolt import Chainr
from pyjolt.transforms import Shift, Sort

chain = Chainr([Shift({"b": "b", "a": "a"}), Sort()])
chain.apply({"b": 2, "a": 1})  # → {"a": 1, "b": 2}  (sorted)
```

## Contributing

Contributions are welcome — bug reports, documentation improvements, new
features, and spec-compatibility fixes all help.

```bash
git clone https://github.com/sthitaprajnas/pyjolt.git
cd pyjolt
pip install -e ".[dev]"
pytest                        # run test suite
ruff check src/pyjolt         # lint
mypy src/pyjolt               # type-check
```

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for the full workflow.  For
security issues, see [SECURITY.md](SECURITY.md).

## License

Copyright 2024 Sthitaprajna Sahoo and contributors.

Licensed under the Apache License, Version 2.0 — see [LICENSE](LICENSE) for
the full text.

You are free to use, modify, and distribute this software under the terms of
the Apache 2.0 license.  Contributions submitted to the project are also
licensed under Apache 2.0.
