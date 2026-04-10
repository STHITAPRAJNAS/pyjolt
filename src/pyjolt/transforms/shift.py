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

    __slots__ = ("literals", "wildcards", "at_self", "dollar_refs", "hash_consts")

    def __init__(self) -> None:
        # Exact-key children
        self.literals: dict[str, _SpecLeaf | _SpecNode] = {}
        # Wildcard children: (compiled_regex, raw_pattern, child)
        self.wildcards: list[tuple[re.Pattern[str], str, _SpecLeaf | _SpecNode]] = []
        # '@' self-reference child
        self.at_self: _SpecLeaf | _SpecNode | None = None
        # '$N' — write the key name at level N as the value
        # Each entry: (level: int, child)
        self.dollar_refs: list[tuple[int, _SpecLeaf | _SpecNode]] = []
        # '#constant' — write a literal constant string as the value
        # Each entry: (constant: str, child)
        self.hash_consts: list[tuple[str, _SpecLeaf | _SpecNode]] = []


_RE_DOLLAR = re.compile(r"^\$(\d*)$")  # $, $0, $1, …
_RE_HASH_CONST = re.compile(r"^#(.+)$")  # #literal (non-empty)


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

            # '@' — self-reference: use the current input value
            if key == "@":
                node.at_self = child
                continue

            # '$' / '$N' — write the key name at context level N as the value
            m = _RE_DOLLAR.match(key)
            if m:
                level = int(m.group(1)) if m.group(1) else 0
                node.dollar_refs.append((level, child))
                continue

            # '#constant' — write a literal constant string as the value
            m = _RE_HASH_CONST.match(key)
            if m:
                node.hash_consts.append((m.group(1), child))
                continue

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
) -> tuple[list[str], list[str], bool]:
    """Resolve path segments into (pre_array_keys, post_array_keys, append).

    When ``[]`` appears in the **middle** of a path (e.g. ``items[].sku``):
    - ``pre_array_keys`` holds the path up to the array key: ``["items"]``
    - ``post_array_keys`` holds the remainder:              ``["sku"]``
    - ``append`` is ``True``

    When ``[]`` appears at the **end** (e.g. ``values[]``):
    - ``pre_array_keys`` = ``["values"]``, ``post_array_keys`` = ``[]``
    - ``append`` = ``True``

    When there is no ``[]``:
    - ``pre_array_keys`` = full path, ``post_array_keys`` = ``[]``
    - ``append`` = ``False``
    """
    all_keys: list[str] = []
    slot_after: int | None = None  # index in all_keys AFTER which [] appeared

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
            all_keys.append("".join(parts))
        if seg_append and slot_after is None:
            # Record the position where [] appeared
            slot_after = len(all_keys)

    if slot_after is None:
        return all_keys, [], False

    pre = all_keys[:slot_after]
    post = all_keys[slot_after:]
    return pre, post, True


# ---------------------------------------------------------------------------
# Output writing
# ---------------------------------------------------------------------------


def _write(
    output: dict[str, Any],
    pre_keys: list[str],
    post_keys: list[str],
    value: Any,
    append: bool,
    slot_registry: dict[tuple[int, tuple[str, ...]], dict[str, Any]],
    ctx: list[_Ctx],
) -> None:
    """Write *value* into *output*.

    Parameters
    ----------
    pre_keys:
        Path segments before any ``[]`` marker.
    post_keys:
        Path segments after the ``[]`` marker (empty when ``[]`` is at end
        or when there is no ``[]``).
    value:
        Value to write.
    append:
        ``True`` when ``[]`` was present in the path.
    slot_registry:
        Shared dict mapping ``(id(array_list), iteration_key_tuple)`` to the
        dict slot already created for the current wildcard iteration.  Ensures
        multiple fields from the same iteration land in the same list element.
    ctx:
        Current match context — used to derive the iteration identity key.
    """
    if not pre_keys and not post_keys:
        return

    if not append:
        # ── Plain write (no array involved) ──────────────────────────────
        node: Any = output
        for key in pre_keys[:-1]:
            if isinstance(node, dict):
                if not isinstance(node.get(key), dict):
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
                return
        last = pre_keys[-1]
        if isinstance(node, dict):
            existing = node.get(last)
            if existing is not None:
                if isinstance(existing, list):
                    existing.append(value)
                else:
                    node[last] = [existing, value]
            else:
                node[last] = value
        return

    # ── Array write ([] present) ──────────────────────────────────────────
    # Navigate to the node that holds the array
    node = output
    for key in pre_keys[:-1]:
        if isinstance(node, dict):
            if not isinstance(node.get(key), (dict, list)):
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
            return

    array_key = pre_keys[-1] if pre_keys else None

    if array_key is None:
        return

    if isinstance(node, dict):
        if not isinstance(node.get(array_key), list):
            node[array_key] = []
        arr = node[array_key]
    else:
        return

    if not post_keys:
        # [] at end — simple append of the value
        arr.append(value)
        return

    # [] in the middle — need a shared dict slot for the current iteration.
    # Use ctx[:-1] so that different leaf fields from the same wildcard iteration
    # (e.g. "sku", "qty", "price" from items[0]) all map to the same slot.
    iter_key: tuple[str, ...] = tuple(c.key for c in ctx[:-1])
    reg_key = (id(arr), iter_key)

    if reg_key not in slot_registry:
        slot: dict[str, Any] = {}
        arr.append(slot)
        slot_registry[reg_key] = slot

    slot = slot_registry[reg_key]

    # Write into the slot using post_keys
    inner: Any = slot
    for key in post_keys[:-1]:
        if not isinstance(inner.get(key), dict):
            inner[key] = {}
        inner = inner[key]
    inner_last = post_keys[-1]
    existing_inner = inner.get(inner_last)
    if existing_inner is not None:
        if isinstance(existing_inner, list):
            existing_inner.append(value)
        else:
            inner[inner_last] = [existing_inner, value]
    else:
        inner[inner_last] = value


