"""Conformance suite: run the reference JOLT (Java) test fixtures against pyjolt.

The fixtures under ``fixtures/`` are copied verbatim from
https://github.com/bazaarvoice/jolt (``jolt-core/src/test/resources/json``),
see ``fixtures/README.md``. Each case mirrors how the Java test suite consumes
the same file, so a pass here means pyjolt produces the same output as the
reference implementation.

Cases that pyjolt does not pass yet are listed in ``known_failures.txt`` and
run as strict xfails: when a fix makes one pass, the suite fails until the
entry is removed, so the list only ever shrinks.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from pyjolt import Chainr, SpecError
from pyjolt.transforms import (
    Cardinality,
    Default,
    ModifyDefault,
    ModifyDefine,
    ModifyOverwrite,
    Remove,
    Shift,
    Sort,
)

HERE = Path(__file__).parent
FIXTURES = HERE / "fixtures"

# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _strip_comments(text: str) -> str:
    """Remove ``//`` and ``/* */`` comments (the Java fixtures use them) outside strings."""
    out: list[str] = []
    i, n = 0, len(text)
    in_str = False
    while i < n:
        ch = text[i]
        if in_str:
            out.append(ch)
            if ch == "\\" and i + 1 < n:
                out.append(text[i + 1])
                i += 2
                continue
            if ch == '"':
                in_str = False
            i += 1
        elif ch == '"':
            in_str = True
            out.append(ch)
            i += 1
        elif text.startswith("//", i):
            while i < n and text[i] != "\n":
                i += 1
        elif text.startswith("/*", i):
            end = text.find("*/", i + 2)
            i = n if end == -1 else end + 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def load(rel: str) -> Any:
    return json.loads(_strip_comments((FIXTURES / rel).read_text(encoding="utf-8")))


def _known_failures() -> set[str]:
    path = HERE / "known_failures.txt"
    lines = path.read_text(encoding="utf-8").splitlines()
    return {ln.split("#", 1)[0].strip() for ln in lines} - {""}


KNOWN_FAILURES = _known_failures()

# ---------------------------------------------------------------------------
# Comparison (equivalent to the Java suite's Diffy)
# ---------------------------------------------------------------------------


def _kind(v: Any) -> str:
    # bool before int: True == 1 in Python but not in JSON / Java
    for t, name in ((bool, "bool"), (int, "int"), (float, "float"), (str, "str")):
        if isinstance(v, t):
            return name
    if v is None:
        return "null"
    return "list" if isinstance(v, list) else "dict" if isinstance(v, dict) else type(v).__name__


def diff(expected: Any, actual: Any, path: str = "$", ignore_order: bool = False) -> str | None:
    """Return a description of the first difference, or None if equal.

    Stricter than ``==``: ``1``, ``1.0`` and ``True`` are different values,
    just as they are for the reference implementation.
    """
    ke, ka = _kind(expected), _kind(actual)
    if ke != ka:
        return f"{path}: expected {ke} {expected!r}, got {ka} {actual!r}"
    if ke == "dict":
        if expected.keys() != actual.keys():
            missing = sorted(expected.keys() - actual.keys())
            extra = sorted(actual.keys() - expected.keys())
            return f"{path}: missing keys {missing}, unexpected keys {extra}"
        for k in expected:
            if d := diff(expected[k], actual[k], f"{path}.{k}", ignore_order):
                return d
        return None
    if ke == "list":
        if len(expected) != len(actual):
            return f"{path}: expected {len(expected)} items, got {len(actual)}: {actual!r}"
        if ignore_order:
            remaining = list(actual)
            for e in expected:
                match = next(
                    (j for j, a in enumerate(remaining) if diff(e, a, ignore_order=True) is None),
                    None,
                )
                if match is None:
                    return f"{path}: no match for {e!r} in {actual!r}"
                remaining.pop(match)
            return None
        for i, (e, a) in enumerate(zip(expected, actual, strict=True)):
            if d := diff(e, a, f"{path}[{i}]", ignore_order):
                return d
        return None
    if expected != actual:
        return f"{path}: expected {expected!r}, got {actual!r}"
    return None


def assert_same(expected: Any, actual: Any, ignore_order: bool = False) -> None:
    if d := diff(expected, actual, ignore_order=ignore_order):
        pytest.fail(f"{d}\n\nfull output:\n{json.dumps(actual, indent=2, default=str)}")


# ---------------------------------------------------------------------------
# Case collection (mirrors the Java test classes)
# ---------------------------------------------------------------------------

_TRANSFORMS: dict[str, Callable[[Any], Any]] = {
    "shiftr": Shift,
    "defaultr": Default,
    "removr": Remove,
    "cardinality": Cardinality,
}

# Fixtures the Java suite uses for something other than input -> expected.
_SPECIAL = {
    "defaultr/__deepCopyTest.json",  # spec mutation test, covered below
    "removr/negativeTestCases.json",  # invalid spec, covered below
    "cardinality/failCardinalityType.json",  # invalid spec, covered below
}

# Modifier fixtures carry one expected output per flavour of the transform.
_MODIFIERS: dict[str, Any] = {
    "OVERWRITR": ModifyOverwrite,
    "DEFAULTR": ModifyDefault,
    "DEFINR": ModifyDefine,
}

