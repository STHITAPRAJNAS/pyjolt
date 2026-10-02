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

"""Functions available in modify specs (``"=toUpper"``, ``"=concat(@(1,a),'-',@(1,b))"``).

Ports ``com.bazaarvoice.jolt.modifier.function``. Every function takes the
evaluated arguments and returns a value or :data:`MISSING` (no result, so
the field is left alone).

JSON numbers follow the reference's Java typing: an ``int`` that fits in 32
bits is an *Integer*, a larger one a *Long*, and a ``float`` a *Double*.
Functions such as ``intSubtract`` or ``elementAt`` only accept the matching
type, exactly like the reference.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from .util import MISSING, java_double_str, java_str

Fn = Callable[..., Any]

_I32 = 2**31
_I64 = 2**63

# ---------------------------------------------------------------------------
# Java number model
# ---------------------------------------------------------------------------


def is_integer(v: Any) -> bool:
    return type(v) is int and -_I32 <= v < _I32


def is_long(v: Any) -> bool:
    return type(v) is int and not -_I32 <= v < _I32


def is_double(v: Any) -> bool:
    return type(v) is float


def is_number(v: Any) -> bool:
    return type(v) in (int, float)


def _wrap(n: int, bits: int) -> int:
    m = 1 << bits
    n &= m - 1
    return n - m if n >= m >> 1 else n


def _saturate(x: float, bits: int) -> int:
    if math.isnan(x):
        return 0
    lo, hi = -(1 << (bits - 1)), (1 << (bits - 1)) - 1
    if x <= lo:
        return lo
    if x >= hi:
        return hi
    return int(x)


def int_value(n: int | float) -> int:
    return _saturate(n, 32) if isinstance(n, float) else _wrap(n, 32)


def long_value(n: int | float) -> int:
    return _saturate(n, 64) if isinstance(n, float) else _wrap(n, 64)


_INT_RE = re.compile(r"[+-]?[0-9]+")
_DOUBLE_RE = re.compile(
    r"[+-]?(NaN|Infinity|(([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?))[fFdD]?"
)


def _parse_double(s: str) -> float | None:
    s = s.strip(" \t\n\r\x0b\x0c\x00")
    if not _DOUBLE_RE.fullmatch(s):
        return None
    s = s.rstrip("fFdD")
    return float(s.replace("Infinity", "inf"))


def to_number(arg: Any) -> int | float | None:
    """``Objects.toNumber``: numbers as-is, strings parsed as int, then long, then double."""
    if is_number(arg):
        return arg  # type: ignore[no-any-return]
    if isinstance(arg, str):
        if _INT_RE.fullmatch(arg):
            n = int(arg)
            if -_I64 <= n < _I64:
                return n
        return _parse_double(arg)
    return None


def to_integer(arg: Any) -> Any:
    n = to_number(arg) if isinstance(arg, str) else (arg if is_number(arg) else None)
    return MISSING if n is None else int_value(n)


def to_long(arg: Any) -> Any:
    n = to_number(arg) if isinstance(arg, str) else (arg if is_number(arg) else None)
    return MISSING if n is None else long_value(n)


def to_double(arg: Any) -> Any:
    n = to_number(arg) if isinstance(arg, str) else (arg if is_number(arg) else None)
    return MISSING if n is None else float(n)


def to_boolean(arg: Any) -> Any:
    if isinstance(arg, bool):
        return arg
    if isinstance(arg, str):
        if arg.lower() == "true":
            return True
        if arg.lower() == "false":
            return False
    return MISSING


def java_to_string(value: Any) -> str:
    """``Object.toString`` including Java's list / map formatting."""
    if isinstance(value, list):
        return "[" + ", ".join(java_to_string(v) for v in value) + "]"
    if isinstance(value, dict):
        return "{" + ", ".join(f"{k}={java_to_string(v)}" for k, v in value.items()) + "}"
    if isinstance(value, float):
        return java_double_str(value)
    return java_str(value)


