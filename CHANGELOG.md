# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [2.0.0] — 2026-10-02

pyjolt now behaves exactly like the reference Java JOLT implementation. It
passes all 178 cases of the reference project's own test suite (shift,
default, remove, cardinality, sort, all three modify flavours and chained
transforms), which runs in CI as `tests/conformance`. A spec built on the
[JOLT demo site](https://jolt-demo.appspot.com) now gives the same output in
pyjolt. Before this release, 35 of those cases passed.

Every transform was rebuilt on a port of the reference path-matching engine.
The public API (`Chainr`, `Shift(spec).apply(data)`, …) is unchanged, but
some 1.x behaviour that differed from JOLT has changed — see *Upgrading* below.

### Added

- **`ModifyDefine`** / `modify-define-beta`: write only where a key does not
  exist.
- **Shift**: `@` and `@(n,path)` as spec keys (use input values as keys, e.g.
  turn `[{"name": k, "value": v}]` into `{k: v}`), `&` in spec keys, `\`
  escaping of special characters, `[#n]` and `[@(n,path)]` array indexes,
  `""` to write to the output root.
- **Default**: `a|b` keys, and `key[]` for arrays (including a top-level
  array input).
- **Modify**: all reference functions (`isPresent`, `notNull`, `isNull`,
  `squashDuplicates`, `sort`, `divide`, `divideAndRound`, `intSubtract`, …),
  `+` / `~` / `_` per-key mode prefixes, `?` "only if present" suffix, `[n]`
  array indexes, `^path` context lookups, and custom functions via
  `ModifyOverwrite(spec, functions={...})`. `pyjolt.MISSING` is exported for
  custom functions that produce no value.
- **Chainr**: `apply(data, context=...)`, and JOLT's Java class names
  (`com.bazaarvoice.jolt.Shiftr`, …) as operation names.
- **Remove**: `a|b` keys, multiple `*` in a key, removing array indexes.
- **Sort**: keys starting with `~` sort first, as in JOLT.
- A reference-conformance test suite (`tests/conformance`).

### Changed — upgrading from 1.x

- **`[]` always appends a new element.** In 1.x, `"out[].a"` and `"out[].b"`
  written under the same `*` match were grouped into one object; that was a
  pyjolt-only behaviour. Write to a shared index instead:
  `"out[&1].a"`, `"out[&1].b"`.
- **Shift returns `None` when nothing matches** (1.x returned `{}`).
- **Function arguments.** `"=fn"` still applies `fn` to the current value, but
  `"=fn(args)"` now uses *only* the given arguments, as in JOLT. 1.x passed the
  current value as a hidden first argument. Reference the current value with
  `@(1,key)`: `"=concat(@(1,name),'-x')"`, `"=min(@(1,n),10)"`,
  `"=split(',',@(1,s))"`. The `split` separator is a regular expression.
- **Function results follow JOLT.** For example `=toBoolean` only converts
  `"true"`/`"false"`, `=toInteger` on `3.7` gives `3`, and a function that
  can't produce a value leaves the field unchanged.
- **Unknown modify functions** emit a `UserWarning` and produce no value, so a
  list of alternatives falls through to the next one (1.x raised `SpecError`).
- **Default on arrays** requires JOLT's `key[]` syntax:
  `{"items[]": {"*": {...}}}`. A plain `{"items": {"*": {...}}}` no longer
  reaches into a list, and a top-level list input needs a `"*"` or index spec.
- **Cardinality**: `MANY` turns `null` into `[]` (1.x gave `[null]`).
  `ONE`/`MANY` are case-sensitive.
- **Invalid specs are rejected as in JOLT**: an empty `{}` spec for shift or
  cardinality, `#` in a shift output path, or array indexes mixed with object
  keys in a modify spec raise `SpecError`.
- Modify uses JOLT's function names `=toUpper` / `=toLower`; the 1.x names
  `=toUpperCase` / `=toLowerCase` still work. The other 1.x-only functions
  (`toFloat`, `floatSum`, `sum`, `sqrt`, `not`, `coalesce`, `startsWith`,
  `endsWith`, `contains`, `indexOf`) remain available, with JOLT-style
  arguments.

### Notes

- Transforms still never modify the input you pass in. `Chainr` now copies the
  input once instead of once per step.
- The engine does more work per key than 1.x did; expect roughly 1.4× the
  runtime of 1.2.2 on large inputs.

## [1.2.2] — 2026-10-02

### Fixed

- **Shift Transform**: Output paths now support explicit array indices such as
  `items.[&2].field`, `items[&1].field`, `list[0]` and `grid[&1][&0]`.
  Previously the bracketed index was written as a literal object key
  (e.g. `"[0]"`) instead of building an array
  ([#8](https://github.com/sthitaprajnas/pyjolt/issues/8)).

## [1.2.1] — 2026-04-10

### Fixed

- **License**: Updated to official Apache 2.0 text and standardised metadata
  for better PyPI compatibility.

## [1.2.0] — 2026-04-10

### Added

- **CLI**: Introduced a command-line interface (`pyjolt`) for running
  transformations from the shell. Supports file/stdin input and output.

## [1.1.0] — 2026-04-10

### Fixed

- **Shift Transform**: Improved JOLT spec compliance and stability in complex
  scenarios (multiple output paths, shared slot coordination).
- **Code Quality**: Fixed 60+ linting violations (Ruff) and resolved all Mypy
  type errors in core transforms.
- **Tests**: Cleaned up unused imports and standardized formatting across the
  entire test suite.

### Added

- **Complex Scenarios**: Added dedicated test suite for complex JOLT-like
  transformations (list-to-object mapping, deep nested array append).

## [1.0.0] — 2024-04-10

### Added

**Core transforms (full Java JOLT parity)**

- `Shift` — re-map fields with full spec language support:
  - Literal key matching
  - Wildcard `*` matching (prefix/suffix combinable, e.g. `prefix_*_suffix`)
  - OR patterns (`a|b`)
  - Self-reference `@` — uses the current input node as its own value
  - `$` / `$N` — emits the matched key name N levels up as a value
  - `#literal` — emits a constant string as a value
  - Output path tokens: `&`/`&N` back-references, `&(N,M)` capture groups,
    `@(N,path)` value lookups, `[]` array-append
  - Array-of-objects slot coordination — multiple fields from the same wildcard
    iteration land in the same output list element
  - Multiple output paths (list of strings)

- `Default` — fill absent or `null` fields; wildcard `*` applies to every key;
  list-aware (`{"key": {"*": sub_spec}}` applies `sub_spec` to each list element)

- `Remove` — delete specified fields; `"*"` removes all keys at a level

- `Sort` — recursively sort all dict keys alphabetically

- `Cardinality` — enforce `ONE` (scalar) or `MANY` (list) cardinality

- `ModifyOverwrite` / `ModifyDefault` — apply functions or literal values to
  fields; 39 built-in functions covering type conversions, string manipulation,
  numeric operations, and collection utilities:
  `toInteger`, `toLong`, `toDouble`, `toFloat`, `toString`, `toBoolean`,
  `trim`, `toUpperCase`, `toLowerCase`, `abs`, `min`, `max`, `intSum`,
  `doubleSum`, `longSum`, `floatSum`, `sum`, `avg`, `sqrt`, `not`,
  `size`, `concat`, `join`, `split`, `leftPad`, `rightPad`, `substring`,
  `startsWith`, `endsWith`, `contains`, `squashNulls`, `recursivelySquashNulls`,
  `toList`, `firstElement`, `lastElement`, `elementAt`, `indexOf`, `coalesce`,
  `noop`

- `Chainr` — chain multiple transforms sequentially; supports both direct
  instantiation and JOLT-spec lists (`from_spec`)

**Packaging**

- PEP 561 `py.typed` marker — full inline type annotations
- `pyproject.toml` with hatchling build backend, classifiers, URLs
- Python 3.10–3.13 support

**Tests**

- 193 tests across all transforms and real-world integration scenarios

[2.0.0]: https://github.com/sthitaprajnas/pyjolt/compare/v1.2.2...v2.0.0
[1.2.2]: https://github.com/sthitaprajnas/pyjolt/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/sthitaprajnas/pyjolt/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/sthitaprajnas/pyjolt/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/sthitaprajnas/pyjolt/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/sthitaprajnas/pyjolt/releases/tag/v1.0.0
