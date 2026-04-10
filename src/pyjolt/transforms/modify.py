# Copyright 2024 Sthitaprajna Sahoo and contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Modify transforms — apply functions or literal values to fields.

Two variants are provided:

* :class:`ModifyOverwrite` (operation ``"modify-overwrite-beta"``) — always
  applies the function/value, overwriting existing data.
* :class:`ModifyDefault` (operation ``"modify-default-beta"``) — only applies
  when the key is **absent** or its value is ``None``.

Spec format
-----------
Each leaf value is either:

* A function expression starting with ``=``, e.g. ``"=toInteger"`` or
  ``"=concat(@(1,a),-,@(1,b))"``.
* A list of such expressions (first non-null result wins for default mode).
* Any other Python literal (string, number, bool, ``None``) — used directly
  as the replacement value.

Built-in functions
------------------
``toInteger``, ``toLong``, ``toDouble``, ``toFloat``, ``toString``,
``toBoolean``, ``trim``, ``toUpperCase``, ``toLowerCase``, ``abs``, ``size``,
``noop`` (identity), ``squashNulls``, ``recursivelySquashNulls``,
``concat``, ``join``, ``split``, ``min``, ``max``, ``intSum``, ``doubleSum``.
"""

from __future__ import annotations

import copy
import re
from collections.abc import Callable
from typing import Any

from ..exceptions import SpecError
from .base import Transform

# ---------------------------------------------------------------------------
# Function registry
# ---------------------------------------------------------------------------

_FunctionType = Callable[..., Any]
_REGISTRY: dict[str, _FunctionType] = {}


def _register(name: str) -> Callable[[_FunctionType], _FunctionType]:
    def decorator(fn: _FunctionType) -> _FunctionType:
        _REGISTRY[name] = fn
        return fn

    return decorator


# ---- Type conversions -------------------------------------------------------


@_register("toInteger")
def _to_integer(val: Any, *args: Any) -> Any:
    if val is None:
        return int(args[0]) if args else None
    try:
        return int(val)
    except (TypeError, ValueError):
        return int(args[0]) if args else None


@_register("toLong")
def _to_long(val: Any, *args: Any) -> Any:
    return _to_integer(val, *args)


@_register("toDouble")
def _to_double(val: Any, *args: Any) -> Any:
    if val is None:
        return float(args[0]) if args else None
    try:
        return float(val)
    except (TypeError, ValueError):
        return float(args[0]) if args else None


@_register("toFloat")
def _to_float(val: Any, *args: Any) -> Any:
    return _to_double(val, *args)


@_register("toString")
def _to_string(val: Any, *_: Any) -> Any:
    if val is None:
        return None
    return str(val)


@_register("toBoolean")
def _to_boolean(val: Any, *_: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, str):
        return val.strip().lower() in {"true", "1", "yes"}
    return bool(val)


# ---- String functions -------------------------------------------------------


@_register("trim")
def _trim(val: Any, *_: Any) -> Any:
    if isinstance(val, str):
        return val.strip()
    return val


@_register("toUpperCase")
def _upper(val: Any, *_: Any) -> Any:
    if isinstance(val, str):
        return val.upper()
    return val


@_register("toLowerCase")
def _lower(val: Any, *_: Any) -> Any:
    if isinstance(val, str):
        return val.lower()
    return val


@_register("concat")
def _concat(*args: Any) -> Any:
    """Concatenate all arguments (first arg is current value)."""
    return "".join(str(a) for a in args if a is not None)


@_register("join")
def _join(val: Any, sep: Any = ",", *rest: Any) -> Any:
    """join(val, separator) — join a list with separator."""
    if isinstance(val, list):
        return str(sep).join(str(v) for v in val if v is not None)
    return val


@_register("split")
def _split(val: Any, sep: Any = ",", *_: Any) -> Any:
    if isinstance(val, str):
        return val.split(str(sep))
    return val


# ---- Numeric functions -------------------------------------------------------


@_register("abs")
def _abs(val: Any, *_: Any) -> Any:
    if isinstance(val, (int, float)):
        return abs(val)
    return val


@_register("min")
def _min(val: Any, *args: Any) -> Any:
    candidates = [val, *args]
    try:
        return min(c for c in candidates if c is not None)
    except (TypeError, ValueError):
        return val


@_register("max")
def _max(val: Any, *args: Any) -> Any:
    candidates = [val, *args]
    try:
        return max(c for c in candidates if c is not None)
    except (TypeError, ValueError):
        return val


@_register("intSum")
def _int_sum(val: Any, *args: Any) -> Any:
    try:
        return int(val or 0) + sum(int(a) for a in args)
    except (TypeError, ValueError):
        return val


@_register("doubleSum")
def _double_sum(val: Any, *args: Any) -> Any:
    try:
        return float(val or 0) + sum(float(a) for a in args)
    except (TypeError, ValueError):
        return val


# ---- Collection functions ---------------------------------------------------


@_register("size")
def _size(val: Any, *_: Any) -> Any:
    try:
        return len(val)
    except TypeError:
        return None


@_register("squashNulls")
def _squash_nulls(val: Any, *_: Any) -> Any:
    if isinstance(val, list):
        return [v for v in val if v is not None]
    return val


@_register("recursivelySquashNulls")
def _recursively_squash(val: Any, *_: Any) -> Any:
    if isinstance(val, list):
        result = []
        for item in val:
            item = _recursively_squash(item)
            if item is not None:
                result.append(item)
        return result
    if isinstance(val, dict):
        return {k: _recursively_squash(v) for k, v in val.items() if v is not None}
    return val


@_register("noop")
def _noop(val: Any, *_: Any) -> Any:
    return val


# ---- Additional numeric functions -------------------------------------------


@_register("longSum")
def _long_sum(val: Any, *args: Any) -> Any:
    try:
        return int(val or 0) + sum(int(a) for a in args)
    except (TypeError, ValueError):
        return val


@_register("floatSum")
def _float_sum(val: Any, *args: Any) -> Any:
    try:
        return float(val or 0) + sum(float(a) for a in args)
    except (TypeError, ValueError):
        return val


@_register("sum")
def _sum(val: Any, *_: Any) -> Any:
    """Sum all elements of a numeric list."""
    if isinstance(val, list):
        try:
            return sum(v for v in val if v is not None)
        except TypeError:
            return val
    return val


@_register("avg")
def _avg(val: Any, *_: Any) -> Any:
    """Average of a numeric list."""
    if isinstance(val, list):
        nums = [v for v in val if v is not None]
        if not nums:
            return None
        try:
            return sum(nums) / len(nums)
        except TypeError:
            return val
    return val


@_register("sqrt")
def _sqrt(val: Any, *_: Any) -> Any:
    import math

    if isinstance(val, (int, float)):
        try:
            return math.sqrt(val)
        except ValueError:
            return None
    return val


@_register("not")
def _not(val: Any, *_: Any) -> Any:
    """Boolean negation."""
    if val is None:
        return None
    return not bool(val)


# ---- Additional string functions --------------------------------------------


@_register("leftPad")
def _left_pad(val: Any, width: Any = 0, char: Any = " ", *_: Any) -> Any:
    if isinstance(val, str):
        return str(val).rjust(int(width), str(char)[0])
    return val


@_register("rightPad")
def _right_pad(val: Any, width: Any = 0, char: Any = " ", *_: Any) -> Any:
    if isinstance(val, str):
        return str(val).ljust(int(width), str(char)[0])
    return val


@_register("substring")
def _substring(val: Any, start: Any = 0, end: Any = None, *_: Any) -> Any:
    if isinstance(val, str):
        s = int(start)
        e = int(end) if end is not None else None
        return val[s:e]
    return val


@_register("startsWith")
def _starts_with(val: Any, prefix: Any = "", *_: Any) -> Any:
    if isinstance(val, str):
        return val.startswith(str(prefix))
    return False


@_register("endsWith")
def _ends_with(val: Any, suffix: Any = "", *_: Any) -> Any:
    if isinstance(val, str):
        return val.endswith(str(suffix))
    return False


@_register("contains")
def _contains(val: Any, item: Any = None, *_: Any) -> Any:
    """Return True if *item* is in *val* (works for strings and lists)."""
    if val is None:
        return False
    try:
        return item in val
    except TypeError:
        return False


# ---- Array / collection extras ----------------------------------------------


@_register("toList")
def _to_list(val: Any, *_: Any) -> Any:
    """Wrap *val* in a list if it isn't one already."""
    if isinstance(val, list):
        return val
    if val is None:
        return []
    return [val]


