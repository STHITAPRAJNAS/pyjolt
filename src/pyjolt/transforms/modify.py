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

"""Modify transforms — compute values with functions, in place.

A port of the reference ``Modifier``, in three flavours:

* :class:`ModifyOverwrite` (``modify-overwrite-beta``) — always writes.
* :class:`ModifyDefault` (``modify-default-beta``) — writes only where the
  value is missing or ``null``.
* :class:`ModifyDefine` (``modify-define-beta``) — writes only where the key
  does not exist at all.

The spec mirrors the shape of the input. Keys are literals, ``*`` wildcards,
``a|b`` alternatives or array indexes (``"[0]"``). A key may start with ``+``,
``~`` or ``_`` to use overwrite / default / define for just that key, and may
end with ``?`` to apply only when the key exists.

Leaf values
    * ``"=fn"`` — apply ``fn`` to the current value, e.g. ``"=toUpper"``.
    * ``"=fn(arg, ...)"`` — call ``fn`` with the given args. Args are
      literals (``5``, ``true``, ``'quoted text'``), ``@(n,path)`` lookups
      into the input, or ``^path`` lookups into the context.
    * ``"@(n,path)"`` / ``"^path"`` — copy a value from the input / context.
    * a list of the above — the first one that produces a value wins.
    * anything else — written as-is.

If a function produces no value (wrong argument types, a missing lookup), the
field is left unchanged. See :mod:`pyjolt._common.functions` for the list of
functions.
"""

from __future__ import annotations

import warnings
from collections.abc import Callable
from typing import Any

from .._common.functions import FUNCTIONS, to_number
from .._common.paths import (
    ArrayMatchedElement,
    ArrayPathElement,
    LiteralPathElement,
    MatchedElement,
    PathElement,
    PathEvaluatingTraversal,
    StarAllPathElement,
    StarDoublePathElement,
    StarPathElement,
    StarRegexPathElement,
    StarSinglePathElement,
    TransposePathElement,
    WalkedPath,
    build_matchable_path_element,
    parse_function_args,
)
from .._common.spec import (
    ExecutionStrategy,
    computed_sort_key,
    create_specs,
)
from .._common.util import MISSING, ROOT_KEY, deep_copy, try_parse_int
from ..exceptions import SpecError
from .base import Transform

_OVERWRITE, _DEFAULT, _DEFINE = "+", "~", "_"
_MODE_NAMES = {_OVERWRITE: "OVERWRITR", _DEFAULT: "DEFAULTR", _DEFINE: "DEFINER"}


# ---------------------------------------------------------------------------
# Op modes
# ---------------------------------------------------------------------------


def _map_applicable(mode: str, source: Any, key: str | None) -> bool:
    if source is None or key is None:
        return False
    if mode == _DEFAULT:
        return source.get(key) is None
    if mode == _DEFINE:
        return key not in source
    return True


def _list_applicable(mode: str, source: Any, index: int, orig_size: int | None) -> bool:
    if source is None or index < 0 or orig_size is None or orig_size < 0:
        return False
    if mode == _OVERWRITE:
        return True
    if index >= len(source):
        return False
    if mode == _DEFAULT:
        return source[index] is None
    return index >= orig_size and source[index] is None


def _set_data(parent: Any, matched: MatchedElement, value: Any, mode: str) -> None:
    if isinstance(parent, dict):
        if _map_applicable(mode, parent, matched.raw_key):
            parent[matched.raw_key] = value
    elif isinstance(parent, list) and isinstance(matched, ArrayMatchedElement):
        index = matched.raw_index
        if _list_applicable(mode, parent, index, matched.orig_size):
            while len(parent) <= index:
                parent.append(None)
            parent[index] = value
    # Otherwise the spec is deeper than the data (the parent is a scalar): the
    # reference fails with "Should not come here!"; pyjolt leaves the data alone.


# ---------------------------------------------------------------------------
# Data types of composite specs
# ---------------------------------------------------------------------------


