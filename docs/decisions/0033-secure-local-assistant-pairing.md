# ADR 0033: Secure local assistant pairing (proposed)

- **Status:** Proposed — **blocked** pending Product Owner approval
- **Date:** 2026-11-24 (recommendations recorded same day)
- **Deciders:** Product Owner + security review (**not approved**)
- **Related:** Issues #273, #274; ADR 0032; `docs/discovery/273-pairing-threat-model.md`;
  `docs/discovery/273-274-secure-assistant-acceptance-and-blockers.md`

## Context

Control API v1 (ADR 0032) uses a caller-supplied 64-hex pairing key kept only as
an in-memory SHA-256 digest. That model is unsuitable for one-click creator
onboarding (#274) and does not isolate stale host processes after re-pair (#273).

The pairing threat model and the Codex Windows registration PoC in
`orga-drone-mcp` record preferred later directions and plaintext `--env` risks.
They do **not** accept a production pairing contract. Same-user processes can
still read memory, command lines, and DPAPI material for that logon session.

## Decision gate (binding)

**No production pairing change is accepted in this ADR until the Product Owner
explicitly approves the five recommended answers below (or records alternate
choices) and residual same-user risk is accepted in writing.**

Until then Orga Drone must keep the ADR 0032 paste-key model:

- The API never generates or discloses a pairing credential.
- Digests stay process-local; disable and process exit drop them.
- Loopback Host/Origin checks in `local_http.py` must not be weakened.
- Editor lease, state token, idempotency, and guarded Undo stay intact.
- No cloud accounts, remote control, or broad "any assistant" claims.

Engineering must **stop** at this gate: no Connect UI, no credential generation,
no handoff store, no Settings "Connect AI Assistant" production path.

## Recommended answers (smallest secure local-first) — AWAITING PO

These recommendations are the smallest design that satisfies #273/#274 without
cloud dependencies, without plaintext Codex config, and without weakening
`local_http.py`. They are **not** Accepted until the Product Owner signs off.

### 1. Secure credential handoff

**Recommend:** One-shot Windows-local handoff file under the Orga Drone app-data
tree, encrypted with **DPAPI (CurrentUser)** and restricted by a
**user-only ACL**. The app writes the blob only after explicit Connect approval.
The MCP adapter reads it once, decrypts in-process, then **deletes / marks
consumed** the handoff artifact.

**Reject for production:** command-line args, Codex `--env`, `config.toml`
secret fields, world-readable files, chat paste, cloud vaults.

**Residual risk (must be accepted by PO):** same-user malware can still read
DPAPI material for that logon session. DPAPI+ACL stop other OS users and casual
file copy off-machine; they are not a cross-process same-user boundary.

**Why smallest:** No named-pipe service to maintain; aligns with the threat-model
"preferred later design"; PoC already showed `--env`/TOML is unsafe.

### 2. Credential storage after handoff

**Recommend:**

| Party | What may be kept | Persistence |
| --- | --- | --- |
| Orga Drone | SHA-256 digest of the bearer only (ADR 0032 style) | **Process memory only**. App restart → Control API disabled, no unintended active session. |
| Orga Drone | Non-secret connection metadata (`connection_id`, status timestamps) | Optional local DB/settings; **never** the raw secret |
| MCP adapter | Raw bearer in process memory after successful retrieve | Memory only; never rewrite into Codex config / argv / logs |
| Handoff file | DPAPI blob | Ephemeral; single-use; gone after retrieve or revoke |

**Reject:** Persisting a usable plaintext or reversible secret across Orga Drone
restarts for "auto reconnect". Reconnect / re-pair after restart requires a new
explicit user approval (or an explicit PO override later — not in v1).

### 3. Registered versus authorized connection lifecycle

**Recommend distinct states:**

1. **Not installed / unavailable** — supported client missing.
2. **Registered** — MCP server entry present in the client config **without** a
   control secret (list-before-add; do not overwrite unrelated entries).
3. **Awaiting authorization** — user started Connect; app has not yet issued a
   live digest / handoff.
4. **Authorized / connected** — user approved; digest live in Orga Drone; adapter
   holds bearer; Control API commands allowed under existing lease/token rules.
5. **Reachable** — optional health check that the authorized adapter can talk to
   loopback Control API (status only; not a second auth factor).
6. **Revoked / disconnected** — digest cleared; handoff invalidated; bearer
   rejected.

**Rule:** Registration alone **never** grants Control API edit access. Only
**Authorized** (with a live digest) may mutate.

### 4. Connection identity, multi-process, re-pair isolation

**Recommend (v1):** Single active **`connection_id`** at a time, each with its own
256-bit credential → digest.

- **Connect:** generate new `connection_id` + secret; install digest; write
  one-shot handoff.
- **Disconnect / revoke:** clear digest; delete/invalidate handoff; reject that
  bearer forever.
- **Re-pair / Reconnect:** mint a **new** `connection_id` + secret; immediately
  invalidate the previous digest so any **stale host process** still holding the
  old bearer fails auth.
- **Multi-process:** do not share one digest across assistants. A second process
  that missed the new handoff cannot authorize with the old secret.
- **Restart (Orga Drone):** start disabled (no live digest). UI shows disconnected;
  user must Connect again.

Multi-concurrent authorized assistants are **out of scope for v1** (can be a
later ADR revision).

### 5. Responsibility boundary (`orga-drone` vs `orga-drone-mcp`)

| Concern | `orga-drone` | `orga-drone-mcp` |
| --- | --- | --- |
| User consent UI / Connect-Disconnect-Reconnect | Owns | No |
| Generate credential + `connection_id` | Owns | No |
| Digest auth, revoke, lease, state token, Undo guards | Owns (`control.py` + `local_http.py`) | No |
| Write / invalidate DPAPI handoff artifact | Owns | No |
| Read+consume handoff; hold bearer in memory | Contract only | Owns |
| Codex/MCP registration without secrets | May orchestrate via documented local hooks | Owns client-config edit (list-before-add) |
| MCP tool surface / LLM prompts | No provider/MCP transport in-app | Owns |
| Shared schema for handoff path + status enum | Shared contract doc in both repos | Shared contract |

**Reject:** Putting retrieve/revoke solely in MCP without app-side digest clear;
inventing MCP transport inside `orga-drone`; cloud token brokers.

## Alternatives considered

1. **Implement preferred later design without PO answers** — Rejected. Would
   invent security architecture and bypass the issue #273 gate.
2. **Ship #274 Settings UX on top of paste-key** — Rejected. Creator UX would
   still require secret handling and would over-claim a secure lifecycle.
3. **Put the pairing key in Codex `--env` / TOML** — Rejected by PoC and threat
   model (plaintext exposure via config and `codex mcp list --json`).
4. **Named pipe / ACL slot instead of DPAPI file** — Deferred. Slightly stronger
   ephemeral handoff, higher Windows service complexity; revisit if PO rejects
   file handoff.
5. **Persist reconnectable secret across app restart** — Rejected for v1
   (conflicts with "restart starts with no unintended active control session").
6. **Keep ADR 0032 only until PO decides** — Current enforced path. Baseline
   security regressions stay mandatory in CI.

## Consequences

- Positive: blockers become concrete recommendations; baseline auth regressions
  remain enforceable; no invented production store until PO signs off.
- Negative / trade-offs: #273 and #274 stay open; creators still use developer
  External control paste-key until Accepted + implemented + security-reviewed.
- Follow-up after PO approval: mark this ADR **Accepted** with the chosen
  answers → smallest #273 implementation slice + mandatory security tests →
  #274 Connect UX → independent security review on every implementation PR.
  Do not merge to `main` / release from this workstream.

## PO approval checklist

Product Owner must record one of:

- **Approve recommendations 1–5 as written**, including residual same-user risk; or
- **Approve with explicit deltas** (list which of 1–5 change and how); or
- **Reject** and keep ADR 0032 paste-key only.

Until that comment (or an Accepted revision of this ADR) exists,
**implementation of production Connect / pairing remains forbidden.**
