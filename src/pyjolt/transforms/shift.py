"""Shift transform — re-maps fields from one JSON path to another.

Spec format
-----------
The spec is a nested dict that mirrors the structure of the input JSON.
Each key in the spec matches a key in the input, and the value defines
where to write that data in the output.

Input-side key tokens
~~~~~~~~~~~~~~~~~~~~~
* ``*``         — wildcard: matches any key (``a*b`` is also valid)
* ``@``         — self-reference: use the current input value directly
* ``|``         — OR separator: ``"a|b"`` matches either ``a`` or ``b``
* Literal       — matches that exact key

Output-side path tokens (dot-separated string)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
* Literal       — a literal key name
* ``&`` / ``&N``      — key matched at N levels up (0 = current)
* ``&(N,M)``    — M-th wildcard capture group at N levels up
* ``@(N,path)`` — value found N levels up following *path*
* ``[]``        — array-append suffix: append rather than overwrite
* ``#value``    — literal string constant as output key

Multiple output paths
~~~~~~~~~~~~~~~~~~~~~
The spec value may be a **list** of strings to fan out one input value to
multiple output locations.

Examples
--------
>>> from pyjolt import Chainr
>>> spec = [{"operation": "shift", "spec": {"rating": "Rating"}}]
>>> Chainr.from_spec(spec).apply({"rating": 4.5})
{'Rating': 4.5}
"""

from __future__ import annotations

import re
from typing import Any

from ..exceptions import SpecError, TransformError
from .base import Transform

# ---------------------------------------------------------------------------
# Path element types (output side)
# ---------------------------------------------------------------------------


class _Literal:
    """A literal string segment (possibly formed by joining sub-parts)."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


class _Amp:
    """Back-reference ``&N`` or ``&(N,M)``."""

    __slots__ = ("levels", "capture")

    def __init__(self, levels: int, capture: int) -> None:
        self.levels = levels
        self.capture = capture


class _At:
    """Value reference ``@(N,a.b.c)``."""

    __slots__ = ("levels", "path")

    def __init__(self, levels: int, path: tuple[str, ...]) -> None:
        self.levels = levels
        self.path = path


class _HashLiteral:
    """Literal string constant ``#value`` used as an output key name."""

    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


class _ArrayAppend:
    """Marker: append to an array rather than overwrite."""

    __slots__ = ()


# A single "segment" in an output path is a list of parts that get
# concatenated to form one key string (e.g. ``"prefix_&0"``).
# _ArrayAppend is special — it signals array-append mode for that segment.
_Part = _Literal | _Amp | _At | _HashLiteral | _ArrayAppend
_Segment = list[_Part]

# ---------------------------------------------------------------------------
# Compiled regex helpers
# ---------------------------------------------------------------------------

_RE_AMP_NM = re.compile(r"&\((\d+),(\d+)\)")
_RE_AMP_N = re.compile(r"&(\d+)")
_RE_AMP_BARE = re.compile(r"&(?!\()")  # & not followed by (
_RE_AT_NP = re.compile(r"@\((\d+),([\w.]+)\)")
_RE_HASH = re.compile(r"^#(.*)$")

# Tokeniser: splits on any reference token
_RE_TOKENS = re.compile(
    r"(&\(\d+,\d+\)"  # &(N,M)
    r"|&\d+"          # &N
    r"|&"             # bare &
    r"|@\(\d+,[\w.]+\)"  # @(N,path)
    r"|#[^.]*"        # #literal
    r")"
)


# ---------------------------------------------------------------------------
# Output path parsing
# ---------------------------------------------------------------------------


def _parse_part(tok: str) -> _Part:
    """Convert a single token string to a *_Part* instance."""
    m = _RE_AMP_NM.fullmatch(tok)
    if m:
        return _Amp(int(m.group(1)), int(m.group(2)))
    m = _RE_AMP_N.fullmatch(tok)
    if m:
        return _Amp(int(m.group(1)), 0)
    if _RE_AMP_BARE.fullmatch(tok):
        return _Amp(0, 0)
    m = _RE_AT_NP.fullmatch(tok)
    if m:
        return _At(int(m.group(1)), tuple(m.group(2).split(".")))
    m = _RE_HASH.fullmatch(tok)
    if m:
        return _HashLiteral(m.group(1))
    return _Literal(tok)


def _parse_segment(raw: str) -> _Segment:
    """Parse one dot-separated segment into a list of *_Part* objects."""
    # Handle bare array-append "[]"
    append = raw.endswith("[]")
    if append:
        raw = raw[:-2]

    if not raw and append:
        return [_ArrayAppend()]

    # Split on reference tokens
    parts: _Segment = []
    pieces = _RE_TOKENS.split(raw)
    for piece in pieces:
        if not piece:
            continue
        parts.append(_parse_part(piece))

    if append:
        parts.append(_ArrayAppend())
    return parts


