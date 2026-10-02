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

"""Spec path parsing, matching, evaluation and tree traversal.

Ports ``com.bazaarvoice.jolt.common`` (path elements, references, walked path,
spec string parsing) and ``com.bazaarvoice.jolt.traversr``.
"""

from __future__ import annotations

import re
from typing import Any

from ..exceptions import SpecError, TransformError
from .util import (
    MISSING,
    ROOT_KEY,
    count_matches,
    is_blank,
    is_digit,
    parse_int,
    try_parse_int,
)

# ---------------------------------------------------------------------------
# Walked path
# ---------------------------------------------------------------------------


class MatchedElement:
    """The data key a spec key matched, plus any ``*`` captures (index 0 is the whole key)."""

    __slots__ = ("raw_key", "sub_keys", "hash_count")

    def __init__(self, key: str, sub_keys: list[str] | None = None) -> None:
        self.raw_key: str = key
        self.sub_keys: list[str] = [key, *(sub_keys or ())]
        self.hash_count = 0

    @property
    def canonical_form(self) -> str:
        return self.raw_key

    def evaluate(self, walked_path: WalkedPath) -> str:
        return self.raw_key

    def get_sub_key_ref(self, index: int) -> str:
        if not 0 <= index < len(self.sub_keys):
            raise TransformError(
                f"MatchedElement {self.sub_keys} cannot be indexed with index {index}"
            )
        return self.sub_keys[index]

    def increment_hash_count(self) -> None:
        self.hash_count += 1


class ArrayMatchedElement(MatchedElement):
    __slots__ = ("orig_size",)

    def __init__(self, key: str, orig_size: int) -> None:
        super().__init__(key)
        self.orig_size = orig_size

    @property
    def raw_index(self) -> int:
        return parse_int(self.raw_key)


class PathStep:
    __slots__ = ("tree_ref", "matched_element", "orig_size")

    def __init__(self, tree_ref: Any, matched_element: MatchedElement) -> None:
        self.tree_ref = tree_ref
        self.matched_element = matched_element
        self.orig_size: int | None = (
            matched_element.orig_size if isinstance(matched_element, ArrayMatchedElement) else None
        )


class WalkedPath(list[PathStep]):
    """The stack of (input subtree, matched key) pairs from the root to the current spec node."""

    def add(self, tree_ref: Any, matched_element: MatchedElement) -> None:
        self.append(PathStep(tree_ref, matched_element))

    def remove_last(self) -> None:
        self.pop()

    def element_from_end(self, idx_from_end: int) -> PathStep | None:
        if not self:
            return None
        pos = len(self) - 1 - idx_from_end
        if pos < 0:
            raise TransformError(
                f"Reference goes {idx_from_end} levels up, but the path is only {len(self)} deep"
            )
        return self[pos]

    def last_element(self) -> PathStep:
        return self[-1]


def _step_from_end(walked_path: WalkedPath, idx: int) -> PathStep:
    step = walked_path.element_from_end(idx)
    if step is None:
        raise TransformError("Reference used on an empty path")
    return step


# ---------------------------------------------------------------------------
# References: &(path,group)  $(path,group)  #path
# ---------------------------------------------------------------------------


class PathAndGroupReference:
    __slots__ = ("path_index", "key_group")
    TOKEN = ""

    def __init__(self, ref_str: str) -> None:
        if not ref_str or ref_str[0] != self.TOKEN:
            raise SpecError(
                f"Invalid reference key={ref_str} either blank or doesn't start with "
                f"correct character={self.TOKEN}"
            )
        p_i = k_g = 0
        try:
            if len(ref_str) > 1:
                meat = ref_str[1:]
                if len(meat) >= 3 and meat.startswith("(") and meat.endswith(")"):
                    ints = meat[1:-1].split(",")
                    if len(ints) > 2:
                        raise SpecError(f"Invalid Reference={ref_str}")
                    p_i = parse_int(ints[0])
                    if len(ints) == 2:
                        k_g = parse_int(ints[1])
                else:
                    p_i = parse_int(meat)
        except ValueError:
            raise SpecError(f"Unable to parse '{self.TOKEN}' reference key:{ref_str}") from None
        if p_i < 0 or k_g < 0:
            raise SpecError(f"Reference:{ref_str} can not have a negative value.")
        self.path_index = p_i
        self.key_group = k_g

    @property
    def canonical_form(self) -> str:
        return f"{self.TOKEN}({self.path_index},{self.key_group})"