class _DataType:
    """Whether a composite spec expects an object, an array, or either (RUNTIME)."""

    __slots__ = ("kind", "max_index")

    def __init__(self, kind: str, max_index: int = -1) -> None:
        self.kind = kind  # "list" | "map" | "runtime"
        self.max_index = max_index

    def is_compatible(self, value: Any) -> bool:
        if self.kind == "list":
            return value is None or isinstance(value, list)
        if self.kind == "map":
            return value is None or isinstance(value, dict)
        return value is not None

    def expand(self, source: list[Any]) -> int:
        orig_size = len(source)
        while len(source) <= self.max_index:
            source.append(None)
        return orig_size

    def create(self, key: str, walked_path: WalkedPath, mode: str) -> Any:
        last = walked_path.last_element()
        parent = last.tree_ref
        if self.kind == "runtime":
            return None
        value: Any = None
        if isinstance(parent, dict) and _map_applicable(mode, parent, key):
            value = [] if self.kind == "list" else {}
            parent[key] = value
        elif isinstance(parent, list):
            index = try_parse_int(key)
            if (
                index is not None
                and index < len(parent)
                and _list_applicable(mode, parent, index, last.orig_size)
            ):
                value = [] if self.kind == "list" else {}
                parent[index] = value
        return value


# ---------------------------------------------------------------------------
# Function arguments and evaluation
# ---------------------------------------------------------------------------


class _Arg:
    __slots__ = ("kind", "value")

    def __init__(self, kind: str, value: Any) -> None:
        self.kind = kind  # "literal" | "self" | "context"
        self.value = value

    def evaluate(self, walked_path: WalkedPath, context: Any) -> Any:
        if self.kind == "literal":
            return self.value
        if self.kind == "self":
            pe: TransposePathElement = self.value
            return pe.object_evaluate(walked_path)
        reader: PathEvaluatingTraversal = self.value
        return reader.read(context, walked_path)


def _reader(path: str) -> PathEvaluatingTraversal:
    return PathEvaluatingTraversal(f"{ROOT_KEY}.{path}", writer=False)


def _literal_arg(arg: Any, parse: bool) -> _Arg:
    if not parse or not isinstance(arg, str):
        return _Arg("literal", arg)
    if arg == "":
        return _Arg("literal", None)
    if len(arg) >= 2 and arg.startswith("'") and arg.endswith("'"):
        return _Arg("literal", arg[1:-1])
    if arg.lower() in ("true", "false"):
        return _Arg("literal", arg.lower() == "true")
    n = to_number(arg)
    return _Arg("literal", arg if n is None else n)


def _single_arg(arg: str, for_function: bool) -> _Arg:
    if arg.startswith("^"):
        return _Arg("context", _reader(arg[1:]))
    if arg.startswith("@"):
        reader = _reader(arg)
        last = reader.elements[-1]
        if not isinstance(last, TransposePathElement):
            raise SpecError(f"Expected @ path element here: {arg}")
        return _Arg("self", last)
    return _literal_arg(arg, for_function)


class _Evaluator:
    __slots__ = ("function", "args")

    def __init__(self, function: Callable[..., Any] | None, args: list[_Arg]) -> None:
        self.function = function
        self.args = args

    def evaluate(self, input_value: Any, walked_path: WalkedPath, context: Any) -> Any:
        try:
            fn = self.function
            if fn is None:
                return self.args[0].evaluate(walked_path, context)
            if len(self.args) == 1:
                value = self.args[0].evaluate(walked_path, context)
                return fn() if value is MISSING else fn(value)
            if len(self.args) > 1:
                values = [a.evaluate(walked_path, context) for a in self.args]
                return fn(*(None if v is MISSING else v for v in values))
            return fn() if input_value is MISSING else fn(input_value)
        except Exception:  # noqa: BLE001 - the reference treats any failure as "no value"
            return MISSING


def _build_evaluator(rhs: str, functions: dict[str, Callable[..., Any]]) -> _Evaluator:
    if not rhs.startswith("="):
        return _Evaluator(None, [_single_arg(rhs, for_function=False)])
    body = rhs[1:]
    if "(" not in body and not body.endswith(")"):
        name, args = body, []
    else:
        parts = parse_function_args(body)
        name, args = parts[0], [_single_arg(a, for_function=True) for a in parts[1:]]
    fn = functions.get(name)
    if fn is None:
        # The reference treats an unknown function as producing no value, which
        # lets a list of alternatives fall through to the next one. Keep that,
        # but make typos visible.
        warnings.warn(
            f"Unknown modify function {name!r} in {rhs!r}; it will produce no value",
            UserWarning,
            stacklevel=2,
        )
        return _Evaluator(_no_value, args)
    return _Evaluator(fn, args)


