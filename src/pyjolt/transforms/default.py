"""Default transform — fill in missing or null values.

The spec mirrors the target JSON structure.  For every key in the spec:

* If the key is absent in the input, add it with the spec value.
* If the key is present but its value is ``None``, replace it with the spec
  value.
* If the spec value is a **dict**, descend recursively.

Wildcard keys (``*``) apply defaults to every key at that level that has no
more-specific override.
"""

from __future__ import annotations

import copy
from typing import Any

from ..exceptions import SpecError
from .base import Transform


def _apply_defaults(data: Any, spec: Any) -> Any:
    """Return *data* with defaults from *spec* applied (non-destructive)."""
    if not isinstance(spec, dict):
        # Leaf spec value — used as-is by callers
        return data

    if not isinstance(data, dict):
        return data

    result = dict(data)
    wildcard_spec = spec.get("*")

    for key, spec_val in spec.items():
        if key == "*":
            continue

        if isinstance(spec_val, dict):
            if key not in result or result[key] is None:
                result[key] = _apply_defaults({}, spec_val)
            elif isinstance(result[key], dict):
                result[key] = _apply_defaults(result[key], spec_val)
            elif isinstance(result[key], list):
                # When the spec_val has a wildcard, apply its sub-spec to each
                # list element (e.g. {"repos": {"*": {"language": "unknown"}}}).
                wildcard = spec_val.get("*")
                if isinstance(wildcard, dict):
                    result[key] = [_apply_defaults(item, wildcard) for item in result[key]]
                else:
                    result[key] = [_apply_defaults(item, spec_val) for item in result[key]]
        else:
            if key not in result or result[key] is None:
                result[key] = copy.deepcopy(spec_val)

    # Apply wildcard defaults to every key that has no specific spec entry
    if wildcard_spec is not None:
        for key in list(result.keys()):
            if key in spec:
                continue
            if isinstance(wildcard_spec, dict):
                if result[key] is None or not isinstance(result[key], dict):
                    pass  # cannot descend into non-dict
                else:
                    result[key] = _apply_defaults(result[key], wildcard_spec)
            else:
                if result[key] is None:
                    result[key] = copy.deepcopy(wildcard_spec)

    return result


class Default(Transform):
    """Apply default values to absent or null fields.

    Parameters
    ----------
    spec:
        A dict whose structure mirrors the desired output.  Leaf values are
        used as defaults.  Nested dicts trigger recursive default-filling.

    Examples
    --------
    >>> d = Default({"status": "unknown", "meta": {"version": 1}})
    >>> d.apply({"name": "test"})
    {'name': 'test', 'status': 'unknown', 'meta': {'version': 1}}
    >>> d.apply({"name": "test", "status": "active"})
    {'name': 'test', 'status': 'active', 'meta': {'version': 1}}
    """

    __slots__ = ("_spec",)

    def __init__(self, spec: dict[str, Any]) -> None:
        if not isinstance(spec, dict):
            raise SpecError(f"Default spec must be a dict, got {type(spec).__name__!r}")
        self._spec = spec

    def apply(self, input_data: Any) -> Any:
        if isinstance(input_data, dict):
            return _apply_defaults(input_data, self._spec)
        if isinstance(input_data, list):
            return [_apply_defaults(item, self._spec) for item in input_data]
        return input_data
