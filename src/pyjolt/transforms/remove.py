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

"""Remove transform — delete keys from JSON.

The spec mirrors the input structure.  A leaf value of any non-dict type
(string, number, ``True``, ``""`` …) means *remove that key*.  A dict value
means *descend and remove the nested keys*.

The wildcard key ``*`` removes every key at that level (or every element of
a list).
"""

from __future__ import annotations

from typing import Any

from ..exceptions import SpecError
from .base import Transform


def _apply_remove(data: Any, spec: Any) -> Any:
    """Return a copy of *data* with keys specified in *spec* removed."""
    if not isinstance(spec, dict):
        return data  # leaf spec reached without a dict input — leave as-is

    if isinstance(data, dict):
        result: dict[str, Any] = {}
        wildcard = spec.get("*")

        for key, val in data.items():
            key_spec = spec.get(key)

            if key_spec is None and wildcard is None:
                # Nothing in the spec for this key — keep it
                result[key] = val
                continue

            # Determine effective spec for this key
            effective = key_spec if key_spec is not None else wildcard

            if isinstance(effective, dict):
                # Recurse into the nested structure
                result[key] = _apply_remove(val, effective)
            else:
                # Non-dict spec value means "remove this key" — omit from result
                pass  # skip — key is removed

        return result

    if isinstance(data, list):
        # Apply the spec to each list element
        wildcard = spec.get("*")
        if wildcard is not None and isinstance(wildcard, dict):
            return [_apply_remove(item, wildcard) for item in data]
        if wildcard is not None:
            # Scalar wildcard value means "remove all elements"
            return []
        return data

    return data


class Remove(Transform):
    """Delete keys/fields from a JSON object.

    Parameters
    ----------
    spec:
        A dict whose keys name the fields to remove.  A non-dict leaf value
        (``""``, ``True``, etc.) signals removal; a dict value triggers
        recursive removal of its children.

    Examples
    --------
    >>> r = Remove({"secret": "", "meta": {"internal": ""}})
    >>> r.apply({"name": "alice", "secret": "xyz", "meta": {"internal": 1, "v": 2}})
    {'name': 'alice', 'meta': {'v': 2}}

    Remove all keys with wildcard::

        r = Remove({"*": ""})
        r.apply({"a": 1, "b": 2})
        # -> {}
    """

    __slots__ = ("_spec",)

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Remove spec must be a dict, got {type(spec).__name__!r}")
        self._spec = spec

    def apply(self, input_data: Any) -> Any:
        return _apply_remove(input_data, self._spec)