_SENTINEL = object()


# ---------------------------------------------------------------------------
# Recursive shift application
# ---------------------------------------------------------------------------


def _apply(
    input_val: Any,
    spec: _SpecLeaf | _SpecNode,
    ctx: list[_Ctx],
    output: dict[str, Any],
    slot_registry: dict[tuple[int, tuple[str, ...]], dict[str, Any]],
) -> None:
    if isinstance(spec, _SpecLeaf):
        for path_segments in spec.paths:
            pre, post, append = _resolve_path(path_segments, ctx, input_val)
            if pre:
                _write(output, pre, post, input_val, append, slot_registry, ctx)
        return

    # _SpecNode — handle self-reference first
    if spec.at_self is not None:
        _apply(input_val, spec.at_self, ctx, output, slot_registry)

    if isinstance(input_val, dict):
        _apply_dict(input_val, spec, ctx, output, slot_registry)
    elif isinstance(input_val, list):
        _apply_list(input_val, spec, ctx, output, slot_registry)
    # Scalar with non-leaf spec: nothing to descend into

    # '$N' — emit the key name at context level N as the written value.
    # Push a dummy ctx entry so that &N back-references and the slot_registry
    # iter_key depth align with sibling regular field moves.
    for level, child in spec.dollar_refs:
        idx = -(level + 1)
        key_val = ctx[idx].key if abs(idx) <= len(ctx) else ""
        dummy_ctx = ctx + [_Ctx("$", (key_val,), key_val)]
        _apply(key_val, child, dummy_ctx, output, slot_registry)

    # '#constant' — emit a literal constant string as the written value.
    # Same dummy-ctx trick for consistent slot_registry / &N alignment.
    for const_val, child in spec.hash_consts:
        dummy_ctx = ctx + [_Ctx(f"#{const_val}", (const_val,), const_val)]
        _apply(const_val, child, dummy_ctx, output, slot_registry)


def _apply_dict(
    d: dict[str, Any],
    spec: _SpecNode,
    ctx: list[_Ctx],
    output: dict[str, Any],
    slot_registry: dict[tuple[int, tuple[str, ...]], dict[str, Any]],
) -> None:
    for key, val in d.items():
        if key in spec.literals:
            # Literal match is exclusive — wildcards do not fire for this key
            child = spec.literals[key]
            new_ctx = ctx + [_Ctx(key, (key,), val)]
            _apply(val, child, new_ctx, output, slot_registry)
        else:
            for pattern, _raw, child in spec.wildcards:
                m = pattern.match(key)
                if m:
                    groups = (key,) + m.groups()
                    new_ctx = ctx + [_Ctx(key, groups, val)]
                    _apply(val, child, new_ctx, output, slot_registry)


def _apply_list(
    lst: list[Any],
    spec: _SpecNode,
    ctx: list[_Ctx],
    output: dict[str, Any],
    slot_registry: dict[tuple[int, tuple[str, ...]], dict[str, Any]],
) -> None:
    for i, val in enumerate(lst):
        str_i = str(i)

        if str_i in spec.literals:
            child = spec.literals[str_i]
            new_ctx = ctx + [_Ctx(str_i, (str_i,), val)]
            _apply(val, child, new_ctx, output, slot_registry)

        for pattern, _raw, child in spec.wildcards:
            m = pattern.match(str_i)
            if m:
                groups = (str_i,) + m.groups()
                new_ctx = ctx + [_Ctx(str_i, groups, val)]
                _apply(val, child, new_ctx, output, slot_registry)


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
        slot_registry: dict[tuple[int, tuple[str, ...]], dict[str, Any]] = {}
        _apply(input_data, self._root, [], output, slot_registry)
        return output
