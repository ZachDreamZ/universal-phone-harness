# Contributing to Universal Phone Harness

Community contributions are welcome.

## Setup

```bash
git clone https://github.com/ZachDreamZ/universal-phone-harness.git
cd universal-phone-harness
python -m pip install -e ".[dev]"
python -m pytest -q
```

The unit suite uses the mock backend and requires no phone.

## Development rules

- Keep real-device actions opt-in and fail closed.
- Add regression tests for behavior changes.
- Never commit phone contents, screenshots, serial numbers, credentials, or local MCP configuration.
- Keep functions focused and names explicit.
- Preserve structured error contracts.
- Do not weaken destructive-action or stale-observation checks to make tests pass.

## Checks

```bash
python -m pytest -q
python -m compileall -q phone_harness benchmarks
python -m build
python -m twine check dist/*
```

## Commits

Use Conventional Commits:

```text
feat: add device selection tool
fix: reject stale indexed long press
docs: document WDA setup
```

## Pull requests

1. Branch from `main`.
2. Keep scope focused.
3. Update tests and documentation.
4. Run all checks.
5. Open a pull request and complete the template.

For vulnerabilities, follow [`SECURITY.md`](SECURITY.md) instead of opening a public issue.