def _no_value(*_args: Any) -> Any:
    return MISSING


# ---------------------------------------------------------------------------
# Specs
# ---------------------------------------------------------------------------

_COMPUTED_ORDER: dict[type, int] = {
    ArrayPathElement: 1,
    StarRegexPathElement: 2,
    StarDoublePathElement: 3,
    StarSinglePathElement: 4,
    StarAllPathElement: 5,
}


class _Spec:
    __slots__ = ("mode", "path_element", "check_value")

    def __init__(self, raw_key: str, mode: str) -> None:
        if raw_key and raw_key[0] in _MODE_NAMES:
            self.mode = raw_key[0]
            raw_key = raw_key[1:]
        else:
            self.mode = mode
        self.check_value = raw_key.endswith("?") and not raw_key.endswith("\\?")
        if self.check_value:
            raw_key = raw_key[:-1]
        self.path_element: PathElement = build_matchable_path_element(raw_key)
        if not isinstance(
            self.path_element, (StarPathElement, LiteralPathElement, ArrayPathElement)
        ):
            raise SpecError(
                f"{_MODE_NAMES[mode]} cannot have {type(self.path_element).__name__} RHS"
            )

    def apply(
        self, input_key: str, input_value: Any, walked_path: WalkedPath, output: Any, ctx: Any
    ) -> bool:
        this_level = self.path_element.match(input_key, walked_path)
        if this_level is None:
            return False
        if not self.check_value or input_value is not MISSING:
            self.apply_element(input_key, input_value, this_level, walked_path, ctx)
        return True

    def apply_element(
        self,
        key: str,
        input_value: Any,
        this_level: MatchedElement,
        walked_path: WalkedPath,
        ctx: Any,
    ) -> None:
        raise NotImplementedError


class _LeafSpec(_Spec):
    __slots__ = ("evaluators",)

    def __init__(
        self, raw_key: str, rhs: Any, mode: str, functions: dict[str, Callable[..., Any]]
    ) -> None:
        super().__init__(raw_key, mode)
        if isinstance(rhs, str):
            self.evaluators = [_build_evaluator(rhs, functions)]
        elif isinstance(rhs, list) and rhs:
            self.evaluators = [
                _build_evaluator(r, functions)
                if isinstance(r, str)
                else _Evaluator(None, [_literal_arg(r, parse=False)])
                for r in rhs
            ]
        else:
            self.evaluators = [_Evaluator(None, [_literal_arg(rhs, parse=False)])]

    def apply_element(
        self,
        key: str,
        input_value: Any,
        this_level: MatchedElement,
        walked_path: WalkedPath,
        ctx: Any,
    ) -> None:
        parent = walked_path.last_element().tree_ref
        walked_path.add(None if input_value is MISSING else input_value, this_level)
        value: Any = MISSING
        for evaluator in self.evaluators:
            value = evaluator.evaluate(input_value, walked_path, ctx)
            if value is not MISSING:
                break
        if value is not MISSING:
            _set_data(parent, this_level, deep_copy(value), self.mode)
        walked_path.remove_last()


