"""Packaged E2E harnesses must resolve --out so library/add works when cwd is the EXE folder."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HARNESSES = (
    ROOT / "packaging" / "e2e" / "studio_masking_ux.py",
    ROOT / "packaging" / "e2e" / "studio_collage_export_disk.py",
)


def test_packaged_harnesses_resolve_out_directory() -> None:
    for path in HARNESSES:
        text = path.read_text(encoding="utf-8")
        assert "args.out.expanduser().resolve()" in text, path.name