class AmpReference(PathAndGroupReference):
    __slots__ = ()
    TOKEN = "&"


class DollarReference(PathAndGroupReference):
    __slots__ = ()
    TOKEN = "$"


class HashReference:
    __slots__ = ("path_index",)
    TOKEN = "#"

    def __init__(self, ref_str: str) -> None:
        if not ref_str or ref_str[0] != self.TOKEN:
            raise SpecError(f"Invalid reference key={ref_str}")
        p_i = 0
        if len(ref_str) > 1:
            try:
                p_i = parse_int(ref_str[1:])
            except ValueError:
                raise SpecError(f"Unable to parse '#' reference key:{ref_str}") from None
        if p_i < 0:
            raise SpecError(f"Reference:{ref_str} can not have a negative value.")
        self.path_index = p_i

    @property
    def canonical_form(self) -> str:
        return f"#{self.path_index}"


# ---------------------------------------------------------------------------
# Path elements
# ---------------------------------------------------------------------------


class PathElement:
    """Base for one segment of a spec key (LHS) or output path (RHS)."""

    __slots__ = ("raw_key",)
    matchable = True
    evaluatable = False

    def __init__(self, key: str) -> None:
        self.raw_key = key

    @property
    def canonical_form(self) -> str:
        return self.raw_key

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        raise NotImplementedError

    def evaluate(self, walked_path: WalkedPath) -> str | None:
        raise NotImplementedError

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.canonical_form!r})"


class LiteralPathElement(PathElement):
    __slots__ = ("_canonical",)
    evaluatable = True

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self._canonical = key.replace(".", "\\.")

    @property
    def canonical_form(self) -> str:
        return self._canonical

    def evaluate(self, walked_path: WalkedPath) -> str:
        return self.raw_key

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        return MatchedElement(self.raw_key) if self.raw_key == data_key else None


class AtPathElement(PathElement):
    __slots__ = ()

    def __init__(self, key: str) -> None:
        super().__init__(key)
        if key != "@":
            raise SpecError(
                f"'References Input' key '@', can only be a single '@'.  Offending key : {key}"
            )

    @property
    def canonical_form(self) -> str:
        return "@"

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        return walked_path.last_element().matched_element


class StarPathElement(PathElement):
    __slots__ = ()

    def string_match(self, literal: str) -> bool:
        raise NotImplementedError


class StarAllPathElement(StarPathElement):
    __slots__ = ()

    def __init__(self, key: str) -> None:
        if key != "*":
            raise SpecError(f"StarAllPathElement key should just be a single '*'.  Was: {key}")
        super().__init__("*")

    def string_match(self, literal: str) -> bool:
        return True

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        orig_size = walked_path.last_element().orig_size
        if orig_size is not None:
            return ArrayMatchedElement(data_key, orig_size)
        return MatchedElement(data_key)


class StarSinglePathElement(StarPathElement):
    __slots__ = ("prefix", "suffix")

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.prefix, self.suffix = key.split("*")

    def string_match(self, literal: str) -> bool:
        return (
            literal.startswith(self.prefix)
            and literal.endswith(self.suffix)
            and len(literal) > len(self.prefix) + len(self.suffix)
        )

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        if not self.string_match(data_key):
            return None
        star = data_key[len(self.prefix) : len(data_key) - len(self.suffix)]
        return MatchedElement(data_key, [star])


