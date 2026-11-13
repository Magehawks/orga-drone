"""Independent Color Workspace acceptance inventory (#364/#365).

This module does not weaken RGB thresholds. It pins the matrix document and
records packaged Windows rows as NOT_RUN when deferred by PO.
"""

from __future__ import annotations

from pathlib import Path

MATRIX = (
    Path(__file__).resolve().parents[1]
    / "docs"
    / "planning"
    / "color-workspace-acceptance-matrix.md"
)

REQUIRED_VERDICTS = ("PASS", "FAIL", "NOT_RUN", "BLOCKED")
REQUIRED_SECTIONS = (
    "Managed color operations",
    "Animation clocks",
    "Scopes",
    "Explicit deferred packaged Windows checks",
)


def test_acceptance_matrix_document_exists_and_is_honest() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    assert "≤ 3.0" in text or "<= 3.0" in text or "≤3.0" in text or "<=3.0" in text
    assert "NOT_RUN — deferred by PO" in text
    assert "not packaged Windows UI parity" in text.lower() or "not** packaged" in text.lower()
    for section in REQUIRED_SECTIONS:
        assert section in text
    for verdict in REQUIRED_VERDICTS:
        assert verdict in text


def test_matrix_does_not_claim_packaged_webview2_pass() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    # Any table row that mentions packaged/WebView2/EXE must not verdict PASS.
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        lower = line.lower()
        if not any(
            token in lower
            for token in ("packaged", "webview2", "windows exe", "installer")
        ):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) < 2:
            continue
        verdict = cells[1]
        assert verdict.startswith(("NOT_RUN", "FAIL", "BLOCKED")), line