@_register("firstElement")
def _first_element(val: Any, *_: Any) -> Any:
    if isinstance(val, list):
        return val[0] if val else None
    return val


@_register("lastElement")
def _last_element(val: Any, *_: Any) -> Any:
    if isinstance(val, list):
        return val[-1] if val else None
    return val


@_register("elementAt")
def _element_at(val: Any, index: Any = 0, *_: Any) -> Any:
    if isinstance(val, list):
        try:
            return val[int(index)]
        except (IndexError, ValueError):
            return None
    return val


@_register("indexOf")
def _index_of(val: Any, item: Any = None, *_: Any) -> Any:
    if isinstance(val, list):
        try:
            return val.index(item)
        except ValueError:
            return -1
    if isinstance(val, str) and isinstance(item, str):
        return val.find(item)
    return -1


@_register("coalesce")
def _coalesce(val: Any, *args: Any) -> Any:
    """Return the first non-None value from *val*, *args*."""
    for candidate in (val, *args):
        if candidate is not None:
            return candidate
    return None


# ---------------------------------------------------------------------------
# Function expression parsing
# ---------------------------------------------------------------------------

_RE_FUNC = re.compile(r"^=([A-Za-z][A-Za-z0-9_]*)(?:\((.*)\))?$", re.DOTALL)


def _parse_func_expr(expr: str) -> tuple[str, list[str]] | None:
    """Return ``(func_name, raw_args)`` for an ``=func(...)`` expression."""
    m = _RE_FUNC.match(expr)
    if not m:
        return None
    name = m.group(1)
    raw_args = m.group(2)
    args = [a.strip() for a in raw_args.split(",")] if raw_args else []
    return name, args


