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


def test_matrix_packaged_rows_cite_evidence_or_are_not_pass() -> None:
    text = MATRIX.read_text(encoding="utf-8")
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        lower = line.lower()
        if not any(token in lower for token in ("packaged", "webview2", "windows exe")):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        verdicts = [c for c in cells if c.startswith(("PASS", "FAIL", "PARTIAL", "NOT_RUN", "BLOCKED"))]
        if not any(v.startswith("PASS") for v in verdicts):
            continue
        assert any(
            "docs/planning" in cell or "acceptance-evidence" in cell or "packaging/e2e" in cell
            for cell in cells
        ), f"PASS packaged row must cite evidence: {line}" 


