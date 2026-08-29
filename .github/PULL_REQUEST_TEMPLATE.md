## What this changes

<!-- Describe the behavior and motivation. -->

Closes #<!-- issue number, when applicable -->

## Type

- [ ] Bug fix
- [ ] Feature
- [ ] Documentation
- [ ] Tests
- [ ] Refactor or maintenance

## Safety impact

- [ ] No real-device behavior changed
- [ ] Real-device behavior changed and safety implications are documented
- [ ] Destructive-action and stale-observation gates remain enforced
- [ ] No credentials, phone contents, screenshots, or serial numbers are included

## Quality gates

- [ ] `python -m pytest -q`
- [ ] `python -m compileall -q phone_harness benchmarks`
- [ ] `python -m build`
- [ ] `python -m twine check dist/*`
- [ ] New behavior has regression tests
- [ ] Documentation is updated

## How to verify

<!-- Provide focused reproduction and verification steps. -->
