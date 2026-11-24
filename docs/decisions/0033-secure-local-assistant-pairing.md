# ADR 0033: Secure local assistant pairing (proposed)

- **Status:** Proposed — **blocked** pending Product Owner security decisions
- **Date:** 2026-11-24
- **Deciders:** Product Owner + security review (not decided)
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

## Decision

**No production pairing change is accepted in this ADR.**

Until the Product Owner records explicit answers to the open questions below in
this ADR (or an equivalent reviewed contract) and residual same-user risk is
accepted, Orga Drone must keep the ADR 0032 paste-key model:

- The API never generates or discloses a pairing credential.
- Digests stay process-local; disable and process exit drop them.
- Loopback Host/Origin checks in `local_http.py` must not be weakened.
- Editor lease, state token, idempotency, and guarded Undo stay intact.
- No cloud accounts, remote control, or broad “any assistant” claims.

When unblocked, a follow-up revision of this ADR must replace the open questions
with concrete choices before any implementation PR merges.

## Open questions (must answer before Accepted)

1. **Handoff channel** — DPAPI-protected file, ACL-limited slot/pipe, or other
   Windows-local mechanism? Document residual same-user malware risk acceptance.
2. **Secret storage after handoff** — app-owned encrypted store versus host
   process memory. Codex `--env` / `config.toml` plaintext must not be the
   production path.
3. **registered vs authorized timing** — may MCP registration occur before
   explicit Studio/user authorize? Which states grant Control API edit access?
4. **Connection identity** — one digest versus multi connection-IDs /
   multi-process; how re-pair isolates a stale host process.
5. **Repo boundary** — retrieve/revoke in `orga-drone` only versus a shared
   contract with `orga-drone-mcp`.

## Alternatives considered

1. **Implement preferred later design without ADR answers** — Rejected. Would
   invent security architecture and bypass the issue #273 gate.
2. **Ship #274 Settings UX on top of paste-key** — Rejected. Creator UX would
   still require secret handling and would over-claim a secure lifecycle.
3. **Put the pairing key in Codex `--env` / TOML** — Rejected by PoC and threat
   model (plaintext exposure via config and `codex mcp list --json`).
4. **Keep ADR 0032 only until PO decides** — Current path. Baseline security
   regressions stay mandatory in CI.

## Consequences

- Positive: no invented credential store; blockers are explicit; baseline auth
  regressions remain enforceable.
- Negative / trade-offs: #273 and #274 stay open; creators still use developer
  External control paste-key.
- Follow-up work: PO answers → mark this ADR Accepted with concrete choices →
  smallest #273 slice + mandatory security tests → #274 Connect UX → independent
  security review on every implementation PR.
