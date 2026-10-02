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

"""Remove transform — delete keys from the input.

A port of the reference ``Removr``. The spec mirrors the shape of the input;
a leaf value of ``""`` removes the matching key (or array index).

Keys
    ``literal``, ``a|b``, and ``*`` wildcards (``"*"``, ``"tag-*"``,
    ``"*-x-*"``). In arrays, use an index (``"0"``) or ``"*"``.
"""

from __future__ import annotations

from typing import Any

from .._common.paths import (
    LiteralPathElement,
    PathElement,
    StarAllPathElement,
    StarDoublePathElement,
    StarPathElement,
    StarRegexPathElement,
    StarSinglePathElement,
)
from .._common.util import count_matches, deep_copy, try_parse_int
from ..exceptions import SpecError
from .base import Transform


def _parse(key: str) -> PathElement:
    if key == "*":
        return StarAllPathElement(key)
    stars = count_matches(key, "*")
    if stars == 1:
        return StarSinglePathElement(key)
    if stars == 2:
        return StarDoublePathElement(key)
    if stars > 2:
        return StarRegexPathElement(key)
    return LiteralPathElement(key)


class _Spec:
    __slots__ = ("path_element",)

    def __init__(self, key: str) -> None:
        self.path_element = _parse(key)

    def _index(self) -> int | None:
        n = try_parse_int(self.path_element.raw_key)
        return n if n is not None and n >= 0 else None

    def apply_to_map(self, data: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    def apply_to_list(self, data: list[Any]) -> list[int]:
        raise NotImplementedError


class _LeafSpec(_Spec):
    __slots__ = ()

    def apply_to_map(self, data: dict[str, Any]) -> list[str]:
        pe = self.path_element
        if isinstance(pe, LiteralPathElement):
            return [pe.raw_key] if pe.raw_key in data else []
        assert isinstance(pe, StarPathElement)
        return [k for k in data if pe.string_match(k)]

    def apply_to_list(self, data: list[Any]) -> list[int]:
        pe = self.path_element
        if isinstance(pe, LiteralPathElement):
            idx = self._index()
            return [idx] if idx is not None and idx < len(data) else []
        if isinstance(pe, StarAllPathElement):
            return list(range(len(data)))
        return []


class _CompositeSpec(_Spec):
    __slots__ = ("children",)

    def __init__(self, key: str, spec: dict[str, Any]) -> None:
        super().__init__(key)
        children: list[_Spec] = []
        for raw_lhs, raw_rhs in spec.items():
            for k in str(raw_lhs).split("|"):
                if isinstance(raw_rhs, dict):
                    children.append(_CompositeSpec(k, raw_rhs))
                elif isinstance(raw_rhs, str) and raw_rhs.strip() == "":
                    children.append(_LeafSpec(k))
                else:
                    raise SpecError("Invalid Removr spec RHS. Should be an empty string or Map")
        self.children = children

    def apply_to_map(self, data: dict[str, Any]) -> list[str]:
        pe = self.path_element
        if isinstance(pe, LiteralPathElement):
            self._process_children(data.get(pe.raw_key))
        else:
            assert isinstance(pe, StarPathElement)
            for key, value in list(data.items()):
                if pe.string_match(key):
                    self._process_children(value)
        return []

    def apply_to_list(self, data: list[Any]) -> list[int]:
        pe = self.path_element
        if isinstance(pe, LiteralPathElement):
            idx = self._index()
            if idx is not None and idx < len(data):
                self._process_children(data[idx])
        elif isinstance(pe, StarAllPathElement):
            for item in data:
                self._process_children(item)
        return []

    def _process_children(self, sub: Any) -> None:
        if isinstance(sub, list):
            indexes: set[int] = set()
            for child in self.children:
                indexes.update(child.apply_to_list(sub))
            for i in sorted(indexes, reverse=True):
                del sub[i]
        elif isinstance(sub, dict):
            keys: list[str] = []
            for child in self.children:
                keys.extend(child.apply_to_map(sub))
            for k in keys:
                sub.pop(k, None)


class Remove(Transform):
    """Delete the keys named in the spec.

    Example::

        Remove({"password": "", "meta": {"*": ""}}).apply(
            {"user": "ana", "password": "x", "meta": {"a": 1}}
        )  # -> {"user": "ana", "meta": {}}
    """

    __slots__ = ("_root",)

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Remove expected a spec of Map type, got {type(spec).__name__}")
        self._root = _CompositeSpec("root", spec)

    def apply(self, input_data: Any) -> Any:
        return self._apply_owned(deep_copy(input_data))

    def _apply_owned(self, data: Any, context: dict[str, Any] | None = None) -> Any:
        self._root.apply_to_map({"root": data})
        return data
