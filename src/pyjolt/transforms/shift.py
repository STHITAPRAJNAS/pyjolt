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

"""Shift transform — re-maps fields from one JSON path to another."""

from __future__ import annotations

import re
from typing import Any

from ..exceptions import SpecError, TransformError
from .base import Transform

# ---------------------------------------------------------------------------
# Path elements
# ---------------------------------------------------------------------------


class _Literal:
    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


class _Amp:
    __slots__ = ("levels", "capture")

    def __init__(self, levels: int, capture: int) -> None:
        self.levels, self.capture = levels, capture


class _At:
    __slots__ = ("levels", "path")

    def __init__(self, levels: int, path: tuple[str, ...]) -> None:
        self.levels, self.path = levels, path


class _HashLiteral:
    __slots__ = ("value",)

    def __init__(self, value: str) -> None:
        self.value = value


class _ArrayAppend:
    __slots__ = ()


class _ArrayIndex:
    __slots__ = ("parts",)

    def __init__(self, parts: list[_Literal | _Amp | _At | _HashLiteral]) -> None:
        self.parts = parts


_Part = _Literal | _Amp | _At | _HashLiteral | _ArrayAppend | _ArrayIndex
_Segment = list[_Part]

# ---------------------------------------------------------------------------
# Regex
# ---------------------------------------------------------------------------

_RE_AMP_NM = re.compile(r"&\((\d+),(\d+)\)")
_RE_AMP_N = re.compile(r"&(\d+)")
_RE_AMP_BARE = re.compile(r"&(?!\()")
_RE_AT_NP = re.compile(r"@\((\d+),([\w.]+)\)")
_RE_HASH = re.compile(r"^#(.*)$")
_RE_TOKENS = re.compile(r"(&\(\d+,\d+\)|&\d+|&|@\(\d+,[\w.]+\)|#[^.]*)")
_RE_INDEX = re.compile(r"^(.*)\[([^\[\]]+)\]$")

# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------


def _parse_part(tok: str) -> _Part:
    if m := _RE_AMP_NM.fullmatch(tok):
        return _Amp(int(m.group(1)), int(m.group(2)))
    if m := _RE_AMP_N.fullmatch(tok):
        return _Amp(int(m.group(1)), 0)
    if _RE_AMP_BARE.fullmatch(tok):
        return _Amp(0, 0)
    if m := _RE_AT_NP.fullmatch(tok):
        return _At(int(m.group(1)), tuple(m.group(2).split(".")))
    if m := _RE_HASH.fullmatch(tok):
        return _HashLiteral(m.group(1))
    return _Literal(tok)


def _parse_tokens(raw: str) -> list[_Part]:
    return [_parse_part(p) for p in _RE_TOKENS.split(raw) if p]


def _parse_segment(raw: str) -> _Segment:
    append = raw.endswith("[]")
    if append:
        raw = raw[:-2]
    if not raw and append:
        return [_ArrayAppend()]
    # Explicit array indices, e.g. "items[&2]", "[&1]", "list[0]" or "grid[&1][&0]"
    indices: list[_Part] = []
    while not append and (m := _RE_INDEX.match(raw)):
        idx_parts: Any = _parse_tokens(m.group(2))
        indices.insert(0, _ArrayIndex(idx_parts))
        raw = m.group(1)
    parts = _parse_tokens(raw) + indices
    if append:
        parts.append(_ArrayAppend())
    return parts


def _split_dots(path: str) -> list[str]:
    segments = []
    depth, buf = 0, []
    for ch in path:
        if ch == "(":
            depth += 1
            buf.append(ch)
        elif ch == ")":
            depth -= 1
            buf.append(ch)
        elif ch == "." and depth == 0:
            if buf:
                segments.append("".join(buf))
                buf = []
        else:
            buf.append(ch)
    if buf:
        segments.append("".join(buf))
    return segments


def _parse_output_path(raw: str) -> list[_Segment]:
    return [_parse_segment(seg) for seg in _split_dots(raw)]


# ---------------------------------------------------------------------------
# Context & Spec
# ---------------------------------------------------------------------------


class _Ctx:
    __slots__ = ("key", "groups", "input_val")

    def __init__(self, key: str, groups: tuple[str, ...], input_val: Any) -> None:
        self.key, self.groups, self.input_val = key, groups, input_val


