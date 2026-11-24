# Architecture decision gate — Secure local assistant (#273 / #274)

Status: **STOP — awaiting Product Owner approval**
Date: 2026-11-24
Base: current `origin/develop` (includes merged PR #570 audit/baseline)
Branch purpose: document recommended architecture only; **no production pairing**

## Why this gate exists

Issue #273 requires a secure pairing lifecycle. Issue #274 depends on it.
PR #570 merged discovery docs, proposed ADR 0033 (open questions), and a CI
pairing security baseline for the **existing ADR 0032** paste-key model.

Closing #273 on that merge would be premature: acceptance criteria for
app-generated credentials, secure handoff, registered≠authorized, re-pair
isolation, and Settings Connect UX remain unmet.

This document + ADR 0033 revision **resolve the five open questions as
proposed recommendations**. They do **not** authorize implementation until the
Product Owner accepts them in writing.

## Five decisions — recommended answers

| # | Topic | Recommended (smallest secure local-first) |
| --- | --- | --- |
| 1 | Credential handoff | One-shot DPAPI (CurrentUser) + user ACL slot under app local data; MCP retrieves into memory; slot cleared/rotated. No argv / TOML / `--env` / chat / logs / URLs. |
| 2 | Storage after handoff | App: digest + non-secret metadata only; secret never long-lived on disk. MCP: memory only. App restart → no active Control session (re-authorize required). |
| 3 | Registered vs authorized | Registration (non-secret origin) may precede authorize. Only explicit user authorize grants Control API edit access. States: not_installed → … → registered → awaiting_authorization → connected → revoked. |
| 4 | Identity / multi-process / re-pair | Single active connection_id + digest. Re-pair rotates secret and drops old digest so stale hosts fail. No PID binding required for v1. |
| 5 | Repo boundary | `orga-drone` owns generate/authorize/revoke/digest auth/slot write and Host/Origin. `orga-drone-mcp` owns Codex list-before-add registration and bearer use as adapter. Shared contract doc only. |

Full prose, rejected alternatives, and residual same-user risk:  
[`docs/decisions/0033-secure-local-assistant-pairing.md`](../decisions/0033-secure-local-assistant-pairing.md).

## Must preserve (non-negotiable)

- `local_http.py` Host and Origin validation — never weaken
- Bearer constant-time compare; digests never echoed
- Editor lease, state token, idempotency, guarded Undo
- No cloud accounts, uploads, remote control, or marketplace
- No credentials in logs, URLs, screenshots, or unprotected config
- Source media never modified

## Explicit STOP

Until PO marks ADR 0033 **Accepted** (or posts equivalent written approval of
decisions 1–5 + residual risk):

- Do **not** ship Connect AI Assistant Settings UI
- Do **not** add production credential generation / handoff / storage
- Do **not** change `control.py` auth beyond ADR 0032
- Do **not** close #273 / #274
- Do **not** merge implementation without independent security review

## After PO approval (implementation order)

1. #273 smallest slice + mandatory security tests (unit, auth/revoke integration,
   wrong/missing credentials, restart/multi-process, leakage checks, mutation
   proofs that fail when auth/revoke are bypassed, deterministic MCP contract
   tests without paid LLM)
2. Integrate gates into Creator Regression Gates / CI
3. #274 minimal Connect / Disconnect / Reconnect Settings (DE/EN)
4. Native WebView2 E2E + packaged EXE E2E evidence
5. Independent security review before merge

## Issue status note

- #273 was closed when PR #570 merged despite unmet ACs; **reopened** with
  rationale. Remains OPEN / BLOCKED.
- #274 remains OPEN / BLOCKED on #273.