class StarDoublePathElement(StarPathElement):
    __slots__ = ("prefix", "mid", "suffix")

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.prefix, self.mid, self.suffix = key.split("*")

    def _mid_index(self, literal: str) -> int:
        start = len(self.prefix) + 1
        end = len(literal) - len(self.suffix) - 1
        if start >= end:
            return -1
        idx = literal[start:end].find(self.mid)
        return idx + start if idx >= 0 else -1

    def string_match(self, literal: str) -> bool:
        return (
            literal.startswith(self.prefix)
            and literal.endswith(self.suffix)
            and self._mid_index(literal) > 0
        )

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        if not self.string_match(data_key):
            return None
        mid_start = self._mid_index(data_key)
        mid_end = mid_start + len(self.mid)
        first = data_key[len(self.prefix) : mid_start]
        second = data_key[mid_end : len(data_key) - len(self.suffix)]
        return MatchedElement(data_key, [first, second])


class StarRegexPathElement(StarPathElement):
    __slots__ = ("pattern",)

    def __init__(self, key: str) -> None:
        super().__init__(key)
        regex = "^" + "(.+?)".join(re.escape(p) for p in key.split("*")) + "$"
        self.pattern = re.compile(regex)

    def string_match(self, literal: str) -> bool:
        return self.pattern.search(literal) is not None

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        m = self.pattern.search(data_key)
        if m is None:
            return None
        return MatchedElement(data_key, list(m.groups()))


class AmpPathElement(PathElement):
    __slots__ = ("tokens", "_canonical")
    evaluatable = True

    def __init__(self, key: str) -> None:
        super().__init__(key)
        tokens: list[str | AmpReference] = []
        canonical: list[str] = []
        literal: list[str] = []
        i = 0
        while i < len(key):
            c = key[i]
            if c == "&":
                if literal:
                    tokens.append("".join(literal))
                    canonical.append("".join(literal))
                    literal = []
                ref_end = _find_end_of_reference(key[i + 1 :])
                ref = AmpReference(key[i : i + ref_end + 1])
                canonical.append(ref.canonical_form)
                tokens.append(ref)
                i += ref_end
            else:
                literal.append(c)
            i += 1
        if literal:
            tokens.append("".join(literal))
            canonical.append("".join(literal))
        self.tokens = tokens
        self._canonical = "".join(canonical)

    @property
    def canonical_form(self) -> str:
        return self._canonical

    def evaluate(self, walked_path: WalkedPath) -> str:
        out = []
        for token in self.tokens:
            if isinstance(token, str):
                out.append(token)
            else:
                matched = _step_from_end(walked_path, token.path_index).matched_element
                out.append(matched.get_sub_key_ref(token.key_group))
        return "".join(out)

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        evaled = self.evaluate(walked_path)
        return MatchedElement(evaled) if evaled == data_key else None


def _find_end_of_reference(key: str) -> int:
    for i, c in enumerate(key):
        if not is_digit(c) and c not in "(),":
            return i
    return len(key)


class DollarPathElement(PathElement):
    __slots__ = ("ref",)
    evaluatable = True

    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.ref = DollarReference(key)

    @property
    def canonical_form(self) -> str:
        return self.ref.canonical_form

    def evaluate(self, walked_path: WalkedPath) -> str:
        matched = _step_from_end(walked_path, self.ref.path_index).matched_element
        return matched.get_sub_key_ref(self.ref.key_group)

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        return MatchedElement(self.evaluate(walked_path))


class HashPathElement(PathElement):
    __slots__ = ("key_value",)

    def __init__(self, key: str) -> None:
        super().__init__(key)
        if is_blank(key):
            raise SpecError("HashPathElement cannot have empty String as input.")
        if not key.startswith("#"):
            raise SpecError(f"LHS # should start with a # : {key}")
        if len(key) <= 1:
            raise SpecError(f"HashPathElement input is too short : {key}")
        if key[1] == "(":
            if key[-1] != ")":
                raise SpecError(f"HashPathElement, mismatched parens : {key}")
            self.key_value = key[2:-1]
        else:
            self.key_value = key[1:]

    @property
    def canonical_form(self) -> str:
        return f"#({self.key_value})"

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        return MatchedElement(self.key_value)