def _split_dots(path: str) -> list[str]:
    """Split *path* on ``.`` but respect parentheses."""
    segments: list[str] = []
    depth = 0
    buf: list[str] = []
    for ch in path:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "." and depth == 0:
            segments.append("".join(buf))
            buf = []
        else:
            buf.append(ch)
    if buf:
        segments.append("".join(buf))
    return segments


def _parse_output_path(raw: str) -> list[_Segment]:
    """Parse a full dot-separated output path string."""
    return [_parse_segment(seg) for seg in _split_dots(raw)]


# ---------------------------------------------------------------------------
# Match context (built up as we recurse through the spec)
# ---------------------------------------------------------------------------


class _Ctx:
    """One level of match context."""

    __slots__ = ("key", "groups", "input_val")

    def __init__(self, key: str, groups: tuple[str, ...], input_val: Any) -> None:
        # key      — the matched input key (or str(index) for lists)
        # groups   — (whole_match, capture1, capture2, …)
        # input_val— the input VALUE at this matched key
        self.key = key
        self.groups = groups
        self.input_val = input_val


# ---------------------------------------------------------------------------
# Spec tree
# ---------------------------------------------------------------------------


class _SpecLeaf:
    """Leaf spec node: list of resolved output paths."""

    __slots__ = ("paths",)

    def __init__(self, paths: list[list[_Segment]]) -> None:
        self.paths = paths


class _SpecNode:
    """Internal spec node with child matchers."""

    __slots__ = ("literals", "wildcards", "at_self")

    def __init__(self) -> None:
        # Exact-key children
        self.literals: dict[str, _SpecLeaf | _SpecNode] = {}
        # Wildcard children: (compiled_regex, raw_pattern, child)
        self.wildcards: list[tuple[re.Pattern[str], str, _SpecLeaf | _SpecNode]] = []
        # '@' self-reference child
        self.at_self: _SpecLeaf | _SpecNode | None = None


def _wildcard_to_regex(key: str) -> re.Pattern[str]:
    """Turn a wildcard spec key (with ``*``) into a compiled regex."""
    parts = key.split("*")
    pattern = "(.*)".join(re.escape(p) for p in parts)
    return re.compile(f"^{pattern}$")


def _build_spec(raw: Any) -> _SpecLeaf | _SpecNode:
    """Recursively compile a raw spec dict/string/list into a spec tree."""
    if raw is None:
        return _SpecLeaf([[]])

    if isinstance(raw, str):
        return _SpecLeaf([_parse_output_path(raw)])

    if isinstance(raw, list):
        paths = [_parse_output_path(item) for item in raw if isinstance(item, str)]
        return _SpecLeaf(paths)

    if isinstance(raw, dict):
        node = _SpecNode()
        for key, val in raw.items():
            child = _build_spec(val)
            if key == "@":
                node.at_self = child
            else:
                # Expand OR patterns (``"a|b"``) into separate entries
                alternatives = [k.strip() for k in key.split("|")]
                for alt in alternatives:
                    if "*" in alt:
                        node.wildcards.append((_wildcard_to_regex(alt), alt, child))
                    else:
                        node.literals[alt] = child
        return node

    raise SpecError(f"Invalid shift spec value type {type(raw).__name__!r}: {raw!r}")


# ---------------------------------------------------------------------------
# Path resolution
# ---------------------------------------------------------------------------


def _resolve_amp(amp: _Amp, ctx: list[_Ctx]) -> str:
    idx = -(amp.levels + 1)
    if abs(idx) > len(ctx):
        raise TransformError(
            f"&{amp.levels} references level {amp.levels} but context depth is {len(ctx)}"
        )
    entry = ctx[idx]
    if amp.capture == 0:
        return entry.key
    if amp.capture < len(entry.groups):
        return entry.groups[amp.capture]
    raise TransformError(
        f"&({amp.levels},{amp.capture}): capture group {amp.capture} not available "
        f"(key={entry.key!r}, groups={entry.groups})"
    )


def _resolve_at(at: _At, ctx: list[_Ctx], current_val: Any) -> Any:
    """Resolve @(N,path): navigate N levels up in the match context, then follow path.

    Level semantics mirror &N:
    - @(0,path) → value stored at the current match (ctx[-1].input_val)
    - @(1,path) → value stored at the parent match (ctx[-2].input_val)
    - @(N,path) → value stored N+1 entries from the end of ctx
    """
    idx = -(at.levels + 1)
    if abs(idx) > len(ctx):
        if not ctx:
            return None
        # Fall back to current value if out of range
        val = current_val
    else:
        val = ctx[idx].input_val
    for part in at.path:
        if isinstance(val, dict):
            val = val.get(part)
        elif isinstance(val, list):
            try:
                val = val[int(part)]
            except (ValueError, IndexError):
                val = None
        else:
            val = None
        if val is None:
            break
    return val


