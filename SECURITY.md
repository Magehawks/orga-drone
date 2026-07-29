# Security Policy

## Supported versions

Security fixes are applied to the latest release on the `master` branch. Older tagged releases may not receive backports unless noted in release notes.

| Version | Supported |
| ------- | --------- |
| latest release | yes |
| older releases | best effort |

## Reporting a vulnerability

**Please do not open a public GitHub issue for security vulnerabilities.**

Instead, use one of these channels:

1. **Preferred:** [GitHub private security advisory](https://github.com/Magehawks/orga-drone/security/advisories/new) for this repository.
2. **Alternative:** Open a GitHub issue with minimal details and ask the maintainer to move the conversation private.

Include when possible:

- Affected version or commit
- Steps to reproduce
- Impact (local data exposure, RCE, path traversal, etc.)
- Suggested fix (optional)

## Scope

orga-drone is a **local-first** desktop app. Reports are in scope when they affect:

- The running application or bundled server on `127.0.0.1`
- Library indexing, file handling, or exports on the user's machine
- Dependencies with a realistic exploit path in this project

Out of scope: issues that require physical access to an unlocked machine, or misconfiguration of unrelated system software.

## Response

We aim to acknowledge reports within **7 days** and to share a fix or mitigation timeline when a valid issue is confirmed.

## Non-security bugs

For regular bugs and feature ideas, use [GitHub Issues](https://github.com/Magehawks/orga-drone/issues) with the appropriate template.