class TransposePathElement(PathElement):
    """``@(n,path)``: look up a value in the input, ``n`` levels up from the current position."""

    __slots__ = ("up_level", "sub_path_reader", "_canonical")
    evaluatable = True

    def __init__(self, original_key: str, up_level: int, sub_path: str | None) -> None:
        super().__init__(original_key)
        self.up_level = up_level
        if not sub_path:
            self.sub_path_reader: PathEvaluatingTraversal | None = None
            self._canonical = f"@({up_level},)"
        else:
            self.sub_path_reader = PathEvaluatingTraversal(sub_path, writer=False)
            self._canonical = f"@({up_level},{self.sub_path_reader.canonical_form})"

    @classmethod
    def parse(cls, key: str) -> TransposePathElement:
        if key is None or len(key) < 2:
            raise SpecError(
                f"'Transpose Input' key '@', can not be null or of length 1.  Offending key : {key}"
            )
        if key[0] != "@":
            raise SpecError(f"'Transpose Input' key must start with an '@'.  Offending key : {key}")
        meat = key[1:]
        if "@" in meat:
            raise SpecError(f"@ pathElement can not contain a nested @. Was: {meat}")
        if "*" in meat or "[]" in meat:
            raise SpecError(
                "'Transpose Input' can not contain expansion wildcards (* and []).  "
                f"Offending key : {key}"
            )
        if meat.startswith("("):
            if not meat.endswith(")"):
                raise SpecError(
                    f"@ path element that starts with '(' must have a matching ')'.  "
                    f"Offending key : {key}"
                )
            meat = meat[1:-1]
        return cls._inner_parse(key, meat)

    @classmethod
    def _inner_parse(cls, original_key: str, meat: str) -> TransposePathElement:
        if meat and is_digit(meat[0]):
            digits = [meat[0]]
            for i in range(1, len(meat)):
                c = meat[i]
                if c == ",":
                    return cls(original_key, int("".join(digits)), meat[i + 1 :])
                if is_digit(c):
                    digits.append(c)
                else:
                    raise SpecError(
                        f"@ path element with non/mixed numeric key is not valid, key={original_key}"
                    )
            return cls(original_key, int("".join(digits)), None)
        return cls(original_key, 0, meat)

    @property
    def canonical_form(self) -> str:
        return self._canonical

    def object_evaluate(self, walked_path: WalkedPath) -> Any:
        """The referenced input value, or ``MISSING``."""
        step = walked_path.element_from_end(self.up_level)
        if step is None:
            return MISSING
        if self.sub_path_reader is None:
            return step.tree_ref
        return self.sub_path_reader.read(step.tree_ref, walked_path)

    def evaluate(self, walked_path: WalkedPath) -> str | None:
        data = self.object_evaluate(walked_path)
        if data is MISSING:
            return None
        if isinstance(data, bool):
            return "true" if data else "false"
        if isinstance(data, (int, float)):
            try:
                return str(int(data))
            except (OverflowError, ValueError):
                return None
        if isinstance(data, str):
            return data
        return None

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        return walked_path.last_element().matched_element


_AUTO_EXPAND, _REFERENCE, _HASH, _TRANSPOSE, _EXPLICIT_INDEX = range(5)


def _non_negative_int_str(key: str | None) -> str | None:
    if key is None:
        return None
    n = try_parse_int(key)
    return key if n is not None and n >= 0 else None