class _CompositeSpec(_Spec):
    __slots__ = ("literal_children", "computed_children", "strategy", "data_type")

    def __init__(
        self,
        raw_key: str,
        spec: dict[str, Any],
        mode: str,
        functions: dict[str, Callable[..., Any]],
    ) -> None:
        super().__init__(raw_key, mode)

        def build(key: str, rhs: Any) -> _Spec:
            if isinstance(rhs, dict) and rhs:
                return _CompositeSpec(key, rhs, mode, functions)
            return _LeafSpec(key, rhs, mode, functions)

        children: list[_Spec] = create_specs(spec, build)
        self.literal_children: dict[str, _Spec] = {}
        computed: list[_Spec] = []
        max_index = confirmed_map = confirmed_array = -1
        for i, child in enumerate(children):
            pe = child.path_element
            if isinstance(pe, LiteralPathElement):
                confirmed_map = i
                self.literal_children[pe.raw_key] = child
            elif isinstance(pe, ArrayPathElement):
                confirmed_array = i
                if not pe.is_explicit_array_index:
                    raise SpecError(
                        f"{_MODE_NAMES[mode]} RHS only supports explicit Array path element"
                    )
                index = pe.explicit_array_index
                assert index is not None
                if not child.check_value:
                    max_index = max(max_index, index)
                self.literal_children[str(index)] = child
            else:
                if not isinstance(pe, StarAllPathElement):
                    confirmed_map = i
                computed.append(child)
            if confirmed_map > -1 and confirmed_array > -1:
                raise SpecError(
                    f"{_MODE_NAMES[mode]} RHS cannot mix int array index and string map key, "
                    f"defined spec for {raw_key} contains: "
                    f"{children[confirmed_map].path_element.canonical_form} conflicting "
                    f"{children[confirmed_array].path_element.canonical_form}"
                )
        if confirmed_array > -1:
            self.data_type = _DataType("list", max_index)
        elif confirmed_map > -1:
            self.data_type = _DataType("map")
        else:
            self.data_type = _DataType("runtime")
        computed.sort(key=computed_sort_key(_COMPUTED_ORDER))
        self.computed_children = computed

        if not computed:
            self.strategy = ExecutionStrategy.ALL_LITERALS
        elif not self.literal_children:
            self.strategy = ExecutionStrategy.COMPUTED
        elif self.mode == _DEFINE and self.data_type.kind == "list":
            self.strategy = ExecutionStrategy.CONFLICT
        else:
            self.strategy = ExecutionStrategy.ALL_LITERALS_WITH_COMPUTED

    def apply_element(
        self,
        key: str,
        input_value: Any,
        this_level: MatchedElement,
        walked_path: WalkedPath,
        ctx: Any,
    ) -> None:
        value = None if input_value is MISSING else input_value
        if not self.data_type.is_compatible(value):
            return
        if value is None:
            value = self.data_type.create(key, walked_path, self.mode)
            if value is not None:
                input_value = value
        if isinstance(value, list):
            if self.data_type.kind == "list":
                orig_size = self.data_type.expand(value)
            else:
                orig_size = len(value)
            this_level = ArrayMatchedElement(this_level.raw_key, orig_size)
        walked_path.add(value, this_level)
        self.strategy.process(self, input_value, walked_path, None, ctx)
        walked_path.remove_last()


# ---------------------------------------------------------------------------
# Public transforms
# ---------------------------------------------------------------------------


class _Modify(Transform):
    __slots__ = ("_root",)
    _MODE = _OVERWRITE

    def __init__(
        self,
        spec: dict[str, Any],
        functions: dict[str, Callable[..., Any]] | None = None,
    ) -> None:
        name = _MODE_NAMES[self._MODE]
        if not isinstance(spec, dict):
            raise SpecError(f"{name} expected a spec of Map type, got {type(spec).__name__}")
        registry = {**FUNCTIONS, **(functions or {})}
        self._root = _CompositeSpec(ROOT_KEY, spec, self._MODE, registry)

    def apply(self, input_data: Any, context: dict[str, Any] | None = None) -> Any:
        """Apply the spec to a copy of *input_data*.

        *context* is an optional dict that ``^path`` arguments read from.
        """
        return self._apply_owned(deep_copy(input_data), context)

    def _apply_owned(self, data: Any, context: dict[str, Any] | None = None) -> Any:
        walked_path = WalkedPath()
        walked_path.add(data, MatchedElement(ROOT_KEY))
        self._root.apply(ROOT_KEY, data, walked_path, None, {ROOT_KEY: context})
        return data


class ModifyOverwrite(_Modify):
    """``modify-overwrite-beta``: always write the computed value.

    Example::

        ModifyOverwrite({"name": "=toUpper", "n": "=toInteger"}).apply({"name": "ana", "n": "7"})
        # -> {"name": "ANA", "n": 7}

    Custom functions can be added with ``functions={"name": callable}``; a
    callable receives the evaluated arguments and returns the new value, or
    :data:`pyjolt.MISSING` to leave the field unchanged.
    """

    __slots__ = ()
    _MODE = _OVERWRITE


class ModifyDefault(_Modify):
    """``modify-default-beta``: write only where the value is missing or ``null``."""

    __slots__ = ()
    _MODE = _DEFAULT


class ModifyDefine(_Modify):
    """``modify-define-beta``: write only where the key does not exist."""

    __slots__ = ()
    _MODE = _DEFINE
