# Reference JOLT test fixtures

These JSON files are copied **unmodified** from the reference Java
implementation of JOLT:

- Repository: https://github.com/bazaarvoice/jolt
- Path: `jolt-core/src/test/resources/json/`
- Commit: `990aee98233362dd0a1c8975056f280c55305c19`
- License: Apache License 2.0 (see `LICENSE` in this directory)
- Copyright: Bazaarvoice, Inc.

Folders copied: `shiftr`, `defaultr`, `removr`, `cardinality`, `sortr`,
`modifier` (except `validation`) and `chainr/integration`.

Some files contain `//` comments, which the reference test suite allows;
`test_conformance.py` strips them before parsing.

To refresh from a newer upstream commit, copy the same folders again, update
the commit above, run `pytest tests/conformance`, and update
`../known_failures.txt` to match.
