# Secure assistant connection — acceptance matrix and blockers (#273 / #274)

Status: **BLOCKED on Product Owner approval of ADR 0033 proposed decisions.**
Audit date: 2026-11-24 (refreshed).
Architecture gate revision: 2026-11-24 — five decisions documented as
**proposed recommendations** in ADR 0033 and
`docs/discovery/273-274-architecture-decision-gate.md`.
Pinned baseline: merged PR #570 on `develop`; this follow-up does **not**
authorize production pairing.

This document records Phase-1 audit findings, the approved baseline security
regression surface, and the architecture decision gate. It does **not**
authorize production pairing, credential storage, Settings Connect UX, or
Control API key generation until the Product Owner accepts ADR 0033.

## Sources reviewed

| Source | Finding |
| --- | --- |
| Issue [#273](https://github.com/Magehawks/orga-drone/issues/273) | Secure pairing lifecycle; **reopened** after premature close on PR #570 |
| Issue [#274](https://github.com/Magehawks/orga-drone/issues/274) | Connect AI Assistant Settings UX; blocked on #273 |
| Issue #273 gap comment (2026-11-12) | Explicitly **BLOCKED on PO spike approval**; five PO decisions listed |
| PR [#570](https://github.com/Magehawks/orga-drone/pull/570) | Merged audit + baseline CI; **not** production pairing |
| [273-pairing-threat-model.md](273-pairing-threat-model.md) | Preferred later design sketched; residual same-user risk |
| [273-274-architecture-decision-gate.md](273-274-architecture-decision-gate.md) | Five recommended answers; STOP until PO accepts |
| ADR [0032](../decisions/0032-control-api-v1.md) | Control API v1: caller-supplied key, digest in memory |
| ADR [0033](../decisions/0033-secure-local-assistant-pairing.md) | Proposed concrete decisions; **not Accepted** |
| [CONTROL_API.md](../CONTROL_API.md) | Paste key; API never generates credentials (until ADR Accepted) |
| `orga-drone-mcp` CODEX_WINDOWS_POC | No secrets in config.toml `--env`; registration ≠ authorized; list-before-add |

## What ships today (unchanged)

- Opt-in Control API with loopback Host/Origin checks (`local_http.py`).
- Caller-supplied 64-hex pairing key → in-memory SHA-256 digest only.
- Bearer constant-time compare; disable / process exit drop the digest.
- Editor lease, state token, idempotency, guarded Undo preserved.
- Studio **External control** paste-key UI (developer-oriented).
- No app-generated credentials, no DPAPI store, no Settings “Connect AI Assistant”.

## Architecture decisions (proposed — require PO approval)

| # | Decision | Proposed answer (summary) | PO status |
| --- | --- | --- | --- |
| 1 | Credential handoff | One-shot DPAPI + user ACL slot; MCP memory retrieval; no TOML/`--env`/argv | Awaiting approval |
| 2 | Storage after handoff | App digest-only; MCP memory-only; restart clears active session | Awaiting approval |
| 3 | Registered vs authorized | Register may precede authorize; only authorize grants edit access | Awaiting approval |
| 4 | Connection identity | Single active connection_id; re-pair rotates secret; stale hosts fail | Awaiting approval |
| 5 | Repo boundary | App owns auth truth; MCP is adapter + Codex registration helpers | Awaiting approval |

Until ADR 0033 is **Accepted**, **no production pairing code, Settings Connect
UX, or CONTROL_API generation path may land.**

## Acceptance matrix

Legend: `PASS` = proven on this branch; `FAIL` = broken; `NOT_RUN` = not
executed; `BLOCKED` = cannot start without architecture approval;
`PARTIAL` = baseline only.

### #273 Secure local assistant pairing lifecycle

| Criterion | Status | Evidence / note |
| --- | --- | --- |
| User explicitly approves; registration alone never grants edit access | BLOCKED | Proposed in ADR 0033 decision 3; awaiting PO |
| App generates strong per-connection credentials | BLOCKED | Generation forbidden until ADR 0033 Accepted |
| Secure local retrieval (approved Windows protection) | BLOCKED | DPAPI slot proposed in ADR 0033 decision 1; awaiting PO |
| No plaintext secret in Codex config, argv, chat, MCP tools, logs, unsecured files | BLOCKED | Depends on (1)(2); PoC already refuses `--env` secrets |
| Connect / status / disconnect-revoke / restart / stale / re-pair | BLOCKED | Product states not implemented |
| Loopback-only, exact Origin, bearer auth preserved | PASS (baseline) | `local_http` + Control API tests; CI pairing gate |
| Editor lease, state-token, target selection, idempotency, guarded Undo | PASS (baseline) | Existing; must not weaken |
| Distinguish registered / authorized / reachable | BLOCKED | State model proposed in ADR 0033; not implemented |
| Unauthorized / revoked / stale clients rejected | PARTIAL | Wrong bearer / disable / restart covered by baseline tests; no connection-id revoke |
| Re-pair does not reauthorize old host process | BLOCKED | connection_id + digest rotation proposed; not implemented |
| App restart: no unintended active control session | PASS (baseline) | New `ControlService` starts disabled |
| Manual editing before/during/after pairing | PASS (baseline) | Current paste-key path; Connect UX not started |
| Automated tests: wrong creds, disconnect, reconnect, multi-process, restart | PARTIAL | Spike + `test_pairing_security_baseline.py` |
| Security review before merge | REQUIRED | Must accompany any future implementation PR |
| Independent security review (subagent / human) in addition to code review | REQUIRED | Stated in delivery PR |

### #274 Connect AI Assistant settings UX

| Criterion | Status | Evidence / note |
| --- | --- | --- |
| Settings → Connect AI Assistant entry | BLOCKED | Depends on #273 approved lifecycle |
| Detect supported client (Codex CLI on Windows first) | BLOCKED | No approved detection/registration contract in app |
| No terminal / manual JSON / secret copy-paste for creators | BLOCKED | Depends on secure handoff |
| Honest states (not installed, registration failed, registered, awaiting auth, connected, revoked) | BLOCKED | |
| Safe errors; no tokens / sensitive paths | BLOCKED | |
| Existing MCP entries not overwritten | BLOCKED | PoC proves list-before-add; app wiring absent |
| Windows packaged EXE clean profile | NOT_RUN | Blocked |
| UI/A11y tests for setup/cancel/failure/disconnect | NOT_RUN | Blocked |
| Manual Studio unchanged when integration disabled | PASS (baseline) | No Connect UX yet |
| No assistant marketplace / cloud / over-claim of clients | PASS (policy) | Out of scope retained |

### Phase 3 / 4 test plan

| Suite | Intent | Status now |
| --- | --- | --- |
| Unit: credential lifecycle, auth transitions, config preservation, revoke/stale, error sanitization | Mandatory CI | PARTIAL — baseline gate only |
| Integration: unauthorized/revoked, disconnect/reconnect, multi-process, restart, Origin/loopback, manual editor | Mandatory CI | PARTIAL — existing Control API + local_http |
| Native Windows WebView2 E2E with deterministic test clients (no live LLM) | Required evidence | NOT_RUN / BLOCKED |
| Regression: weaken auth / break revoke / unsafe config replace must fail CI | Mandatory security gates | PARTIAL — CI step runs pairing baseline; product revoke/config-replace still BLOCKED |
| Existing `tests/test_pairing_spike.py` | Digest not on disk; disable rejects bearer | PASS |
| New `tests/test_pairing_security_baseline.py` | Wrong bearer, disable, re-enable invalidates old key, restart, no key echo, no generate path | PASS (this branch) |

## Parallel-workstream ownership

To reduce conflicts with other feature agents:

| Area | Owner for this workstream | Do not change without coordination |
| --- | --- | --- |
| Pairing discovery / acceptance / threat docs | This branch (`docs/discovery/273*`, `274*`) | Other discovery topics |
| ADR 0033 + architecture gate | This branch until Accepted/Rejected | Do not mark Accepted without PO |
| Future pairing modules (after ADR) | New small modules under `src/orga_drone/` | Grow `studio.js` for this |
| `local_http.py` Host/Origin | **Frozen** — never weaken | Any feature |
| `control.py` auth model | Frozen until ADR Accepted | Timeline/color agents |
| Settings templates / locales (Connect section) | This workstream after ADR | Unrelated settings (LUT, collage) |
| `orga-drone-mcp` registration / retrieval | Separate repo; contract only after decision (5) | App inventing MCP transport |

Shared-file touches on this audit branch: discovery docs, proposed ADR 0033,
pairing baseline tests, and a dedicated CI pairing-security step. No changes to
`local_http.py`, `control.py`, Settings templates, or MCP transport.

## Threat-model alignment

Aligned with [273-pairing-threat-model.md](273-pairing-threat-model.md):

- Same-user process residual risk remains; DPAPI/ACL do not stop malware as the pilot.
- Preferred later design (generate, explicit approve, protected handoff, DPAPI+ACL at rest, keep loopback/Origin/bearer/lease, revocable connection identity) is **guidance only**, not an accepted ADR.
- Checkpoint and threat model both say: **do not ship production pairing** until a reviewed contract accepts residual risk.
- Codex PoC confirms: do not put secrets in `--env`/TOML; registration ≠ authorized connection; list before add so unrelated MCP entries are preserved.

## Remaining limitations (honest)

- No production secure pairing lifecycle.
- No Connect AI Assistant Settings UX.
- ADR 0033 now carries proposed concrete choices; still not Accepted / not implementable.
- Packaged WebView2 assistant journey NOT_RUN.
- Cross-repo boundary proposed in ADR 0033 decision 5; awaiting PO.
- Architecture-gate and implementation PRs must **not** close #273 or #274 until ACs are actually satisfied. #273 was reopened after premature close on PR #570.

## Required next steps (PO / security)

1. Product Owner accepts (or amends) the five proposed decisions in ADR 0033 / this gate doc in writing, then marks ADR 0033 Accepted.
2. Accept residual same-user risk in a reviewed security contract / ADR.
3. Only then implement the smallest #273 slice (generate + connection id + consent authorize + revoke/re-pair + status + mandatory security tests + CONTROL_API/ADR update).
4. #274 Settings UX follows that slice; keep Codex-first wording; no marketplace.
5. Every implementation PR requires **independent security review** in addition to normal code review (ChatGPT GitHub PR review + security-review). Do not self-merge.

## Implementation status on this branch

| Item | Status |
| --- | --- |
| Production pairing / credential store / DPAPI | None (intentionally) |
| Settings Connect UI | None (intentionally) |
| Weakening of Host/Origin | None |
| Approved-piece baseline security tests + CI gate | Added |
| Closing #273 / #274 | Forbidden while security requirements unresolved |

## Mutation proof (Phase 4, local)

Temporary mutations to `src/orga_drone/control.py` were applied with
`PYTHONPATH` pointed at this worktree, then reverted (working tree clean):

| Mutation | Expected CI failure | Result |
| --- | --- | --- |
| `authenticate` always returns (bypassed authorization) | `test_wrong_bearer_is_rejected` | FAIL as expected |
| `disable` leaves digest set (broken revocation) | `test_disable_revokes_and_rejects_old_bearer` | FAIL as expected |
| Restored baseline | pairing spike + baseline suite | 9 passed |

Unsafe MCP configuration replacement remains covered by the `orga-drone-mcp`
Codex PoC (`unrelated_preserved` / `name_conflict_rejected`), not by app
code on this branch.


