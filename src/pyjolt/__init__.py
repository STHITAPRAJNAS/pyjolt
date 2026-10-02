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

"""pyjolt — a JOLT-compatible JSON-to-JSON transformation library for Python.

Quick start
-----------
>>> from pyjolt import Chainr
>>> spec = [
...     {"operation": "shift",   "spec": {"name": "fullName", "age": "years"}},
...     {"operation": "default", "spec": {"years": 0}},
... ]
>>> Chainr.from_spec(spec).apply({"name": "Alice", "age": 30})
{'fullName': 'Alice', 'years': 30}

Individual transforms can also be used directly::

    from pyjolt.transforms import Shift, Default, Remove, Sort, Cardinality
    from pyjolt.transforms import ModifyOverwrite, ModifyDefault
"""

from importlib.metadata import PackageNotFoundError, version

from ._common.util import MISSING
from .chainr import Chainr
from .exceptions import PyJoltError, SpecError, TransformError
from .transforms import (
    Cardinality,
    Default,
    ModifyDefault,
    ModifyDefine,
    ModifyOverwrite,
    Remove,
    Shift,
    Sort,
    Transform,
)

__all__ = [
    # Orchestration
    "Chainr",
    # Transforms
    "Transform",
    "Shift",
    "Default",
    "Remove",
    "Sort",
    "Cardinality",
    "ModifyOverwrite",
    "ModifyDefault",
    "ModifyDefine",
    # Exceptions
    "PyJoltError",
    "SpecError",
    "TransformError",
    # Custom modify functions return this for "no value"
    "MISSING",
    # Version
    "__version__",
]

try:
    __version__: str = version("jolt-py")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "1.0.0"