class ArrayPathElement(PathElement):
    """``[]``, ``[3]``, ``[&1]``, ``[#2]`` or ``[@(1,x)]``."""

    __slots__ = ("array_path_type", "ref", "transpose", "_canonical", "array_index")
    evaluatable = True

    def __init__(self, key: str) -> None:
        super().__init__(key)
        if not key or key[0] != "[" or key[-1] != "]":
            raise SpecError(f"Invalid ArrayPathElement key:{key}")
        self.ref: AmpReference | HashReference | None = None
        self.transpose: TransposePathElement | None = None
        self.array_index = ""
        if len(key) == 2:
            self.array_path_type = _AUTO_EXPAND
            self._canonical = "[]"
            return
        meat = key[1:-1]
        first = meat[0]
        if first == "&":
            self.ref = AmpReference(meat)
            self.array_path_type = _REFERENCE
            self._canonical = f"[{self.ref.canonical_form}]"
        elif first == "#":
            self.ref = HashReference(meat)
            self.array_path_type = _HASH
            self._canonical = f"[{self.ref.canonical_form}]"
        elif first == "@":
            self.transpose = TransposePathElement.parse(meat)
            self.array_path_type = _TRANSPOSE
            self._canonical = f"[{self.transpose.canonical_form}]"
        else:
            index = _non_negative_int_str(meat)
            if index is None:
                raise SpecError(f"Bad explict array index:{meat} from key:{key}")
            self.array_index = index
            self.array_path_type = _EXPLICIT_INDEX
            self._canonical = f"[{index}]"

    @property
    def canonical_form(self) -> str:
        return self._canonical

    @property
    def is_explicit_array_index(self) -> bool:
        return self.array_path_type == _EXPLICIT_INDEX

    @property
    def explicit_array_index(self) -> int | None:
        return try_parse_int(self.array_index)

    def evaluate(self, walked_path: WalkedPath) -> str | None:
        t = self.array_path_type
        if t == _AUTO_EXPAND:
            return self._canonical
        if t == _EXPLICIT_INDEX:
            return self.array_index
        if t == _HASH:
            assert self.ref is not None
            matched = _step_from_end(walked_path, self.ref.path_index).matched_element
            return str(matched.hash_count)
        if t == _TRANSPOSE:
            assert self.transpose is not None
            return _non_negative_int_str(self.transpose.evaluate(walked_path))
        assert isinstance(self.ref, AmpReference)
        matched = _step_from_end(walked_path, self.ref.path_index).matched_element
        return _non_negative_int_str(matched.get_sub_key_ref(self.ref.key_group))

    def match(self, data_key: str, walked_path: WalkedPath) -> MatchedElement | None:
        if self.evaluate(walked_path) != data_key:
            return None
        orig_size = walked_path.last_element().orig_size
        if orig_size is None:
            return None
        return ArrayMatchedElement(data_key, orig_size)


# ---------------------------------------------------------------------------
# Spec string parsing (SpecStringParser / PathElementBuilder)
# ---------------------------------------------------------------------------


class _CharIter:
    __slots__ = ("s", "i")

    def __init__(self, s: str) -> None:
        self.s, self.i = s, 0

    def has_next(self) -> bool:
        return self.i < len(self.s)

    def next(self) -> str:
        c = self.s[self.i]
        self.i += 1
        return c


def parse_dot_notation(it: _CharIter, ref: str) -> list[str]:
    """Split an output path on unescaped dots, keeping ``@(...)`` groups whole."""
    paths: list[str] = []
    prev_escape = False
    sb: list[str] = []
    while it.has_next():
        c = it.next()
        curr_escape = c == "\\" and not prev_escape
        if prev_escape and c not in ".\\":
            sb.append("\\")
            sb.append(c)
        elif c == "@":
            sb.append("@")
            sb.append(parse_at_path_element(it, ref))
            s = "".join(sb)
            if not ("[" in s and "]" not in s):
                paths.append(s)
                sb = []
        elif c == ".":
            if prev_escape:
                sb.append(".")
            else:
                if sb:
                    paths.append("".join(sb))
                    sb = []
                prev_escape = False
                continue
        elif not curr_escape:
            sb.append(c)
        prev_escape = curr_escape
    if sb:
        paths.append("".join(sb))
    return paths


