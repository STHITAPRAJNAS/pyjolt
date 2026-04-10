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
]

__version__ = "0.1.0"
