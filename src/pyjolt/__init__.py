# Copyright 2024 Sthitaprajna Sahoo
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

"""pyjolt — high-performance Python implementation of the JOLT JSON transformation library.

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

from .chainr import Chainr
from .exceptions import PyJoltError, SpecError, TransformError
from .transforms import (
    Cardinality,
    Default,
    ModifyDefault,
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
    # Exceptions
    "PyJoltError",
    "SpecError",
    "TransformError",
    # Version
    "__version__",
]

try:
    __version__: str = version("pyjolt")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "1.0.0"