def parse_at_path_element(it: _CharIter, ref: str) -> str:
    if not it.has_next():
        return ""
    sb: list[str] = []
    is_parens = False
    parens = 0
    c = it.next()
    if c == "(":
        is_parens = True
        parens += 1
    elif c == ".":
        raise SpecError(f"Unable to parse dotNotation, invalid TransposePathElement : {ref}")
    sb.append(c)
    while it.has_next():
        c = it.next()
        sb.append(c)
        if is_parens:
            if c == "(":
                raise SpecError(f"Unable to parse dotNotation, too many open parens '(' : {ref}")
            if c == ")":
                parens -= 1
            if parens == 0:
                return "".join(sb)
        elif c == ".":
            return "(" + "".join(sb[:-1]) + ")"
    if is_parens and parens != 0:
        raise SpecError(f"Invalid @() pathElement from : {ref}")
    return "".join(sb)


def fix_leading_bracket_sugar(dot_notation: str) -> str:
    """``a[0]`` -> ``a.[0]`` (but not after ``@``, ``.`` or an escape)."""
    if not dot_notation:
        return ""
    out = [dot_notation[0]]
    prev = dot_notation[0]
    for curr in dot_notation[1:]:
        if curr == "[" and prev != "\\" and prev not in "@.":
            out.append(".")
        out.append(curr)
        prev = curr
    return "".join(out)


def remove_escaped_values(key: str) -> str:
    """Drop escaped characters (used to decide what kind of element a key is)."""
    out = []
    prev_escape = False
    for c in key:
        if c == "\\":
            prev_escape = not prev_escape
        else:
            if not prev_escape:
                out.append(c)
            prev_escape = False
    return "".join(out)


def remove_escape_chars(key: str) -> str:
    """Drop the escape backslashes, keeping the escaped characters."""
    out = []
    prev_escape = False
    for c in key:
        if c == "\\":
            if prev_escape:
                out.append(c)
                prev_escape = False
            else:
                prev_escape = True
        else:
            out.append(c)
            prev_escape = False
    return "".join(out)


def parse_function_args(arg_string: str) -> list[str]:
    """``fn(a,@(1,b),'c,d')`` -> ``['fn', 'a', '@(1,b)', "'c,d'"]``."""
    first = arg_string.index("(")
    args = [arg_string[:first]]
    body = arg_string[first + 1 : -1]
    sb: list[str] = []
    in_brackets = in_quotes = False
    for c in body:
        if c == "(":
            if not in_quotes:
                in_brackets = True
            sb.append(c)
        elif c == ")":
            if not in_quotes:
                in_brackets = False
            sb.append(c)
        elif c == "'":
            in_quotes = not in_quotes
            sb.append(c)
        elif c == "," and not in_brackets and not in_quotes:
            args.append("".join(sb).strip())
            sb = []
        else:
            sb.append(c)
    args.append("".join(sb).strip())
    return args


def parse_single_key_lhs(orig_key: str) -> PathElement:
    """Build the path element for one spec key (or one segment of an output path)."""
    if "\\" in orig_key:
        inspect = remove_escaped_values(orig_key)
        element_key = remove_escape_chars(orig_key)
    else:
        inspect = element_key = orig_key

    if inspect == "@":
        return AtPathElement(element_key)
    if inspect == "*":
        return StarAllPathElement(element_key)
    if inspect.startswith("["):
        if count_matches(inspect, "[") != 1 or count_matches(inspect, "]") != 1:
            raise SpecError(f"Invalid key:{orig_key} has too many [] references.")
        return ArrayPathElement(element_key)
    if inspect.startswith("@") or "@(" in inspect:
        return TransposePathElement.parse(orig_key)
    if "@" in inspect:
        raise SpecError(f"Invalid key:{orig_key} can not have an @ other than at the front.")
    if "$" in inspect:
        return DollarPathElement(element_key)
    if "[" in inspect:
        if count_matches(inspect, "[") != 1 or count_matches(inspect, "]") != 1:
            raise SpecError(f"Invalid key:{orig_key} has too many [] references.")
        return ArrayPathElement(element_key)
    if "&" in inspect:
        if "*" in inspect:
            raise SpecError(f"Invalid key:{orig_key}, Can't mix * with & ) ")
        return AmpPathElement(element_key)
    if "*" in inspect:
        stars = count_matches(inspect, "*")
        if stars == 1:
            return StarSinglePathElement(element_key)
        if stars == 2:
            return StarDoublePathElement(element_key)
        return StarRegexPathElement(element_key)
    if "#" in inspect:
        return HashPathElement(element_key)
    return LiteralPathElement(element_key)


