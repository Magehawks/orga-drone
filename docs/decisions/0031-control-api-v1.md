# ADR 0031: Opt-in local Studio Control API v1

Status: Accepted for issue #255 (PM/UX/CTO approved).

## Context

An optional local controller needs a small editing boundary while Studio selection,
inspector data and preview remain browser-owned. Direct backend writes alone
cannot safely establish editor readiness or synchronize the running inspector.

## Decision

Use a process-local control service, versioned authenticated HTTP routes, and one
injected sequential Studio polling bridge. Admission queues an idempotent expiring
command; execution follows a fresh editor readiness/selection check under temporary
input exclusion. Disable remains usable. Existing Host/Origin checks stay intact;
activation requires loopback binding and actual local peer access. The user supplies
a locally generated 256-bit key; retain only a digest and never echo it.

Bind tokens to instance, session, selection revision, history mutation revision and
a project fingerprint. Manual mutation requests conservatively invalidate tokens.
Use the existing history lock/stack with a narrow transactional context that captures
before/after values before commit and publishes the prepared history step afterward.
Merge existing image/color validators into one effect_settings write. No schema or
project-format changes. Explicitly distinguish commit, inspector ack and requested
preview refresh; retain committed/unconfirmed outcomes after UI loss.

## Consequences

One paused static video/editor, four controls, guarded Undo. No MCP adapter,
general event bus, new framework or provider dependency. Credentials, leases,
commands and history expire on restart; settings persist. Bounded IDs refuse
new commands at capacity rather than permitting replay. Existing preview limitations
remain. Human Windows/WebView2 verification precedes any merge decision.

See [the API contract](../CONTROL_API.md) for lifecycle, examples and verification.
