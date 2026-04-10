# Contributing to PyJolt

Thank you for your interest in contributing! We welcome bug reports, feature
requests, and pull requests.

## Development setup

```bash
git clone https://github.com/sthitaprajnas/pyjolt.git
cd pyjolt
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Running tests

```bash
# All tests
pytest

# With coverage
pytest --cov=pyjolt --cov-report=term-missing

# Single file
pytest tests/test_shift.py -v
```

## Code quality

```bash
# Lint + auto-fix
ruff check src/pyjolt --fix

# Type check
mypy src/pyjolt
```

Both must pass with zero errors before a PR is merged.

## Submitting a pull request

1. Fork the repository and create a branch from `main`.
2. Add or update tests that cover your change.
3. Ensure `pytest`, `ruff check`, and `mypy` all pass.
4. Open a pull request with a clear description and reference any related issues.

## Reporting issues

Use [GitHub Issues](https://github.com/sthitaprajnas/pyjolt/issues).  For
security vulnerabilities, see [SECURITY.md](SECURITY.md).

## Coding conventions

- Follow existing code style (enforced by ruff).
- Full type annotations on all public functions.
- Docstrings on public classes and methods.
- No runtime dependencies beyond the Python standard library.

## License

By contributing you agree that your contributions will be licensed under the
[Apache License 2.0](LICENSE).