def build_matchable_path_element(raw_key: str) -> PathElement:
    pe = parse_single_key_lhs(raw_key)
    if not pe.matchable:
        raise SpecError(f"Spec LHS key={raw_key} is not a valid LHS key.")
    return pe


def parse_dot_notation_rhs(dot_notation: str) -> list[PathElement]:
    fixed = fix_leading_bracket_sugar(dot_notation)
    keys = parse_dot_notation(_CharIter(fixed), dot_notation)
    out = []
    for key in keys:
        pe = parse_single_key_lhs(key)
        if isinstance(pe, AtPathElement):
            raise SpecError(f"'.@.' is not valid on the RHS: {dot_notation}")
        out.append(pe)
    return out


# ---------------------------------------------------------------------------
# Traversr: walk / create containers along a list of keys
# ---------------------------------------------------------------------------

_GET, _SET, _REMOVE = range(3)


class _Step:
    __slots__ = ("traversr", "child")
    container_type: type = dict

    def __init__(self, traversr: Traversr, child: _Step | None) -> None:
        self.traversr = traversr
        self.child = child

    def new_container(self) -> Any:
        return self.container_type()

    def get(self, tree: Any, key: str) -> Any:
        raise NotImplementedError

    def remove(self, tree: Any, key: str) -> Any:
        raise NotImplementedError

    def overwrite_set(self, tree: Any, key: str, data: Any) -> Any:
        raise NotImplementedError

    def traverse(self, tree: Any, op: int, keys: list[str], pos: int, data: Any) -> Any:
        if tree is None or not isinstance(tree, self.container_type):
            return MISSING
        key = keys[pos]
        if self.child is None:
            if op == _GET:
                return self.get(tree, key)
            if op == _SET:
                return self.traversr.handle_final_set(self, tree, key, data)
            return self.remove(tree, key)
        sub = self.traversr.handle_intermediate_get(self, tree, key, op)
        if sub is MISSING:
            return MISSING
        return self.child.traverse(sub, op, keys, pos + 1, data)


class _MapStep(_Step):
    __slots__ = ()
    container_type = dict

    def get(self, tree: dict[str, Any], key: str) -> Any:
        return tree.get(key, MISSING)

    def remove(self, tree: dict[str, Any], key: str) -> Any:
        return tree.pop(key, None)

    def overwrite_set(self, tree: dict[str, Any], key: str, data: Any) -> Any:
        tree[key] = data
        return data


class _ArrayStep(_Step):
    __slots__ = ()
    container_type = list

    def get(self, tree: list[Any], key: str) -> Any:
        i = parse_int(key)
        return tree[i] if 0 <= i < len(tree) else MISSING

    def remove(self, tree: list[Any], key: str) -> Any:
        i = parse_int(key)
        return tree.pop(i) if 0 <= i < len(tree) else MISSING

    def overwrite_set(self, tree: list[Any], key: str, data: Any) -> Any:
        i = parse_int(key)
        while len(tree) <= i:
            tree.append(None)
        tree[i] = data
        return data


class _AutoExpandStep(_ArrayStep):
    __slots__ = ()

    def get(self, tree: list[Any], key: str) -> Any:
        return MISSING

    def remove(self, tree: list[Any], key: str) -> Any:
        return MISSING

    def overwrite_set(self, tree: list[Any], key: str, data: Any) -> Any:
        tree.append(data)
        return data


