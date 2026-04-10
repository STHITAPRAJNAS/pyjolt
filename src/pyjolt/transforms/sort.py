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

"""Sort transform — sort all dict keys alphabetically (recursively).

No spec is needed (pass an empty dict ``{}``).  The transform recursively
sorts every mapping in the data tree.  Lists retain their original order but
their elements are recursively sorted.
"""

from __future__ import annotations

from typing import Any

from .base import Transform


def _sort_recursive(val: Any) -> Any:
    if isinstance(val, dict):
        return {k: _sort_recursive(val[k]) for k in sorted(val)}
    if isinstance(val, list):
        return [_sort_recursive(item) for item in val]
    return val


class Sort(Transform):
    """Sort all dict keys in the JSON tree alphabetically.

    Parameters
    ----------
    spec:
        Ignored (pass ``{}`` for consistency with the JOLT interface).

    Examples
    --------
    >>> s = Sort({})
    >>> s.apply({"b": 2, "a": 1, "c": {"z": 26, "a": 1}})
    {'a': 1, 'b': 2, 'c': {'a': 1, 'z': 26}}
    """

    __slots__ = ()

    def __init__(self, spec: Any = None) -> None:  # noqa: ARG002
        pass

    def apply(self, input_data: Any) -> Any:
        return _sort_recursive(input_data)
