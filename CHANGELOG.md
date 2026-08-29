# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.0.0] - 2026-08-28

### Added

- Android, WebDriverAgent iOS, and deterministic mock backends
- MCP stdio server with 16 mobile-control tools
- CLI and Python APIs
- Indexed accessibility DOMs with observation generations
- Post-action assertions and re-grounded retry
- Destructive-action gates, step budgets, loop detection, and PII masking
- Local OCR and Set-of-Marks image support
- Connected-device benchmark and 108-test suite

### Changed

- Post-action DOM output now uses a separate 200-token estimated budget
- MCP JSON now uses compact encoding and native image content blocks
- Android text clearing now uses a hardware-validated long-press fast path

### Security

- Indexed MCP actions require matching observation generations
- Typed text and post-type DOMs are not echoed in MCP responses
- Client-facing and diagnostic errors avoid clipboard and secret values

[Unreleased]: https://github.com/ZachDreamZ/universal-phone-harness/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/ZachDreamZ/universal-phone-harness/releases/tag/v1.0.0