# Function fixtures in the Java suite are only checked for one flavour.
_MODIFIER_FUNCTION_FLAVOUR = {"labelsLookupTest": "DEFAULTR"}
# The Java suite compares these two with array order respected.
_ORDERED_MODIFIER_CASES = {"squashNullsTests", "deleteDuplicatesTests"}


def _case(case_id: str, *values: Any) -> Any:
    marks = []
    if case_id in KNOWN_FAILURES:
        marks.append(pytest.mark.xfail(strict=True, reason="known_failures.txt"))
    return pytest.param(case_id, *values, id=case_id, marks=marks)


def _transform_cases() -> list[Any]:
    cases = []
    for folder in _TRANSFORMS:
        for f in sorted((FIXTURES / folder).glob("*.json")):
            rel = f"{folder}/{f.name}"
            if rel not in _SPECIAL:
                cases.append(_case(f"{folder}/{f.stem}", folder, rel))
    return cases


def _modifier_cases() -> list[Any]:
    cases = []
    for f in sorted((FIXTURES / "modifier").rglob("*.json")):
        rel = f.relative_to(FIXTURES).as_posix()
        unit = load(rel)
        if rel.startswith("modifier/functions/"):
            flavours = [_MODIFIER_FUNCTION_FLAVOUR.get(f.stem, "OVERWRITR")]
        else:
            flavours = [k for k in _MODIFIERS if k in unit]
        for flavour in flavours:
            cases.append(_case(f"{rel.removesuffix('.json')}[{flavour}]", rel, flavour))
    return cases


def _chainr_cases() -> list[Any]:
    return [
        _case(f"chainr/integration/{f.stem}", f"chainr/integration/{f.name}")
        for f in sorted((FIXTURES / "chainr/integration").glob("*.json"))
    ]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("case_id", "folder", "rel"), _transform_cases())
def test_transform(case_id: str, folder: str, rel: str) -> None:
    unit = load(rel)
    actual = _TRANSFORMS[folder](unit["spec"]).apply(unit["input"])
    assert_same(unit["expected"], actual)


def _label_computation(pick: Callable[..., int]) -> Callable[..., Any]:
    # Custom functions registered by the reference test suite (ModifierTest.java).
    def fn(*args: Any) -> Any:
        labels = args[0]
        keys = [int(k) for k in labels if k.lstrip("-").isdigit()]
        return labels.get(str(pick(keys)))

    return fn


_TEST_FUNCTIONS = {
    "minLabelComputation": _label_computation(min),
    "maxLabelComputation": _label_computation(max),
}


@pytest.mark.filterwarnings("ignore:Unknown modify function")
@pytest.mark.parametrize(("case_id", "rel", "flavour"), _modifier_cases())
def test_modifier(case_id: str, rel: str, flavour: str) -> None:
    unit = load(rel)
    transform = _MODIFIERS[flavour](unit["spec"], functions=_TEST_FUNCTIONS)
    actual = transform.apply(unit["input"], unit.get("context"))
    stem = Path(rel).stem
    assert_same(unit[flavour], actual, ignore_order=stem not in _ORDERED_MODIFIER_CASES)


@pytest.mark.parametrize(("case_id", "rel"), _chainr_cases())
def test_chainr(case_id: str, rel: str) -> None:
    unit = load(rel)
    actual = Chainr.from_spec(unit["spec"]).apply(unit["input"])
    assert_same(unit["expected"], actual)


def _sortr_case() -> list[Any]:
    return [_case("sortr/simple")]


@pytest.mark.parametrize("case_id", _sortr_case())
def test_sortr(case_id: str) -> None:
    expected = load("sortr/simple/output.json")
    actual = Sort().apply(load("sortr/simple/input.json"))
    assert_same(expected, actual)

    def key_order_errors(e: Any, a: Any, path: str = "$") -> str | None:
        if isinstance(e, dict) and isinstance(a, dict):
            if list(e) != list(a):
                return f"{path}: key order {list(a)} != {list(e)}"
            for k in e:
                if err := key_order_errors(e[k], a[k], f"{path}.{k}"):
                    return err
        elif isinstance(e, list) and isinstance(a, list):
            for i, (x, y) in enumerate(zip(e, a, strict=True)):
                if err := key_order_errors(x, y, f"{path}[{i}]"):
                    return err
        return None

    if err := key_order_errors(expected, actual):
        pytest.fail(err)


@pytest.mark.parametrize(
    "case_id",
    [_case("defaultr/__deepCopyTest")],
)
def test_defaultr_does_not_share_spec_objects(case_id: str) -> None:
    unit = load("defaultr/__deepCopyTest.json")
    transform = Default(unit["spec"])
    first = transform.apply(load("defaultr/__deepCopyTest.json")["input"])
    first["array"].append("a")
    first["map"]["c"] = "c"
    second = transform.apply(load("defaultr/__deepCopyTest.json")["input"])
    assert_same(unit["expected"], second)


@pytest.mark.parametrize(
    ("case_id", "factory", "rel"),
    [
        _case("removr/negativeTestCases", Remove, "removr/negativeTestCases.json"),
        _case(
            "cardinality/failCardinalityType", Cardinality, "cardinality/failCardinalityType.json"
        ),
    ],
)
def test_invalid_spec_rejected(case_id: str, factory: Callable[[Any], Any], rel: str) -> None:
    with pytest.raises(SpecError):
        factory(load(rel)["spec"])