def _resolve_path(
    segments: list[_Segment],
    ctx: list[_Ctx],
    current_val: Any,
) -> tuple[list[str], bool]:
    """Resolve a list of segments to concrete string keys + append flag."""
    keys: list[str] = []
    append = False

    for seg in segments:
        parts: list[str] = []
        seg_append = False
        for part in seg:
            if isinstance(part, _Literal):
                parts.append(part.value)
            elif isinstance(part, _Amp):
                parts.append(_resolve_amp(part, ctx))
            elif isinstance(part, _At):
                val = _resolve_at(part, ctx, current_val)
                parts.append("" if val is None else str(val))
            elif isinstance(part, _HashLiteral):
                parts.append(part.value)
            elif isinstance(part, _ArrayAppend):
                seg_append = True
        if parts:
            keys.append("".join(parts))
        if seg_append:
            append = True

    return keys, append


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def _write(output: dict[str, Any], keys: list[str], value: Any, append: bool) -> None:
    """Write *value* into *output* following *keys*, creating intermediate dicts."""
    if not keys:
        return

    node: Any = output
    for key in keys[:-1]:
        if isinstance(node, dict):
            existing = node.get(key)
            if not isinstance(existing, dict):
                node[key] = {}
            node = node[key]
        elif isinstance(node, list):
            try:
                idx = int(key)
            except ValueError:
                return
            while len(node) <= idx:
                node.append(None)
            if not isinstance(node[idx], dict):
                node[idx] = {}
            node = node[idx]
        else:
            return  # cannot descend into a scalar

    last = keys[-1]
    if isinstance(node, dict):
        if append:
            existing = node.get(last)
            if existing is None:
                node[last] = [value]
            elif isinstance(existing, list):
                existing.append(value)
            else:
                node[last] = [existing, value]
        else:
            existing = node.get(last)
            if existing is not None and existing is not node.get(last, _SENTINEL):
                # Key already set — collect into list (JOLT default behaviour)
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    node[last] = [existing, value]
            else:
                node[last] = value


_SENTINEL = object()


# ---------------------------------------------------------------------------
# Recursive shift application
# ---------------------------------------------------------------------------


def _apply(
    input_val: Any,
    spec: _SpecLeaf | _SpecNode,
    ctx: list[_Ctx],
    output: dict[str, Any],
) -> None:
    if isinstance(spec, _SpecLeaf):
        for path_segments in spec.paths:
            keys, append = _resolve_path(path_segments, ctx, input_val)
            if keys:
                _write(output, keys, input_val, append)
        return

    # _SpecNode — handle self-reference first
    if spec.at_self is not None:
        _apply(input_val, spec.at_self, ctx, output)

    if isinstance(input_val, dict):
        _apply_dict(input_val, spec, ctx, output)
    elif isinstance(input_val, list):
        _apply_list(input_val, spec, ctx, output)
    # Scalar with non-leaf spec: nothing to descend into


def _apply_dict(
    d: dict[str, Any],
    spec: _SpecNode,
    ctx: list[_Ctx],
    output: dict[str, Any],
) -> None:
    for key, val in d.items():
        if key in spec.literals:
            # Literal match is exclusive — wildcards do not fire for this key
            child = spec.literals[key]
            new_ctx = ctx + [_Ctx(key, (key,), val)]
            _apply(val, child, new_ctx, output)
        else:
            for pattern, _raw, child in spec.wildcards:
                m = pattern.match(key)
                if m:
                    groups = (key,) + m.groups()
                    new_ctx = ctx + [_Ctx(key, groups, val)]
                    _apply(val, child, new_ctx, output)


def _apply_list(
    lst: list[Any],
    spec: _SpecNode,
    ctx: list[_Ctx],
    output: dict[str, Any],
) -> None:
    for i, val in enumerate(lst):
        str_i = str(i)

        if str_i in spec.literals:
            child = spec.literals[str_i]
            new_ctx = ctx + [_Ctx(str_i, (str_i,), val)]
            _apply(val, child, new_ctx, output)

        for pattern, _raw, child in spec.wildcards:
            m = pattern.match(str_i)
            if m:
                groups = (str_i,) + m.groups()
                new_ctx = ctx + [_Ctx(str_i, groups, val)]
                _apply(val, child, new_ctx, output)


# ---------------------------------------------------------------------------
# Public Transform class
# ---------------------------------------------------------------------------


class Shift(Transform):
    """Re-map JSON fields from input paths to output paths.

    Parameters
    ----------
    spec:
        A nested dict following the JOLT shift spec format.

    Examples
    --------
    >>> s = Shift({"rating": {"primary": {"value": "Rating"}}})
    >>> s.apply({"rating": {"primary": {"value": 4.5}}})
    {'Rating': 4.5}

    Wildcard with back-reference::

        s = Shift({"*": {"value": "out.&1.val"}})
        s.apply({"foo": {"value": 1}, "bar": {"value": 2}})
        # -> {"out": {"foo": {"val": 1}, "bar": {"val": 2}}}
    """

    __slots__ = ("_root",)

    def __init__(self, spec: dict[str, Any]) -> None:
        self._root: _SpecLeaf | _SpecNode = _build_spec(spec)

    def apply(self, input_data: Any) -> Any:
        output: dict[str, Any] = {}
        _apply(input_data, self._root, [], output)
        return output
