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

"""Shift transform — re-maps fields from one JSON path to another.

A port of the reference ``Shiftr``: the spec mirrors the shape of the input,
and each leaf says where the matched value is written in the output.

LHS (spec keys)
    ``literal``, ``*`` / ``a*b`` wildcards, ``a|b`` alternatives, ``&n`` keys
    built from parent matches, ``@`` (the current value), ``@(n,path)``
    (a value looked up in the input), ``$`` / ``$n`` (the matched key itself),
    ``#value`` (a constant), and ``\\`` to escape any of these characters.

RHS (output paths)
    dot-separated keys using ``&``, ``&n``, ``&(n,m)``, ``@(n,path)``,
    ``[]`` (append), ``[n]`` / ``[&n]`` / ``[#n]`` / ``[@(n,path)]`` (array
    index) and ``\\`` escapes. An empty string writes to the output root, and a
    list of paths writes the value to each of them. Values written to the
    same place are collected into a list.
"""

from __future__ import annotations

from typing import Any

from .._common.paths import (
    AmpPathElement,
    AtPathElement,
    DollarPathElement,
    HashPathElement,
    LiteralPathElement,
    MatchedElement,
    PathElement,
    PathEvaluatingTraversal,
    StarAllPathElement,
    StarDoublePathElement,
    StarRegexPathElement,
    StarSinglePathElement,
    TransposePathElement,
    WalkedPath,
    build_matchable_path_element,
    build_writer,
)
from .._common.spec import (
    computed_sort_key,
    create_specs,
    determine_execution_strategy,
)
from .._common.util import MISSING, ROOT_KEY, deep_copy
from ..exceptions import SpecError
from .base import Transform

_COMPUTED_ORDER: dict[type, int] = {
    AmpPathElement: 1,
    StarRegexPathElement: 2,
    StarDoublePathElement: 3,
    StarSinglePathElement: 4,
    StarAllPathElement: 5,
}
_SPECIAL = (AtPathElement, HashPathElement, DollarPathElement, TransposePathElement)


def _build(key: str, rhs: Any) -> _LeafSpec | _CompositeSpec:
    if isinstance(rhs, dict):
        return _CompositeSpec(key, rhs)
    return _LeafSpec(key, rhs)


class _LeafSpec:
    __slots__ = ("path_element", "writers")

    def __init__(self, key: str, rhs: Any) -> None:
        self.path_element: PathElement = build_matchable_path_element(key)
        if isinstance(rhs, str):
            self.writers: list[PathEvaluatingTraversal] = [build_writer(rhs)]
        elif isinstance(rhs, list):
            self.writers = [build_writer(r) for r in rhs]
        elif rhs is None:
            self.writers = []
        else:
            raise SpecError(
                "Invalid Shiftr spec RHS.  Should be map, string, or array of strings.  "
                f"Spec in question : {rhs!r}"
            )

    def apply(
        self, input_key: str, input_value: Any, walked_path: WalkedPath, output: Any, ctx: Any
    ) -> bool:
        value = None if input_value is MISSING else input_value
        this_level = self.path_element.match(input_key, walked_path)
        if this_level is None:
            return False

        pe = self.path_element
        real_child = False
        if isinstance(pe, (DollarPathElement, HashPathElement)):
            data: Any = this_level.canonical_form
        elif isinstance(pe, AtPathElement):
            data = value
        elif isinstance(pe, TransposePathElement):
            data = pe.object_evaluate(walked_path)
            if data is MISSING:
                return False
        else:
            data = value
            real_child = True

        walked_path.add(value, this_level)
        for writer in self.writers:
            writer.write(data, output, walked_path)
        walked_path.remove_last()

        if real_child:
            walked_path.last_element().matched_element.increment_hash_count()
        return real_child


class _CompositeSpec:
    __slots__ = (
        "path_element",
        "special_children",
        "literal_children",
        "computed_children",
        "strategy",
    )

    def __init__(self, key: str, spec: dict[str, Any]) -> None:
        self.path_element: PathElement = build_matchable_path_element(key)
        if isinstance(self.path_element, AtPathElement):
            raise SpecError("@ Shiftr key, can not have children.")
        if isinstance(self.path_element, DollarPathElement):
            raise SpecError("$ Shiftr key, can not have children.")

        children = create_specs(spec, _build)
        if not children:
            raise SpecError(
                "Shift ShiftrSpec format error : ShiftrSpec line with empty {} as value is not valid."
            )
        self.special_children: list[Any] = []
        self.literal_children: dict[str, Any] = {}
        computed: list[Any] = []
        for child in children:
            cpe = child.path_element
            if isinstance(cpe, LiteralPathElement):
                self.literal_children[cpe.raw_key] = child
            elif isinstance(cpe, _SPECIAL):
                self.special_children.append(child)
            else:
                computed.append(child)
        computed.sort(key=computed_sort_key(_COMPUTED_ORDER))
        self.computed_children = computed
        self.strategy = determine_execution_strategy(self)

    def apply(
        self, input_key: str, input_value: Any, walked_path: WalkedPath, output: Any, ctx: Any
    ) -> bool:
        this_level = self.path_element.match(input_key, walked_path)
        if this_level is None:
            return False

        pe = self.path_element
        if isinstance(pe, TransposePathElement):
            input_value = pe.object_evaluate(walked_path)
            if input_value is MISSING:
                return False

        walked_path.add(None if input_value is MISSING else input_value, this_level)
        for child in self.special_children:
            child.apply(input_key, input_value, walked_path, output, ctx)
        self.strategy.process(self, input_value, walked_path, output, ctx)
        walked_path.remove_last()

        walked_path.last_element().matched_element.increment_hash_count()
        return True


class Shift(Transform):
    """Move data from one place in the JSON tree to another.

    Returns ``None`` when nothing in the input matched the spec, like the
    reference implementation.

    Example::

        Shift({"rating": {"primary": {"value": "Rating"}}}).apply(
            {"rating": {"primary": {"value": 3}}}
        )  # -> {"Rating": 3}
    """

    __slots__ = ("_root",)

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Shift expected a spec of Map type, got {type(spec).__name__}")
        self._root = _CompositeSpec(ROOT_KEY, spec)

    def apply(self, input_data: Any) -> Any:
        # Copy so that values accumulated into lists never alias the caller's input.
        return self._apply_owned(deep_copy(input_data))

    def _apply_owned(self, input_data: Any, context: dict[str, Any] | None = None) -> Any:
        output: dict[str, Any] = {}
        walked_path = WalkedPath()
        walked_path.add(input_data, MatchedElement(ROOT_KEY))
        self._root.apply(ROOT_KEY, input_data, walked_path, output, None)
        return output.get(ROOT_KEY)
