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

"""Default transform — fill in missing or null values.

A port of the reference ``Defaultr``. The spec mirrors the shape of the
output. For each spec key, if the input value there is missing or ``null`` the
spec value is written; if the spec value is an object, defaulting continues
inside it.

Keys
    ``literal``, ``a|b`` (each of the listed keys that exists), ``*`` (every
    existing key). Literal keys are applied first, then ``|`` keys (fewest
    alternatives first), then ``*``.

Arrays
    A key ending in ``[]`` (e.g. ``"photos[]"``) says the value is an array;
    its children are then indexes (``"0"``, ``"1|2"``) or ``*``.
"""

from __future__ import annotations

from typing import Any

from .._common.util import deep_copy, parse_int
from ..exceptions import SpecError, TransformError
from .base import Transform

_LITERAL, _OR, _STAR = range(3)


class _NotAnIndex(SpecError):
    pass


def _parse_op(key: str) -> int:
    if "*" in key:
        if key != "*":
            raise SpecError(
                f"Defaultr key {key} is invalid.  * keys can only contain *, and no other characters."
            )
        return _STAR
    if "|" in key:
        return _OR
    return _LITERAL


def _to_index(s: str) -> int:
    try:
        return parse_int(s)
    except ValueError:
        raise _NotAnIndex(f"Defaultr array key {s!r} is not an integer") from None


class _Key:
    __slots__ = (
        "raw_key",
        "is_array_output",
        "op",
        "key_strings",
        "children",
        "literal_value",
        "output_array_size",
        "parent_is_array",
        "key_ints",
        "key_int",
    )

    def __init__(self, raw_json_key: str, spec: Any, parent_is_array: bool) -> None:
        raw = raw_json_key
        self.is_array_output = raw.endswith("[]")
        if self.is_array_output:
            raw = raw.replace("[]", "")
        self.raw_key = raw
        self.parent_is_array = parent_is_array
        self.op = _parse_op(raw)
        if self.op == _OR:
            self.key_strings = raw.split("|")
        elif self.op == _LITERAL:
            self.key_strings = [raw]
        else:
            self.key_strings = []

        self.key_int = -1
        self.key_ints: list[int] = []
        if parent_is_array:
            if self.op == _OR:
                self.key_ints = [_to_index(s) for s in self.key_strings]
            elif self.op == _LITERAL:
                self.key_int = _to_index(raw)
                self.key_ints = [self.key_int]

        self.children: list[_Key] | None = None
        self.literal_value: Any = None
        self.output_array_size = -1
        if isinstance(spec, dict):
            children = [_Key(k, v, self.is_array_output) for k, v in spec.items()]
            children.sort(key=_precedence)
            self.children = children
            if self.is_array_output:
                for child in children:
                    self.output_array_size = max(self.output_array_size, child.key_int)
        else:
            self.literal_value = spec

    @property
    def or_count(self) -> int:
        return len(self.key_strings) if self.op == _OR else 0

    def new_container(self) -> Any:
        return [] if self.is_array_output else {}

    def apply_children(self, defaultee: Any) -> None:
        if defaultee is None:
            raise TransformError("Defaultee should never be null when passed to applyChildren.")
        if self.children is None:
            return
        if self.is_array_output and isinstance(defaultee, list):
            while len(defaultee) <= self.output_array_size:
                defaultee.append(None)
        for child in self.children:
            child.apply_child(defaultee)

    def apply_child(self, container: Any) -> None:
        if self.parent_is_array:
            if isinstance(container, list):
                for index in self._matching_indexes(container):
                    self._apply_at(container, index)
        elif isinstance(container, dict):
            for key in self._matching_keys(container):
                self._apply_at(container, key)

    def _matching_keys(self, container: dict[str, Any]) -> list[str]:
        if self.op == _LITERAL:
            return self.key_strings
        if self.op == _STAR:
            return list(container)
        return [k for k in self.key_strings if k in container]

    def _matching_indexes(self, container: list[Any]) -> list[int]:
        if self.op == _LITERAL:
            return self.key_ints
        if self.op == _STAR:
            return list(range(len(container)))
        return [i for i in self.key_ints if i < len(container)]

    def _apply_at(self, container: Any, key: Any) -> None:
        if isinstance(container, list):
            if not 0 <= key < len(container):
                return
            value = container[key]
        else:
            value = container.get(key)
        if self.children is None:
            if value is None:
                container[key] = deep_copy(self.literal_value)
        else:
            if value is None:
                value = self.new_container()
                container[key] = value
            self.apply_children(value)


def _precedence(key: _Key) -> tuple[int, int, str]:
    if key.op == _OR:
        return 1, key.or_count, key.raw_key
    return (0 if key.op == _LITERAL else 2), 0, ""


class Default(Transform):
    """Fill in missing or ``null`` values from the spec.

    Example::

        Default({"status": "active", "tags": []}).apply({"name": "Ana", "status": None})
        # -> {"name": "Ana", "status": "active", "tags": []}
    """

    __slots__ = ("_map_root", "_array_root")

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Default expected a spec of Map type, got {type(spec).__name__}")
        self._map_root = _Key("root", spec, parent_is_array=False)
        try:
            self._array_root: _Key | None = _Key("root[]", spec, parent_is_array=False)
        except _NotAnIndex:
            self._array_root = None

    def apply(self, input_data: Any) -> Any:
        return self._apply_owned(deep_copy(input_data))

    def _apply_owned(self, data: Any, context: dict[str, Any] | None = None) -> Any:
        if data is None:
            data = {}
        if isinstance(data, list):
            if self._array_root is None:
                raise TransformError(
                    "The Spec provided can not handle input that is a top level Json Array."
                )
            self._array_root.apply_children(data)
        else:
            self._map_root.apply_children(data)
        return data