def strict_equal(a: Any, b: Any) -> bool:
    """``Object.equals``: ``1``, ``1.0`` and ``True`` are all different."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(strict_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(strict_equal(x, y) for x, y in zip(a, b, strict=True))
    return bool(a == b)


# ---------------------------------------------------------------------------
# Function shapes (Function.BaseFunction, SingleFunction, ...)
# ---------------------------------------------------------------------------


def base_function(apply_list: Fn, apply_single: Fn) -> Fn:
    def fn(*args: Any) -> Any:
        if not args:
            return MISSING
        if len(args) == 1:
            arg = args[0]
            if isinstance(arg, list):
                return apply_list(arg) if arg else MISSING
            if arg is None:
                return MISSING
            return apply_single(arg)
        return apply_list(list(args))

    return fn


def single_function(apply_single: Fn) -> Fn:
    def apply_list(items: list[Any]) -> Any:
        out = []
        for item in items:
            r = apply_single(item)
            out.append(item if r is MISSING else r)
        return out

    return base_function(apply_list, apply_single)


def list_function(apply_list: Fn) -> Fn:
    return base_function(apply_list, lambda _arg: MISSING)


def arg_driven_function(is_special: Callable[[Any], bool], apply_list: Fn, apply_single: Fn) -> Fn:
    def fn(*args: Any) -> Any:
        if len(args) == 1 and isinstance(args[0], list):
            args = tuple(args[0])
        if len(args) < 2 or not is_special(args[0]):
            return MISSING
        special = args[0]
        if len(args) == 2:
            if isinstance(args[1], list):
                return apply_list(special, args[1])
            return apply_single(special, args[1])
        return apply_list(special, list(args[1:]))

    return fn


def arg_driven_single_function(is_special: Callable[[Any], bool], apply_single: Fn) -> Fn:
    def apply_list(special: Any, items: list[Any]) -> Any:
        out = []
        for item in items:
            r = apply_single(special, item)
            out.append(item if r is MISSING else r)
        return out

    return arg_driven_function(is_special, apply_list, apply_single)


def arg_driven_list_function(is_special: Callable[[Any], bool], apply_list: Fn) -> Fn:
    return arg_driven_function(is_special, apply_list, lambda _s, _a: MISSING)


def squash_function(apply_single: Fn) -> Fn:
    def fn(*args: Any) -> Any:
        if not args:
            return MISSING
        if len(args) == 1:
            arg = args[0]
            if isinstance(arg, list) and not arg:
                return MISSING
            if arg is None:
                return MISSING
            return apply_single(arg)
        return apply_single(list(args))

    return fn


def _is_str(v: Any) -> bool:
    return isinstance(v, str)


# ---------------------------------------------------------------------------
# Built-ins: generic
# ---------------------------------------------------------------------------


def _noop(*args: Any) -> Any:
    return MISSING


def _is_present(*args: Any) -> Any:
    return args[0] if args else MISSING


def _not_null(*args: Any) -> Any:
    return args[0] if args and args[0] is not None else MISSING


def _is_null(*args: Any) -> Any:
    return args[0] if args and args[0] is None else MISSING


def _size(*args: Any) -> Any:
    if not args:
        return MISSING
    if len(args) > 1:
        return len(args)
    arg = args[0]
    if isinstance(arg, (list, str, dict)):
        return len(arg)
    return MISSING


# ---------------------------------------------------------------------------
# Built-ins: strings
# ---------------------------------------------------------------------------


def _str_single(op: Callable[[str], str]) -> Fn:
    return single_function(lambda a: op(a) if isinstance(a, str) else MISSING)


def _java_trim(s: str) -> str:
    return s.strip("".join(chr(c) for c in range(33)))


def _concat(items: list[Any]) -> Any:
    return "".join(java_to_string(a) for a in items if a is not None)


def _join(sep: str, items: list[Any]) -> Any:
    out = []
    for i, arg in enumerate(items):
        if arg is not None:
            s = java_to_string(arg)
            if s != "":
                out.append(s)
                if i < len(items) - 1:
                    out.append(sep)
    return "".join(out)


def _java_split(regex: str, source: str) -> list[str]:
    """``String.split(regex)``: no leading piece for a zero-width match at 0, no trailing empties."""
    if source == "":
        return [""]
    parts: list[str] = []
    last = 0
    matched = False
    for m in re.finditer(regex, source):
        if m.end() == 0:
            continue
        matched = True
        parts.append(source[last : m.start()])
        last = m.end()
    if not matched:
        return [source]
    parts.append(source[last:])
    while parts and parts[-1] == "":
        parts.pop()
    return parts


def _split(sep: Any, source: Any) -> Any:
    if source is None or sep is None or not isinstance(source, str):
        return MISSING
    return _java_split(sep, source)


def _substring(items: list[Any]) -> Any:
    if len(items) != 3:
        return MISSING
    s, start, end = items
    if not (isinstance(s, str) and is_integer(start) and is_integer(end)):
        return MISSING
    if start >= end or start < 0 or end < 1 or end > len(s):
        return MISSING
    return s[start:end]


def _pad(left: bool) -> Fn:
    def apply(source: str, items: list[Any]) -> Any:
        if source is None or items is None or len(items) < 2:
            return MISSING
        width, filler = items[0], items[1]
        if not (is_integer(width) and isinstance(filler, str)):
            return MISSING
        if width <= 0 or width > 500 or len(filler) != 1:
            return MISSING
        if width <= len(source):
            return source
        pad = filler * (width - len(source))
        return pad + source if left else source + pad

    return arg_driven_list_function(_is_str, apply)


# ---------------------------------------------------------------------------
# Built-ins: math
# ---------------------------------------------------------------------------


def _extreme(items: list[Any], want_max: bool) -> Any:
    pick: Callable[[Any, Any], Any] = max if want_max else min
    best_int = -_I32 if want_max else _I32 - 1
    best_double = -1.7976931348623157e308 if want_max else 1.7976931348623157e308
    best_long = -_I64 if want_max else _I64 - 1
    found = False
    for arg in items:
        if isinstance(arg, str):
            n = to_number(arg)
            if n is None:
                continue
            arg = n
        if is_integer(arg):
            best_int = pick(best_int, arg)
        elif is_double(arg):
            best_double = pick(best_double, arg)
        elif is_long(arg):
            best_long = pick(best_long, arg)
        else:
            continue
        found = True
    if not found:
        return MISSING
    bd = long_value(best_double)
    if want_max:
        if best_int >= bd and best_int >= best_long:
            return best_int
        return best_long if best_long >= bd else best_double
    if best_int <= bd and best_int <= best_long:
        return best_int
    return best_long if best_long <= bd else best_double


def _abs(arg: Any) -> Any:
    if is_integer(arg):
        return _wrap(abs(arg), 32)
    if is_double(arg):
        return abs(arg)
    if is_long(arg):
        return _wrap(abs(arg), 64)
    if isinstance(arg, str):
        n = to_number(arg)
        return MISSING if n is None else _abs(n)
    return MISSING


def _avg(items: list[Any]) -> Any:
    total, count = 0.0, 0
    for arg in items:
        n = to_number(arg)
        if n is not None:
            total += float(n)
            count += 1
    return MISSING if count == 0 else total / count


def _int_sum(items: list[Any]) -> Any:
    total = 0
    for arg in items:
        n = to_integer(arg)
        if n is not MISSING:
            total = _wrap(total + n, 32)
    return total


def _long_sum(items: list[Any]) -> Any:
    total = 0
    for arg in items:
        n = to_long(arg)
        if n is not MISSING:
            total = _wrap(total + n, 64)
    return total


def _double_sum(items: list[Any]) -> Any:
    total = 0.0
    for arg in items:
        n = to_double(arg)
        if n is not MISSING:
            total += n
    return total


def _subtract(check: Callable[[Any], bool], bits: int | None) -> Fn:
    def apply(items: list[Any]) -> Any:
        if len(items) != 2 or not (check(items[0]) and check(items[1])):
            return MISSING
        r = items[0] - items[1]
        return r if bits is None else _wrap(r, bits)

    return list_function(apply)


def _divide(items: list[Any]) -> Any:
    if len(items) != 2:
        return MISSING
    num, den = to_number(items[0]), to_number(items[1])
    if num is None or den is None or float(den) == 0:
        return MISSING
    return float(num) / float(den)


def _divide_and_round(digits: int, items: list[Any]) -> Any:
    result = _divide(items)
    if result is MISSING:
        return MISSING
    q = Decimal(1).scaleb(-digits)
    return float(Decimal(result).quantize(q, rounding=ROUND_HALF_UP))


def _sqrt(arg: Any) -> Any:
    n = to_number(arg) if isinstance(arg, str) else (arg if is_number(arg) else None)
    if n is None or n < 0:
        return MISSING
    return math.sqrt(n)


def _sum(items: list[Any]) -> Any:
    nums = [n for n in (to_number(a) for a in items) if n is not None]
    if any(isinstance(n, float) for n in nums):
        return float(sum(nums))
    return sum(nums)


# ---------------------------------------------------------------------------
# Built-ins: lists / objects
# ---------------------------------------------------------------------------


def _element_at(index: int, items: list[Any]) -> Any:
    if items is not None and len(items) > index >= 0:
        return items[index]
    return MISSING


def _java_sort_key(v: Any) -> Any:
    if isinstance(v, str):
        return v.encode("utf-16-be", "surrogatepass")
    return v


def _sort(items: list[Any]) -> Any:
    if not items or any(v is None for v in items):
        return MISSING
    kinds = {type(v) if not is_long(v) else "long" for v in items}
    if len(kinds) != 1 or isinstance(items[0], (list, dict)):
        return MISSING  # Arrays.sort would throw ClassCastException
    return sorted(items, key=_java_sort_key)


def _squash_nulls(arg: Any) -> Any:
    if isinstance(arg, list):
        arg[:] = [v for v in arg if v is not None]
    elif isinstance(arg, dict):
        for k in [k for k, v in arg.items() if v is None]:
            del arg[k]
    return arg


def _recursively_squash_nulls(arg: Any) -> Any:
    _squash_nulls(arg)
    if isinstance(arg, list):
        for v in arg:
            _recursively_squash_nulls(v)
    elif isinstance(arg, dict):
        for v in arg.values():
            _recursively_squash_nulls(v)
    return arg


def _squash_duplicates(arg: Any) -> Any:
    if not isinstance(arg, list):
        return arg
    out: list[Any] = []
    for v in arg:
        if not any(strict_equal(v, seen) for seen in out):
            out.append(v)
    return out


def _coalesce(items: list[Any]) -> Any:
    for v in items:
        if v is not None:
            return v
    return MISSING


def _source_item(op: Callable[[Any, Any], Any]) -> Fn:
    """pyjolt extension shape: ``=fn(source, item)``."""

    def apply(items: list[Any]) -> Any:
        if len(items) != 2:
            return MISSING
        return op(items[0], items[1])

    return list_function(apply)


def _contains(source: Any, item: Any) -> Any:
    if isinstance(source, str):
        return isinstance(item, str) and item in source
    if isinstance(source, list):
        return any(strict_equal(v, item) for v in source)
    if isinstance(source, dict):
        return isinstance(item, str) and item in source
    return MISSING


def _index_of(source: Any, item: Any) -> Any:
    if isinstance(source, str):
        return source.find(item) if isinstance(item, str) else -1
    if isinstance(source, list):
        for i, v in enumerate(source):
            if strict_equal(v, item):
                return i
        return -1
    return MISSING


def _starts_ends(starts: bool) -> Fn:
    def op(source: Any, item: Any) -> Any:
        if not (isinstance(source, str) and isinstance(item, str)):
            return MISSING
        return source.startswith(item) if starts else source.endswith(item)

    return _source_item(op)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_to_lower = _str_single(str.lower)
_to_upper = _str_single(str.upper)
_to_double_fn = single_function(to_double)

STOCK_FUNCTIONS: dict[str, Fn] = {
    # strings
    "toLower": _to_lower,
    "toUpper": _to_upper,
    "concat": list_function(_concat),
    "join": arg_driven_list_function(_is_str, _join),
    "split": arg_driven_single_function(_is_str, _split),
    "substring": list_function(_substring),
    "trim": _str_single(_java_trim),
    "leftPad": _pad(left=True),
    "rightPad": _pad(left=False),
    # math
    "min": base_function(
        lambda items: _extreme(items, want_max=False),
        lambda a: a if is_number(a) else MISSING,
    ),
    "max": base_function(
        lambda items: _extreme(items, want_max=True),
        lambda a: a if is_number(a) else MISSING,
    ),
    "abs": single_function(_abs),
    "avg": list_function(_avg),
    "intSum": list_function(_int_sum),
    "doubleSum": list_function(_double_sum),
    "longSum": list_function(_long_sum),
    "intSubtract": _subtract(is_integer, 32),
    "doubleSubtract": _subtract(is_double, None),
    "longSubtract": _subtract(is_long, 64),
    "divide": list_function(_divide),
    "divideAndRound": arg_driven_list_function(is_integer, _divide_and_round),
    # type conversion
    "toInteger": single_function(to_integer),
    "toDouble": _to_double_fn,
    "toLong": single_function(to_long),
    "toBoolean": single_function(to_boolean),
    "toString": single_function(java_to_string),
    # objects
    "size": _size,
    "squashNulls": squash_function(_squash_nulls),
    "recursivelySquashNulls": squash_function(_recursively_squash_nulls),
    "squashDuplicates": squash_function(_squash_duplicates),
    "noop": _noop,
    "isPresent": _is_present,
    "notNull": _not_null,
    "isNull": _is_null,
    # lists
    "firstElement": list_function(lambda items: items[0] if items else MISSING),
    "lastElement": list_function(lambda items: items[-1] if items else MISSING),
    "elementAt": arg_driven_list_function(is_integer, _element_at),
    "toList": base_function(lambda items: items, lambda a: [a]),
    "sort": base_function(_sort, lambda a: a),
}

# Functions pyjolt offers in addition to the reference implementation.
EXTRA_FUNCTIONS: dict[str, Fn] = {
    "toLowerCase": _to_lower,
    "toUpperCase": _to_upper,
    "toFloat": _to_double_fn,
    "floatSum": list_function(_double_sum),
    "sum": list_function(_sum),
    "sqrt": single_function(_sqrt),
    "not": single_function(lambda a: (not a) if isinstance(a, bool) else MISSING),
    "startsWith": _starts_ends(starts=True),
    "endsWith": _starts_ends(starts=False),
    "contains": _source_item(_contains),
    "indexOf": _source_item(_index_of),
    "coalesce": base_function(_coalesce, lambda a: a),
}

FUNCTIONS: dict[str, Fn] = {**STOCK_FUNCTIONS, **EXTRA_FUNCTIONS}
