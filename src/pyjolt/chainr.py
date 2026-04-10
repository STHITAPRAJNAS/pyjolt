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

"""Chainr — orchestrate a sequence of transforms.

The spec is a JSON array where each element has an ``"operation"`` key and an
optional ``"spec"`` key::

    [
        {"operation": "shift",   "spec": {...}},
        {"operation": "default", "spec": {...}},
        {"operation": "sort"}
    ]

Supported operation names
--------------------------
* ``"shift"``                  — :class:`~pyjolt.transforms.Shift`
* ``"default"``                — :class:`~pyjolt.transforms.Default`
* ``"remove"``                 — :class:`~pyjolt.transforms.Remove`
* ``"sort"``                   — :class:`~pyjolt.transforms.Sort`
* ``"cardinality"``            — :class:`~pyjolt.transforms.Cardinality`
* ``"modify-overwrite-beta"``  — :class:`~pyjolt.transforms.ModifyOverwrite`
* ``"modify-default-beta"``    — :class:`~pyjolt.transforms.ModifyDefault`
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .exceptions import SpecError
from .transforms.base import Transform
from .transforms.cardinality import Cardinality
from .transforms.default import Default
from .transforms.modify import ModifyDefault, ModifyOverwrite
from .transforms.remove import Remove
from .transforms.shift import Shift
from .transforms.sort import Sort

_OPERATIONS: dict[str, Callable[[Any], Transform]] = {
    "shift": Shift,
    "default": Default,
    "remove": Remove,
    "sort": Sort,
    "cardinality": Cardinality,
    "modify-overwrite-beta": ModifyOverwrite,
    "modify-default-beta": ModifyDefault,
}


class Chainr:
    """Chain multiple transforms and apply them sequentially.

    Parameters
    ----------
    transforms:
        An ordered list of :class:`~pyjolt.transforms.Transform` instances.

    Examples
    --------
    Build from a list of transform instances::

        from pyjolt import Chainr
        from pyjolt.transforms import Shift, Default

        chain = Chainr([
            Shift({"a": "b"}),
            Default({"b": 0}),
        ])
        chain.apply({"a": 5})   # -> {"b": 5}
        chain.apply({})          # -> {"b": 0}

    Build from a JOLT-style spec list::

        spec = [
            {"operation": "shift",   "spec": {"rating": "Rating"}},
            {"operation": "default", "spec": {"Rating": 0}},
        ]
        chain = Chainr.from_spec(spec)
        chain.apply({"rating": 4.5})  # -> {"Rating": 4.5}
    """

    def __init__(self, transforms: list[Transform]) -> None:
        self._transforms = list(transforms)

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    def from_spec(cls, spec: list[dict[str, Any]]) -> Chainr:
        """Create a :class:`Chainr` from a JOLT-style spec list.

        Parameters
        ----------
        spec:
            A list of dicts, each with at least an ``"operation"`` key.

        Raises
        ------
        SpecError
            If an operation name is unknown or the spec is malformed.
        """
        if not isinstance(spec, list):
            raise SpecError(f"Chainr spec must be a list, got {type(spec).__name__!r}")

        transforms: list[Transform] = []
        for i, entry in enumerate(spec):
            if not isinstance(entry, dict):
                raise SpecError(f"Chainr spec[{i}] must be a dict, got {type(entry).__name__!r}")
            op = entry.get("operation")
            if op is None:
                raise SpecError(f"Chainr spec[{i}] missing 'operation' key")
            klass = _OPERATIONS.get(str(op))
            if klass is None:
                raise SpecError(
                    f"Unknown operation {op!r} at spec[{i}]. "
                    f"Supported: {sorted(_OPERATIONS)}"
                )
            transform_spec = entry.get("spec", {})
            transforms.append(klass(transform_spec))

        return cls(transforms)

    # ------------------------------------------------------------------
    # Application
    # ------------------------------------------------------------------

    def apply(self, input_data: Any) -> Any:
        """Apply all transforms in order and return the final result.

        Parameters
        ----------
        input_data:
            The JSON-compatible Python object to transform.
        """
        result = input_data
        for transform in self._transforms:
            result = transform.apply(result)
        return result

    def __repr__(self) -> str:
        ops = [type(t).__name__ for t in self._transforms]
        return f"Chainr([{', '.join(ops)}])"

    def __len__(self) -> int:
        return len(self._transforms)
