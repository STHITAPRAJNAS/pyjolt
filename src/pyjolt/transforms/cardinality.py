# Copyright 2024 PyJolt Contributors
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

"""Cardinality transform — enforce ONE or MANY cardinality on fields.

Spec values
-----------
* ``"ONE"``  — if the value is a list, take the **first** element; otherwise
  keep as-is.
* ``"MANY"`` — if the value is *not* a list, wrap it in a single-element list;
  otherwise keep as-is.

Wildcards
---------
``*`` as a spec key applies the cardinality rule to every key at that level.
"""

from __future__ import annotations

from typing import Any

from ..exceptions import SpecError
from .base import Transform

_ONE = "ONE"
_MANY = "MANY"


def _adjust(val: Any, mode: str) -> Any:
    upper = mode.upper()
    if upper == _ONE:
        if isinstance(val, list):
            return val[0] if val else None
        return val
    if upper == _MANY:
        if not isinstance(val, list):
            return [val]
        return val
    raise SpecError(f"Unknown cardinality mode {mode!r}. Expected 'ONE' or 'MANY'.")


def _apply_cardinality(data: Any, spec: Any) -> Any:
    if isinstance(spec, str):
        return _adjust(data, spec)

    if not isinstance(spec, dict):
        raise SpecError(f"Cardinality spec must be a dict or string, got {type(spec).__name__!r}")

    if isinstance(data, dict):
        result: dict[str, Any] = dict(data)
        wildcard = spec.get("*")

        for key, mode_or_sub in spec.items():
            if key == "*":
                continue
            if key not in result:
                continue
            result[key] = _apply_cardinality(result[key], mode_or_sub)

        if wildcard is not None:
            for key in result:
                if key not in spec:
                    result[key] = _apply_cardinality(result[key], wildcard)

        return result

    if isinstance(data, list):
        wildcard = spec.get("*")
        if wildcard is not None:
            return [_apply_cardinality(item, wildcard) for item in data]
        return data

    return data


class Cardinality(Transform):
    """Adjust the cardinality of JSON values to ONE or MANY.

    Parameters
    ----------
    spec:
        A dict mapping field names to ``"ONE"`` or ``"MANY"``.  Nested dicts
        trigger recursive cardinality adjustment.

    Examples
    --------
    >>> c = Cardinality({"tags": "MANY", "primary": "ONE"})
    >>> c.apply({"tags": "python", "primary": ["first", "second"]})
    {'tags': ['python'], 'primary': 'first'}
    """

    __slots__ = ("_spec",)

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Cardinality spec must be a dict, got {type(spec).__name__!r}")
        self._spec = spec

    def apply(self, input_data: Any) -> Any:
        return _apply_cardinality(input_data, self._spec)
