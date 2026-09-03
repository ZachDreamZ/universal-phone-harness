# Changelog

All notable changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [Unreleased]

## [1.1.0] - 2026-09-04

### Added

- Native MCP Resources: `phone://device/status`, `phone://screen/dom`, and `phone://diagnostics/efficiency` for passive agent state inspection
- Native MCP Prompts: `mobile_flow_qa`, `extract_screen_data`, and `troubleshoot_screen` agent workflow templates
- New MCP tools: `phone_get_clipboard` (read system clipboard) and `phone_save_screenshot` (export screenshot to disk with optional SoM)
- Direct disk export in `PhoneHarness.save_screenshot()` supporting both raw and Set-of-Marks annotated views
- Extended CLI subcommands: `phone-harness screenshot`, `phone-harness clipboard`, and `phone-harness report`
- Comprehensive test suite in `tests/test_mcp_upgrades.py` bringing test count to 114 passing tests

### Changed

- MCP stdio server now advertises and handles `resources` and `prompts` protocol capabilities
- Bumped version to `1.1.0`

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

[Unreleased]: https://github.com/ZachDreamZ/universal-phone-harness/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/ZachDreamZ/universal-phone-harness/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/ZachDreamZ/universal-phone-harness/releases/tag/v1.0.0