class _SpecLeaf:
    __slots__ = ("paths",)

    def __init__(self, paths: list[list[_Segment]]) -> None:
        self.paths = paths


class _SpecNode:
    __slots__ = ("literals", "wildcards", "at_self", "dollar_refs", "hash_consts")

    def __init__(self) -> None:
        self.literals: dict[str, _SpecLeaf | _SpecNode] = {}
        self.wildcards: list[tuple[re.Pattern[str], str, _SpecLeaf | _SpecNode]] = []
        self.at_self: _SpecLeaf | _SpecNode | None = None
        self.dollar_refs: list[tuple[int, _SpecLeaf | _SpecNode]] = []
        self.hash_consts: list[tuple[str, _SpecLeaf | _SpecNode]] = []


def _build_spec(raw: Any) -> _SpecLeaf | _SpecNode:
    if raw is None:
        return _SpecLeaf([[]])
    if isinstance(raw, str):
        return _SpecLeaf([_parse_output_path(raw)])
    if isinstance(raw, list):
        return _SpecLeaf([_parse_output_path(i) for i in raw if isinstance(i, str)])
    if isinstance(raw, dict):
        node = _SpecNode()
        for k, v in raw.items():
            child = _build_spec(v)
            if k == "@":
                node.at_self = child
            elif m := re.match(r"^\$(\d*)$", k):
                node.dollar_refs.append((int(m.group(1)) if m.group(1) else 0, child))
            elif m := re.match(r"^#(.+)$", k):
                node.hash_consts.append((m.group(1), child))
            else:
                for alt in [s.strip() for s in k.split("|")]:
                    if "*" in alt:
                        parts = alt.split("*")
                        p = "(.*)".join(re.escape(s) for s in parts)
                        node.wildcards.append((re.compile(f"^{p}$"), alt, child))
                    else:
                        node.literals[alt] = child
        return node
    raise SpecError(f"Invalid spec type {type(raw).__name__}")


# ---------------------------------------------------------------------------
# Resolution & Writing
# ---------------------------------------------------------------------------


def _resolve_amp(amp: _Amp, ctx: list[_Ctx]) -> str:
    idx = -(amp.levels + 1)
    if abs(idx) > len(ctx):
        raise TransformError(f"&{amp.levels} out of range")
    e = ctx[idx]
    if amp.capture == 0:
        return e.key
    if amp.capture < len(e.groups):
        return e.groups[amp.capture]
    raise TransformError(f"&({amp.levels},{amp.capture}) capture group not available")


def _resolve_at(at: _At, ctx: list[_Ctx], val: Any) -> Any:
    idx = -(at.levels + 1)
    v = val if abs(idx) > len(ctx) else ctx[idx].input_val
    for p in at.path:
        if isinstance(v, dict):
            v = v.get(p)
        elif isinstance(v, list):
            try:
                v = v[int(p)]
            except Exception:
                v = None
        else:
            v = None
        if v is None:
            break
    return v


def _resolve_part(p: _Part, ctx: list[_Ctx], val: Any) -> str:
    if isinstance(p, (_Literal, _HashLiteral)):
        return p.value
    if isinstance(p, _Amp):
        return _resolve_amp(p, ctx)
    if isinstance(p, _At):
        v = _resolve_at(p, ctx, val)
        return "" if v is None else str(v)
    return ""


_Key = str | int


def _resolve_path(
    segments: list[_Segment], ctx: list[_Ctx], val: Any
) -> tuple[list[_Key], list[_Key], bool] | None:
    keys: list[_Key] = []
    slot_after = None
    for seg in segments:
        parts, is_array, indices = [], False, []
        for p in seg:
            if isinstance(p, _ArrayAppend):
                is_array = True
            elif isinstance(p, _ArrayIndex):
                raw_idx = "".join(_resolve_part(ip, ctx, val) for ip in p.parts)
                if not raw_idx.isdigit():
                    return None
                indices.append(int(raw_idx))
            else:
                parts.append(_resolve_part(p, ctx, val))
        k = "".join(parts)
        if k or not (is_array or indices):
            keys.append(k)
        keys.extend(indices)
        if is_array and slot_after is None:
            slot_after = len(keys)
    if slot_after is None:
        return keys, [], False
    return keys[:slot_after], keys[slot_after:], True


def _get(node: Any, k: _Key) -> Any:
    if isinstance(k, int):
        return node[k] if k < len(node) else None
    return node.get(k)