class Traversr:
    """Get / set / remove a value in a tree following canonical path keys."""

    __slots__ = ("root", "length")

    def __init__(self, paths: list[str]) -> None:
        root: _Step | None = None
        for path in reversed(paths):
            root = self._make_step(path, root)
        assert root is not None
        self.root = root
        self.length = len(paths)

    def _make_step(self, path: str, child: _Step | None) -> _Step:
        if path == "[]":
            return _AutoExpandStep(self, child)
        if path.startswith("[") and path.endswith("]"):
            return _ArrayStep(self, child)
        return _MapStep(self, child)

    def _check(self, keys: list[str]) -> None:
        if len(keys) != self.length:
            raise TransformError(
                f"Traversal Path and number of keys mismatch, traversalLength:{self.length} "
                f"numKeys:{len(keys)}"
            )

    def get(self, tree: Any, keys: list[str]) -> Any:
        self._check(keys)
        return self.root.traverse(tree, _GET, keys, 0, None)

    def set(self, tree: Any, keys: list[str], data: Any) -> Any:
        self._check(keys)
        if tree is None:
            return MISSING
        return self.root.traverse(tree, _SET, keys, 0, data)

    def remove(self, tree: Any, keys: list[str]) -> Any:
        self._check(keys)
        if tree is None:
            return MISSING
        return self.root.traverse(tree, _REMOVE, keys, 0, None)

    def handle_final_set(self, step: _Step, tree: Any, key: str, data: Any) -> Any:
        return step.overwrite_set(tree, key, data)

    def handle_intermediate_get(self, step: _Step, tree: Any, key: str, op: int) -> Any:
        sub = step.get(tree, key)
        if sub is MISSING:
            sub = None
        if sub is None and op == _SET:
            assert step.child is not None
            sub = step.child.new_container()
            step.overwrite_set(tree, key, sub)
        return sub


class ShiftrTraversr(Traversr):
    """On final set, values landing on the same spot accumulate into a list."""

    __slots__ = ()

    def handle_final_set(self, step: _Step, tree: Any, key: str, data: Any) -> Any:
        existing = step.get(tree, key)
        if existing is MISSING or existing is None:
            step.overwrite_set(tree, key, data)
        elif isinstance(existing, list):
            existing.append(data)
        else:
            step.overwrite_set(tree, key, [existing, data])
        return data


class PathEvaluatingTraversal:
    """An output path (writer) or ``@(...)`` lookup path (reader) evaluated against a walked path."""

    __slots__ = ("elements", "traversr")

    def __init__(self, dot_notation: str, writer: bool) -> None:
        if ("*" in dot_notation and "\\*" not in dot_notation) or (
            "$" in dot_notation and "\\$" not in dot_notation
        ):
            raise SpecError(
                f"DotNotation (write key) can not contain '*' or '$' : write key: {dot_notation}"
            )
        cls = ShiftrTraversr if writer else Traversr
        if not is_blank(dot_notation):
            paths = parse_dot_notation_rhs(dot_notation)
            self.traversr = cls([pe.canonical_form for pe in paths])
        else:
            paths = []
            self.traversr = cls([""])
        for pe in paths:
            if not pe.evaluatable:
                raise SpecError(f"RHS key={pe.raw_key} is not a valid RHS key.")
        self.elements = paths

    def evaluate(self, walked_path: WalkedPath) -> list[str] | None:
        out = []
        for pe in self.elements:
            value = pe.evaluate(walked_path)
            if value is None:
                return None
            out.append(value)
        return out

    def write(self, data: Any, output: dict[str, Any], walked_path: WalkedPath) -> None:
        keys = self.evaluate(walked_path)
        if keys is not None:
            self.traversr.set(output, keys, data)

    def read(self, data: Any, walked_path: WalkedPath) -> Any:
        keys = self.evaluate(walked_path)
        if keys is None:
            return MISSING
        return self.traversr.get(data, keys)

    @property
    def canonical_form(self) -> str:
        return ".".join(pe.canonical_form for pe in self.elements)


def build_writer(raw: Any) -> PathEvaluatingTraversal:
    """An output path from a spec RHS string, rooted at :data:`ROOT_KEY`."""
    if not isinstance(raw, str):
        raise SpecError(
            f"Invalid spec, RHS should be a String or array of Strings. Value in question : {raw!r}"
        )
    path = ROOT_KEY if is_blank(raw) else f"{ROOT_KEY}.{raw}"
    return PathEvaluatingTraversal(path, writer=True)

