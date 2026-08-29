# Security Policy

## Supported versions

Security fixes target the latest release.

| Version | Supported |
|---|---|
| 1.x | Yes |
| <1.0 | No |

## Report a vulnerability

Do not open a public issue. Email **zachdreamz@users.noreply.github.com** with:

- affected version and backend;
- impact and reproduction steps;
- proof of concept, if safe;
- suggested mitigation, if known.

Do not include real credentials, phone contents, screenshots, clipboard data, or persistent device identifiers.

Expect acknowledgment within 48 hours and an initial assessment within five business days.

## Scope

Examples include:

- destructive-action gate bypass;
- stale-observation or target-grounding bypass;
- secret leakage through DOM, images, errors, logs, or MCP responses;
- command injection through app names, URLs, text, or device identifiers;
- unauthorized network exposure of the MCP server;
- unsafe fallback from a real device to the mock backend.

## Operational guidance

- Run the MCP server locally over stdio.
- Keep USB debugging authorization limited to trusted hosts.
- Require explicit confirmation for destructive actions.
- Use post-action assertions for sensitive workflows.
- Do not expose device-control tools to untrusted prompts or clients.