def _coerce_arg(arg: str) -> Any:
    """Try to coerce a string argument to int/float, else return as string."""
    try:
        return int(arg)
    except ValueError:
        pass
    try:
        return float(arg)
    except ValueError:
        pass
    return arg


def _apply_func_expr(val: Any, expr: str, current_obj: Any) -> Any:
    """Apply a single function expression string to *val*."""
    parsed = _parse_func_expr(expr)
    if parsed is None:
        raise SpecError(f"Invalid modify function expression: {expr!r}")
    name, raw_args = parsed
    fn = _REGISTRY.get(name)
    if fn is None:
        raise SpecError(f"Unknown modify function: {name!r}. Available: {sorted(_REGISTRY)}")
    args = [_coerce_arg(a) for a in raw_args]
    return fn(val, *args)


def _apply_spec_value(
    val: Any,
    spec_val: Any,
    current_obj: Any,
    overwrite: bool,
    key: str,
) -> Any:
    """Return the new value for *key* based on *spec_val* and the mode."""
    if isinstance(spec_val, list):
        # Try each expression; first non-null result wins
        for item in spec_val:
            result = _apply_spec_value(val, item, current_obj, overwrite, key)
            if result is not None:
                return result
        return val

    if isinstance(spec_val, str) and spec_val.startswith("="):
        if not overwrite and val is not None:
            return val  # default mode: skip if value already present
        return _apply_func_expr(val, spec_val, current_obj)

    # Literal replacement
    if not overwrite and val is not None:
        return val
    return copy.deepcopy(spec_val)


# ---------------------------------------------------------------------------
# Recursive application
# ---------------------------------------------------------------------------


def _apply_modify(data: Any, spec: Any, overwrite: bool) -> Any:
    if not isinstance(spec, dict):
        return data

    if isinstance(data, dict):
        result: dict[str, Any] = dict(data)
        wildcard = spec.get("*")

        for key, spec_val in spec.items():
            if key == "*":
                continue
            if isinstance(spec_val, dict):
                if key in result:
                    if isinstance(result[key], dict):
                        result[key] = _apply_modify(result[key], spec_val, overwrite)
                    elif isinstance(result[key], list):
                        # Apply spec to each element of the list
                        result[key] = _apply_modify(result[key], spec_val, overwrite)
                elif key not in result and not overwrite:
                    pass  # default mode — skip absent nested keys
            else:
                current = result.get(key)
                result[key] = _apply_spec_value(current, spec_val, result, overwrite, key)

        if wildcard is not None:
            for key in list(result.keys()):
                if key in spec:
                    continue
                current = result[key]
                if isinstance(wildcard, dict):
                    if isinstance(current, (dict, list)):
                        result[key] = _apply_modify(current, wildcard, overwrite)
                    # wildcard dict-spec does not apply to scalar values — skip
                else:
                    result[key] = _apply_spec_value(current, wildcard, result, overwrite, key)

        return result

    if isinstance(data, list):
        # When the spec has a wildcard dict-spec ("*": {...}), apply that
        # sub-spec to each list element directly.  This covers the common
        # pattern {"items": {"*": {"price": "=toDouble"}}} where items is a
        # list of dicts and the wildcard targets each element's fields.
        wildcard = spec.get("*") if isinstance(spec, dict) else None
        if isinstance(wildcard, dict):
            return [_apply_modify(item, wildcard, overwrite) for item in data]
        return [_apply_modify(item, spec, overwrite) for item in data]

    return data


# ---------------------------------------------------------------------------
# Public transform classes
# ---------------------------------------------------------------------------


class ModifyOverwrite(Transform):
    """Apply modify functions/values, always overwriting existing data.

    Parameters
    ----------
    spec:
        A dict mapping field names to function expressions (``"=toInteger"``,
        etc.) or literal replacement values.

    Examples
    --------
    >>> m = ModifyOverwrite({"score": "=toInteger", "label": "=toUpperCase"})
    >>> m.apply({"score": "42", "label": "hello"})
    {'score': 42, 'label': 'HELLO'}
    """

    __slots__ = ("_spec",)

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Modify spec must be a dict, got {type(spec).__name__!r}")
        self._spec = spec

    def apply(self, input_data: Any) -> Any:
        return _apply_modify(input_data, self._spec, overwrite=True)


class ModifyDefault(Transform):
    """Apply modify functions/values only to absent or null fields.

    Parameters
    ----------
    spec:
        A dict mapping field names to function expressions or literal values.
        Each entry is only applied if the field is absent or ``None``.

    Examples
    --------
    >>> m = ModifyDefault({"status": "=toString", "count": 0})
    >>> m.apply({"status": None, "count": 5})
    {'status': None, 'count': 5}
    >>> m.apply({"count": 5})
    {'count': 5}
    """

    __slots__ = ("_spec",)

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Modify spec must be a dict, got {type(spec).__name__!r}")
        self._spec = spec

    def apply(self, input_data: Any) -> Any:
        return _apply_modify(input_data, self._spec, overwrite=False)
