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

"""Cardinality transform — force values to be a single item or a list.

A port of the reference ``CardinalityTransform``. The spec mirrors the shape
of the input; leaves are ``"ONE"`` or ``"MANY"``.

``"MANY"``
    A non-list value is wrapped in a list; ``null`` becomes ``[]``.
``"ONE"``
    A list is replaced by its first element (``null`` if empty).

Keys are literals, ``*`` wildcards, or ``"@"`` to apply to the containing
value itself.
"""

from __future__ import annotations

from typing import Any

from .._common.paths import (
    AmpPathElement,
    AtPathElement,
    LiteralPathElement,
    MatchedElement,
    PathElement,
    StarAllPathElement,
    StarRegexPathElement,
    StarSinglePathElement,
    WalkedPath,
)
from .._common.spec import computed_sort_key
from .._common.util import count_matches, deep_copy, java_str
from ..exceptions import SpecError
from .base import Transform

_ORDER: dict[type, int] = {
    AmpPathElement: 1,
    StarAllPathElement: 2,
    StarSinglePathElement: 2,
    StarRegexPathElement: 2,
}


def _parse(key: str) -> PathElement:
    if "@" in key:
        return AtPathElement(key)
    if key == "*":
        return StarAllPathElement(key)
    if "*" in key:
        if count_matches(key, "*") == 1:
            return StarSinglePathElement(key)
        return StarRegexPathElement(key)
    return LiteralPathElement(key)


def _put(container: Any, key: str, value: Any) -> None:
    if isinstance(container, dict):
        container[key] = value
    elif isinstance(container, list):
        container[int(key)] = value


class _LeafSpec:
    __slots__ = ("path_element", "many")

    def __init__(self, key: str, rhs: Any) -> None:
        self.path_element = _parse(key)
        value = java_str(rhs)
        if value not in ("ONE", "MANY"):
            raise SpecError(f"Invalid Cardinality type :{value}")
        self.many = value == "MANY"

    def apply_cardinality(
        self, input_key: str, value: Any, walked_path: WalkedPath, parent: Any
    ) -> bool:
        this_level = self.path_element.match(input_key, walked_path)
        if this_level is None:
            return False
        self._adjust(input_key, value, walked_path, parent, this_level)
        return True

    def apply_to_parent_container(
        self, input_key: str, value: Any, walked_path: WalkedPath, parent: Any
    ) -> Any:
        this_level = self.path_element.match(input_key, walked_path)
        if this_level is None:
            return None
        return self._adjust(input_key, value, walked_path, parent, this_level)

    def _adjust(
        self,
        input_key: str,
        value: Any,
        walked_path: WalkedPath,
        parent: Any,
        this_level: MatchedElement,
    ) -> Any:
        if not isinstance(parent, (dict, list)):
            return None
        result: Any = None
        if self.many:
            if isinstance(value, list):
                result = value
            elif value is None:
                result = []
            else:
                result = [value]
            _put(parent, input_key, result)
        elif isinstance(value, list):
            result = value[0] if value else None
            _put(parent, input_key, result)
        return result


class _CompositeSpec:
    __slots__ = ("path_element", "special_child", "literal_children", "computed_children")

    def __init__(self, key: str, spec: dict[str, Any]) -> None:
        self.path_element = _parse(key)
        if isinstance(self.path_element, AtPathElement):
            raise SpecError("@ CardinalityTransform key, can not have children.")
        children: list[_LeafSpec | _CompositeSpec] = []
        seen: set[str] = set()
        for k, rhs in spec.items():
            child: _LeafSpec | _CompositeSpec = (
                _CompositeSpec(k, rhs) if isinstance(rhs, dict) else _LeafSpec(k, rhs)
            )
            canonical = child.path_element.canonical_form
            if canonical in seen:
                raise SpecError(f"Duplicate canonical CardinalityTransform key found : {canonical}")
            seen.add(canonical)
            children.append(child)
        if not children:
            raise SpecError(
                "CardinalitySpec format error : CardinalitySpec line with empty {} as value is "
                "not valid."
            )
        self.special_child: _LeafSpec | None = None
        self.literal_children: dict[str, _LeafSpec | _CompositeSpec] = {}
        computed = []
        for child in children:
            # The reference registers every child by its raw key, so even a "*" child
            # matches a data key that is literally "*".
            self.literal_children[child.path_element.raw_key] = child
            if isinstance(child.path_element, LiteralPathElement):
                continue
            if isinstance(child.path_element, AtPathElement):
                if not isinstance(child, _LeafSpec):
                    raise SpecError("@ CardinalityTransform key, can not have children.")
                self.special_child = child
            else:
                computed.append(child)
        computed.sort(key=computed_sort_key(_ORDER))
        self.computed_children = computed

    def apply_cardinality(
        self, input_key: str, value: Any, walked_path: WalkedPath, parent: Any
    ) -> bool:
        this_level = self.path_element.match(input_key, walked_path)
        if this_level is None:
            return False
        walked_path.add(value, this_level)
        if self.special_child is not None:
            value = self.special_child.apply_to_parent_container(
                input_key, value, walked_path, parent
            )
        self._process(value, walked_path)
        walked_path.remove_last()
        return True

    def _process(self, value: Any, walked_path: WalkedPath) -> None:
        if isinstance(value, dict):
            for key, sub in list(value.items()):
                self._apply_key(key, sub, walked_path, value)
        elif isinstance(value, list):
            for i in range(len(value)):
                self._apply_key(str(i), value[i], walked_path, value)
        elif value is not None:
            scalar = java_str(value)
            self._apply_key(scalar, None, walked_path, scalar)

    def _apply_key(self, key: str, sub: Any, walked_path: WalkedPath, parent: Any) -> None:
        literal = self.literal_children.get(key)
        if literal is not None:
            literal.apply_cardinality(key, sub, walked_path, parent)
            return
        for child in self.computed_children:
            if child.apply_cardinality(key, sub, walked_path, parent):
                break


class Cardinality(Transform):
    """Force values to be a single item (``"ONE"``) or a list (``"MANY"``).

    Example::

        Cardinality({"tags": "MANY", "photo": "ONE"}).apply(
            {"tags": "a", "photo": ["p1.jpg", "p2.jpg"]}
        )  # -> {"tags": ["a"], "photo": "p1.jpg"}
    """

    __slots__ = ("_root",)

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Cardinality expected a spec of Map type, got {type(spec).__name__}")
        self._root = _CompositeSpec("root", spec)

    def apply(self, input_data: Any) -> Any:
        return self._apply_owned(deep_copy(input_data))

    def _apply_owned(self, data: Any, context: dict[str, Any] | None = None) -> Any:
        self._root.apply_cardinality("root", data, WalkedPath(), None)
        return data
