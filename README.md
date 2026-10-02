# jolt-py

A pure-Python implementation of the [JOLT](https://github.com/bazaarvoice/jolt) JSON-to-JSON transformation library.

**Spec-compatible with JOLT.** pyjolt runs the reference implementation's own
test suite (178 cases across every transform) on every commit and passes all
of it, so a spec you build on the [JOLT demo site](https://jolt-demo.appspot.com)
gives the same output here.

[![PyPI version](https://img.shields.io/pypi/v/jolt-py.svg)](https://pypi.org/project/jolt-py/)
[![Python](https://img.shields.io/pypi/pyversions/jolt-py.svg)](https://pypi.org/project/jolt-py/)
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
| `ModifyDefault` | `modify-default-beta` | Apply functions only where the value is missing or `null` |
| `ModifyDefine` | `modify-define-beta` | Apply functions only where the key does not exist |
| `Chainr` | — | Chain multiple transforms sequentially |

## Installation

```bash
pip install jolt-py
```

## CLI Usage

`jolt-py` includes a command-line interface for testing specs or running
transformations in shell pipelines:

```bash
# Transform a file
pyjolt input.json --spec spec.json --indent 2

# Use in a pipeline
cat input.json | pyjolt --spec spec.json > output.json
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
                    "sku":       "items[&1].sku",
                    "qty":       "items[&1].quantity",
                    "unitPrice": "items[&1].price",
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

> **Note** — `items[&1].sku` writes to index `&1` of `items`: the array index
> matched one level up (by `*` over `lineItems`). Fields written with the same
> index land in the same object. A bare `items[]` appends a *new* element on
> every write, so it is for collecting values (`"tags[]"`), not for building
> objects.

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
                    "id":               "repos[&1].id",
                    "full_name":        "repos[&1].name",
                    "stargazers_count": "repos[&1].stars",
                    "language":         "repos[&1].language",
                    "private":          "repos[&1].private",
                }
            },
        },
    },
    {
        "operation": "default",
        # "repos[]" tells default that repos is an array; "*" is each element
        "spec": {"repos[]": {"*": {"language": "unknown"}}},
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
    {"operation": "modify-overwrite-beta", "spec": {"crm": {"plan": "=toUpper"}}},
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

If nothing in the input matches the spec, the result is `None`, as in JOLT.

**Spec tokens — input side (keys):**

| Token | Meaning |
|-------|---------|
| `*` | Match any key (combinable: `prefix_*_suffix`, `*-*`) |
| `a\|b` | Match key `a` OR `b` |
| `&` / `&N` | Match the key built from earlier matches |
| `@` | The current input value itself |
| `@(N,path)` | A value looked up in the input, used as the key to match on |
| `$` / `$N` | Emit the matched key name N levels up as the value |
| `#literal` | Emit the literal string `literal` as a constant value |
| `\\` | Escape any of the characters above (`"\\@type"` matches the key `@type`) |

**Spec tokens — output path (values):**

| Token | Meaning |
|-------|---------|
| `literal` | Literal key name |
| `&` / `&N` | Key matched N levels up (`&0` = current, `&1` = parent, …) |
| `&(N,M)` | M-th wildcard capture group at N levels up |
| `@(N,path)` | Value found at N levels up following a dot-separated path |
| `[]` | Append a new array element |
| `[N]` / `[&N]` / `[#N]` / `[@(N,path)]` | Write to an array index: literal, matched key, match count, or looked-up value |
| `""` | Write to the output root |

Values written to the same place are collected into a list.

**Wildcard back-references:**

```python
# *-* matches "foo-bar"; &(0,1)="foo", &(0,2)="bar"
s = Shift({"*-*": "out.&(0,1).&(0,2)"})
s.apply({"foo-bar": 42})  # → {"out": {"foo": {"bar": 42}}}
```

**Array of objects:**

```python
# [&1] is the index matched one level up, so each item's fields share an element
s = Shift({"items": {"*": {"id": "out[&1].id", "name": "out[&1].name"}}})
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
s = Shift({"sensors": {"*": {"value": "out.&1.v", "$1": "out.&1.section"}}})
s.apply({"sensors": {"temp": {"value": 22}}})
# → {"out": {"temp": {"v": 22, "section": "sensors"}}}
```

**Value as key (`@` lookups):**

```python
# Turn [{"name": ..., "value": ...}] into {name: value}
s = Shift({"*": {"value": "@(1,name)"}})
s.apply([{"name": "color", "value": "red"}, {"name": "size", "value": "L"}])
# → {"color": "red", "size": "L"}
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

Fill in absent or `null` fields. Keys are literals, `a|b` or `*`; literal keys
are applied first, then `|` keys, then `*`.

```python
from pyjolt.transforms import Default

d = Default({"status": "unknown", "meta": {"version": 1}})
d.apply({"name": "test"})
# → {"name": "test", "status": "unknown", "meta": {"version": 1}}
```

Apply a default to every element of an array. A key ending in `[]` marks an
array; its children are indexes or `*`:

```python
Default({"items[]": {"*": {"active": True}}}).apply(
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

### ModifyOverwrite / ModifyDefault / ModifyDefine

Compute field values with functions. `"=fn"` applies `fn` to the current value;
`"=fn(arg, ...)"` calls it with the given arguments, which are literals
(`5`, `true`, `'quoted text'`), `@(N,path)` lookups into the input (`@(1,x)` is
the sibling field `x`), or `^path` lookups into a context dict.

```python
from pyjolt.transforms import ModifyOverwrite, ModifyDefault

m = ModifyOverwrite({
    "score": "=toInteger",
    "label": "=toUpper",
    "full":  "=concat(@(1,first),' ',@(1,last))",
})
m.apply({"score": "42", "label": "hello", "first": "Ada", "last": "Lovelace"})
# → {"score": 42, "label": "HELLO", "first": "Ada", "last": "Lovelace", "full": "Ada Lovelace"}
```

A list of alternatives uses the first one that produces a value. A function that
can't produce a value (wrong types, missing lookup) leaves the field unchanged:

```python
ModifyOverwrite({"n": ["=toInteger", 0]}).apply({"n": "abc"})  # → {"n": 0}
```

`ModifyDefault` only touches fields that are missing or `null`; `ModifyDefine`
only touches fields that don't exist:

```python
m = ModifyDefault({"count": 0, "active": True})
m.apply({"count": 5})  # → {"count": 5, "active": True}
```

Prefix a key with `+`, `~` or `_` to overwrite / default / define just that key,
and end it with `?` to apply only if the key exists.

Apply a function to every element of an array:

```python
ModifyOverwrite({"prices": {"*": {"amount": "=toDouble"}}}).apply(
    {"prices": [{"amount": "9.99"}, {"amount": "4.49"}]}
)
# → {"prices": [{"amount": 9.99}, {"amount": 4.49}]}
```

**Built-in functions** (the same set as JOLT):

| Function | Description |
|----------|-------------|
| `=toInteger` / `=toLong` / `=toDouble` / `=toBoolean` / `=toString` | Type conversion (also element-wise on a list) |
| `=toUpper` / `=toLower` / `=trim` | String case and whitespace |
| `=concat(a,b,…)` | Join values as strings |
| `=join(sep,list)` | Join non-empty values with a separator |
| `=split(regex,string)` | Split a string |
| `=substring(string,start,end)` | Slice a string |
| `=leftPad(string,width,char)` / `=rightPad(…)` | Pad a string |
| `=min(…)` / `=max(…)` / `=abs` / `=avg(…)` | Math on numbers or a list |
| `=intSum(…)` / `=longSum(…)` / `=doubleSum(…)` | Sum |
| `=intSubtract(a,b)` / `=longSubtract(a,b)` / `=doubleSubtract(a,b)` | Subtract |
| `=divide(a,b)` / `=divideAndRound(digits,a,b)` | Divide |
| `=size` | Length of a string, list or object |
| `=firstElement` / `=lastElement` / `=elementAt(index,list)` | Pick from a list |
| `=toList` / `=sort` | Wrap in a list / sort a list |
| `=squashNulls` / `=recursivelySquashNulls` / `=squashDuplicates` | Clean up lists and objects |
| `=isPresent` / `=notNull` / `=isNull` / `=noop` | Conditions, for use in a list of alternatives |

pyjolt also provides `=toUpperCase` / `=toLowerCase` / `=toFloat` / `=floatSum`
(aliases), `=sum(…)`, `=sqrt`, `=not`, `=coalesce(…)`, and
`=startsWith(string,prefix)` / `=endsWith(string,suffix)` /
`=contains(source,item)` / `=indexOf(source,item)`.

**Custom functions and context:**

```python
from pyjolt import MISSING, ModifyOverwrite

def initials(name):
    return "".join(part[0] for part in name.split()) if isinstance(name, str) else MISSING

m = ModifyOverwrite(
    {"initials": "=initials(@(1,name))", "currency": "^defaults.currency"},
    functions={"initials": initials},
)
m.apply({"name": "Ada Lovelace"}, context={"defaults": {"currency": "EUR"}})
# → {"name": "Ada Lovelace", "initials": "AL", "currency": "EUR"}
```

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

`Chainr.apply(data, context={...})` passes the context to modify steps.
Operation names from JOLT (including Java class names such as
`com.bazaarvoice.jolt.Shiftr`) are accepted, so specs can be copied over as-is.

Compose transform instances directly:

```python
from pyjolt import Chainr
from pyjolt.transforms import Shift, Sort

chain = Chainr([Shift({"b": "b", "a": "a"}), Sort()])
chain.apply({"b": 2, "a": 1})  # → {"a": 1, "b": 2}  (sorted)
```

## Upgrading from 1.x

2.0 makes every transform behave like reference JOLT. Specs written for JOLT
(or the demo site) now give identical results, but some 1.x-only behaviour
changed — most notably `out[].field` no longer groups fields from the same
parent into one element (use `out[&1].field`), and `=fn(args)` no longer
receives the current value implicitly (use `@(1,key)`). See the
[changelog](CHANGELOG.md#200--2026-10-02) for the full list.

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
