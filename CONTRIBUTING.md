# Contributing

Thanks for considering a contribution! Note this project is in **alpha** —
APIs and UI may change without notice.

## Getting started

```bash
git clone https://github.com/mosandlt/Bosch-Smart-Home-Camera-Tool-Python-frontend.git
cd Bosch-Smart-Home-Camera-Tool-Python-frontend
pip install -e ".[dev]"
```

## Before opening a PR

```bash
pytest
ruff format --check .
ruff check .
mypy .
```

All of the above must pass. Please add or update tests for any behavior
change.

## Reporting bugs

Please open an issue using the bug report template and include:

* Your OS and Python version
* Steps to reproduce
* Relevant logs (with any tokens/secrets redacted)

## Security issues

Please do **not** open a public issue for security vulnerabilities — see
[SECURITY.md](SECURITY.md).

## Code of Conduct

This project follows the [Code of Conduct](CODE_OF_CONDUCT.md).
