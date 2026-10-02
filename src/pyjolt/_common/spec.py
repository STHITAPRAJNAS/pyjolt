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

"""Spec tree building and the strategies a composite spec uses to walk its input.

Ports ``com.bazaarvoice.jolt.common.spec`` and ``ExecutionStrategy``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from enum import Enum
from typing import Any, Protocol

from ..exceptions import SpecError
from .paths import PathElement, StarPathElement, WalkedPath
from .util import MISSING, java_str, try_parse_int


class BaseSpec(Protocol):
    path_element: PathElement

    def apply(
        self,
        input_key: str,
        input_value: Any,
        walked_path: WalkedPath,
        output: Any,
        context: Any,
    ) -> bool: ...


class OrderedCompositeSpec(Protocol):
    @property
    def literal_children(self) -> Mapping[str, Any]: ...

    @property
    def computed_children(self) -> Sequence[Any]: ...


def create_specs(raw_spec: dict[str, Any], factory: Callable[[str, Any], BaseSpec]) -> list[Any]:
    """Build child specs, expanding ``a|b`` keys and rejecting duplicate keys."""
    result = []
    seen: set[str] = set()
    for raw_lhs, raw_rhs in raw_spec.items():
        for key in str(raw_lhs).split("|"):
            child = factory(key, raw_rhs)
            canonical = child.path_element.canonical_form
            if canonical in seen:
                raise SpecError(f"Duplicate canonical key found : {canonical}")
            seen.add(canonical)
            result.append(child)
    return result


def computed_sort_key(order: dict[type, int]) -> Callable[[Any], tuple[int, int, str]]:
    """``ComputedKeysComparator``: by element kind, then longest canonical form, then text."""

    def key(spec: Any) -> tuple[int, int, str]:
        pe = spec.path_element
        cf = pe.canonical_form
        return order.get(type(pe), len(order) + 1), -len(cf), cf

    return key


class ExecutionStrategy(Enum):
    AVAILABLE_LITERALS = "available_literals"
    ALL_LITERALS = "all_literals"
    COMPUTED = "computed"
    CONFLICT = "conflict"
    AVAILABLE_LITERALS_WITH_COMPUTED = "available_literals_with_computed"
    ALL_LITERALS_WITH_COMPUTED = "all_literals_with_computed"

    def process(
        self,
        spec: OrderedCompositeSpec,
        input_value: Any,
        walked_path: WalkedPath,
        output: Any,
        context: Any,
    ) -> None:
        value = None if input_value is MISSING else input_value
        if isinstance(value, dict):
            handler = _MAP[self]
        elif isinstance(value, list):
            handler = _LIST[self]
        elif value is not None:
            _SCALAR[self](spec, java_str(value), walked_path, output, context)
            return
        else:
            return
        handler(spec, value, walked_path, output, context)


def determine_execution_strategy(spec: OrderedCompositeSpec) -> ExecutionStrategy:
    if not spec.computed_children:
        return ExecutionStrategy.AVAILABLE_LITERALS
    if not spec.literal_children:
        return ExecutionStrategy.COMPUTED
    for computed in spec.computed_children:
        pe = computed.path_element
        if not isinstance(pe, StarPathElement):
            return ExecutionStrategy.CONFLICT
        for literal in spec.literal_children:
            if pe.string_match(literal):
                return ExecutionStrategy.CONFLICT
    return ExecutionStrategy.AVAILABLE_LITERALS_WITH_COMPUTED


# --- shared pieces ---------------------------------------------------------


def _apply_to_computed(
    children: Sequence[Any], walked_path: WalkedPath, output: Any, key: str, sub: Any, ctx: Any
) -> None:
    for child in children:
        if child.apply(key, sub, walked_path, output, ctx):
            break


def _apply_to_literal_and_computed(
    spec: OrderedCompositeSpec, key: str, sub: Any, walked_path: WalkedPath, output: Any, ctx: Any
) -> None:
    literal = spec.literal_children.get(key)
    if literal is not None:
        literal.apply(key, sub, walked_path, output, ctx)
    else:
        _apply_to_computed(spec.computed_children, walked_path, output, key, sub, ctx)


def _list_item(items: list[Any], index: int, orig_size: int | None) -> Any:
    value = items[index]
    if value is None and orig_size is not None and index >= orig_size:
        return MISSING
    return value


# --- AVAILABLE_LITERALS ----------------------------------------------------


def _avail_map(spec: Any, data: dict[str, Any], wp: WalkedPath, out: Any, ctx: Any) -> None:
    for key, child in spec.literal_children.items():
        if key in data:
            child.apply(key, data[key], wp, out, ctx)


def _avail_list(spec: Any, data: list[Any], wp: WalkedPath, out: Any, ctx: Any) -> None:
    orig_size = wp.last_element().orig_size
    for key, child in spec.literal_children.items():
        idx = try_parse_int(key)
        if idx is not None and 0 <= idx < len(data):
            child.apply(key, _list_item(data, idx, orig_size), wp, out, ctx)


def _avail_scalar(spec: Any, data: str, wp: WalkedPath, out: Any, ctx: Any) -> None:
    child = spec.literal_children.get(data)
    if child is not None:
        child.apply(data, MISSING, wp, out, ctx)


# --- ALL_LITERALS ----------------------------------------------------------


def _all_map(spec: Any, data: dict[str, Any], wp: WalkedPath, out: Any, ctx: Any) -> None:
    for key, child in spec.literal_children.items():
        child.apply(key, data.get(key, MISSING), wp, out, ctx)


def _all_list(spec: Any, data: list[Any], wp: WalkedPath, out: Any, ctx: Any) -> None:
    orig_size = wp.last_element().orig_size
    for key, child in spec.literal_children.items():
        idx = try_parse_int(key)
        sub: Any = MISSING
        if idx is not None and 0 <= idx < len(data):
            sub = _list_item(data, idx, orig_size)
        child.apply(key, sub, wp, out, ctx)


# --- COMPUTED --------------------------------------------------------------


def _comp_map(spec: Any, data: dict[str, Any], wp: WalkedPath, out: Any, ctx: Any) -> None:
    for key, value in list(data.items()):
        _apply_to_computed(spec.computed_children, wp, out, key, value, ctx)


def _comp_list(spec: Any, data: list[Any], wp: WalkedPath, out: Any, ctx: Any) -> None:
    orig_size = wp.last_element().orig_size
    for i in range(len(data)):
        sub = _list_item(data, i, orig_size)
        _apply_to_computed(spec.computed_children, wp, out, str(i), sub, ctx)


def _comp_scalar(spec: Any, data: str, wp: WalkedPath, out: Any, ctx: Any) -> None:
    _apply_to_computed(spec.computed_children, wp, out, data, MISSING, ctx)


# --- CONFLICT --------------------------------------------------------------


def _conf_map(spec: Any, data: dict[str, Any], wp: WalkedPath, out: Any, ctx: Any) -> None:
    for key, value in list(data.items()):
        _apply_to_literal_and_computed(spec, key, value, wp, out, ctx)


def _conf_list(spec: Any, data: list[Any], wp: WalkedPath, out: Any, ctx: Any) -> None:
    orig_size = wp.last_element().orig_size
    for i in range(len(data)):
        sub = _list_item(data, i, orig_size)
        _apply_to_literal_and_computed(spec, str(i), sub, wp, out, ctx)


def _conf_scalar(spec: Any, data: str, wp: WalkedPath, out: Any, ctx: Any) -> None:
    _apply_to_literal_and_computed(spec, data, MISSING, wp, out, ctx)


def _both(*fns: Callable[..., None]) -> Callable[..., None]:
    def run(*args: Any) -> None:
        for fn in fns:
            fn(*args)

    return run


_S = ExecutionStrategy
_MAP: dict[ExecutionStrategy, Callable[..., None]] = {
    _S.AVAILABLE_LITERALS: _avail_map,
    _S.ALL_LITERALS: _all_map,
    _S.COMPUTED: _comp_map,
    _S.CONFLICT: _conf_map,
    _S.AVAILABLE_LITERALS_WITH_COMPUTED: _both(_avail_map, _comp_map),
    _S.ALL_LITERALS_WITH_COMPUTED: _both(_all_map, _comp_map),
}
_LIST: dict[ExecutionStrategy, Callable[..., None]] = {
    _S.AVAILABLE_LITERALS: _avail_list,
    _S.ALL_LITERALS: _all_list,
    _S.COMPUTED: _comp_list,
    _S.CONFLICT: _conf_list,
    _S.AVAILABLE_LITERALS_WITH_COMPUTED: _both(_avail_list, _comp_list),
    _S.ALL_LITERALS_WITH_COMPUTED: _both(_all_list, _comp_list),
}
_SCALAR: dict[ExecutionStrategy, Callable[..., None]] = {
    _S.AVAILABLE_LITERALS: _avail_scalar,
    _S.ALL_LITERALS: _avail_scalar,
    _S.COMPUTED: _comp_scalar,
    _S.CONFLICT: _conf_scalar,
    _S.AVAILABLE_LITERALS_WITH_COMPUTED: _both(_avail_scalar, _comp_scalar),
    _S.ALL_LITERALS_WITH_COMPUTED: _both(_avail_scalar, _comp_scalar),
}
