# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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

[1.1.0]: https://github.com/sthitaprajnas/pyjolt/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/sthitaprajnas/pyjolt/releases/tag/v1.0.0
