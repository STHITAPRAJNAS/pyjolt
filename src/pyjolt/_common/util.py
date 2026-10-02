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

"""Small helpers that reproduce Java semantics the reference relies on."""

from __future__ import annotations

import math
import re
from decimal import Decimal
from typing import Any, Final

ROOT_KEY: Final = "root"


class _Missing:
    """Marks an absent value, as opposed to a present ``None`` (Java's ``Optional.empty()``)."""

    _instance: _Missing | None = None

    def __new__(cls) -> _Missing:
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __repr__(self) -> str:
        return "MISSING"

    def __bool__(self) -> bool:
        return False


MISSING: Final = _Missing()


def unwrap(value: Any) -> Any:
    """``Optional.get()``: the value, or ``None`` when missing."""
    return None if value is MISSING else value


_INT_RE = re.compile(r"[+-]?[0-9]+")
_INT_MIN, _INT_MAX = -(2**31), 2**31 - 1


def parse_int(s: str) -> int:
    """``Integer.parseInt``: strict decimal int32, raises ``ValueError`` otherwise."""
    if s.isascii() and s.isdigit():
        n = int(s)  # fast path for plain indexes
    elif _INT_RE.fullmatch(s):
        n = int(s)
    else:
        raise ValueError(s)
    if not _INT_MIN <= n <= _INT_MAX:
        raise ValueError(s)
    return n


def try_parse_int(s: str) -> int | None:
    try:
        return parse_int(s)
    except ValueError:
        return None


def is_digit(c: str) -> bool:
    return "0" <= c <= "9"


def java_double_str(x: float) -> str:
    """``Double.toString``."""
    if math.isnan(x):
        return "NaN"
    if math.isinf(x):
        return "Infinity" if x > 0 else "-Infinity"
    if x == 0:
        return "-0.0" if math.copysign(1.0, x) < 0 else "0.0"
    sign, digits, exp = Decimal(repr(x)).as_tuple()
    assert isinstance(exp, int)
    ds = "".join(map(str, digits)).rstrip("0") or "0"
    # value = 0.ds * 10**point
    point = len(digits) + exp
    neg = "-" if sign else ""
    if 1e-3 <= abs(x) < 1e7:
        if point <= 0:
            return f"{neg}0.{'0' * -point}{ds}"
        if point >= len(ds):
            return f"{neg}{ds}{'0' * (point - len(ds))}.0"
        return f"{neg}{ds[:point]}.{ds[point:]}"
    frac = ds[1:] or "0"
    return f"{neg}{ds[0]}.{frac}E{point - 1}"


def java_str(value: Any) -> str:
    """``Object.toString`` for JSON scalars."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return java_double_str(value)
    return str(value)


def count_matches(source: str, sub: str) -> int:
    """``StringTools.countMatches`` (non-overlapping)."""
    if not source or not sub:
        return 0
    return source.count(sub)


def is_blank(s: str | None) -> bool:
    return s is None or s.strip() == ""


def deep_copy(value: Any) -> Any:
    """Copy a JSON-like tree (much faster than :func:`copy.deepcopy` for plain data)."""
    if isinstance(value, dict):
        return {k: deep_copy(v) for k, v in value.items()}
    if isinstance(value, list):
        return [deep_copy(v) for v in value]
    return value