def _set(node: Any, k: _Key, v: Any) -> None:
    if isinstance(k, int):
        while len(node) <= k:
            node.append(None)
    node[k] = v


def _descend(node: Any, k: _Key, want_list: bool) -> Any:
    child = _get(node, k)
    if not isinstance(child, list if want_list else dict):
        child = [] if want_list else {}
        _set(node, k, child)
    return child


def _place(node: Any, k: _Key, val: Any) -> None:
    cur = _get(node, k)
    if cur is None and (isinstance(k, int) or k not in node):
        _set(node, k, val)
    elif isinstance(cur, list):
        cur.append(val)
    else:
        _set(node, k, [cur, val])


def _write(
    out: dict[str, Any],
    pre: list[_Key],
    post: list[_Key],
    val: Any,
    append: bool,
    slots: dict[tuple[int, tuple[str, ...]], Any],
    ctx: list[_Ctx],
) -> None:
    if isinstance(pre[0], int):
        return  # the root output is always an object
    node: Any = out
    for i, k in enumerate(pre[:-1]):
        node = _descend(node, k, isinstance(pre[i + 1], int))

    ak = pre[-1]
    if not append:
        _place(node, ak, val)
        return

    arr = _descend(node, ak, True)
    if not post:
        arr.append(val)
        return

    rk = (id(arr), tuple(c.key for c in ctx[:-1]))
    if rk not in slots:
        slot: Any = [] if isinstance(post[0], int) else {}
        arr.append(slot)
        slots[rk] = slot
    inner = slots[rk]
    for i, k in enumerate(post[:-1]):
        inner = _descend(inner, k, isinstance(post[i + 1], int))
    _place(inner, post[-1], val)


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------


def _apply(
    val: Any,
    spec: _SpecLeaf | _SpecNode,
    ctx: list[_Ctx],
    out: dict[str, Any],
    slots: dict[tuple[int, tuple[str, ...]], Any],
) -> None:
    if isinstance(spec, _SpecLeaf):
        for path_list in spec.paths:
            resolved = _resolve_path(path_list, ctx, val)
            if resolved is None:
                continue
            pre, post, append = resolved
            if pre:
                _write(out, pre, post, val, append, slots, ctx)
        return
    if spec.at_self:
        _apply(val, spec.at_self, ctx, out, slots)
    if isinstance(val, dict):
        for k, v in val.items():
            sk = str(k)
            if sk in spec.literals:
                _apply(v, spec.literals[sk], ctx + [_Ctx(sk, (sk,), v)], out, slots)
            else:
                for pattern, _, child in spec.wildcards:
                    if m := pattern.match(sk):
                        _apply(v, child, ctx + [_Ctx(sk, (sk,) + m.groups(), v)], out, slots)
    elif isinstance(val, list):
        for i, v in enumerate(val):
            si = str(i)
            if si in spec.literals:
                _apply(v, spec.literals[si], ctx + [_Ctx(si, (si,), v)], out, slots)
            for pattern, _, child in spec.wildcards:
                if m := pattern.match(si):
                    _apply(v, child, ctx + [_Ctx(si, (si,) + m.groups(), v)], out, slots)
    else:
        sv = str(val)
        if sv in spec.literals:
            _apply(val, spec.literals[sv], ctx + [_Ctx(sv, (sv,), val)], out, slots)
        else:
            for pattern, _, child in spec.wildcards:
                if m := pattern.match(sv):
                    _apply(val, child, ctx + [_Ctx(sv, (sv,) + m.groups(), val)], out, slots)
    for level, child_spec in spec.dollar_refs:
        kv = ctx[-(level + 1)].key if abs(-(level + 1)) <= len(ctx) else ""
        _apply(kv, child_spec, ctx + [_Ctx("$", (kv,), kv)], out, slots)
    for v_const, c_spec in spec.hash_consts:
        _apply(v_const, c_spec, ctx + [_Ctx(f"#{v_const}", (v_const,), v_const)], out, slots)


class Shift(Transform):
    __slots__ = ("_root",)

    def __init__(self, spec: dict[str, Any]) -> None:
        self._root = _build_spec(spec)

    def apply(self, data: Any) -> Any:
        out: dict[str, Any] = {}
        _apply(data, self._root, [], out, {})
        return out
