# Managed image API coverage (#512 / #506)

Date: 2026-11-19  
Tree: `develop` @ `cb068da`

## Scope

Automated FastAPI coverage for managed-sdr image grades with spatial
selections after #508/#509 architecture changes.

## Coverage (`tests/test_managed_image_api_coverage.py`)

| Case | Asserts |
|---|---|
| Stale revision | PUT returns 409 |
| Unknown grade command | 400/422 fail-closed |
| Primaries + HSL + brush/invert selections | persist on GET |
| Preview-frame | 200 JPEG under spatial CPU path |
| Still export job | completes; output file non-empty |
| `upsert_step_params` command | revision advances |

## Non-scope

Full WebView2 UI click E2E (tracked under #513 responsiveness harness).
Inventing new endpoints.
