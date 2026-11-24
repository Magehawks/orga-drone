"""TEST-ONLY low-space collage export check (never fills a real disk)."""
from __future__ import annotations

import os
import sys
from pathlib import Path

from PIL import Image


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: collage_low_space_sidecar.py <work_dir>", file=sys.stderr)
        return 2
    root = Path(sys.argv[1]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    os.environ["ORGA_DRONE_E2E"] = "1"
    os.environ["ORGA_DRONE_COLLAGE_STAGING_FREE_BYTES"] = "1024"
    os.environ["ORGA_DRONE_DATA_DIR"] = str(root / "data")

    from orga_drone.config import Settings
    from orga_drone.db import Database
    from orga_drone.export.studio_encoder import StudioExportError
    from orga_drone.studio_collage import assign_leaf_media, collage_spec_from_raw, iter_leaves
    from orga_drone.studio_export import run_studio_export
    import orga_drone.app as app
    import orga_drone.app_prefs as ap
    import orga_drone.config as cfg
    import orga_drone.studio_collage_still as st
    import orga_drone.studio_export as se

    prefs = Settings(data_dir=root / "data")
    ap.settings = prefs
    se.settings = prefs
    cfg.settings = prefs
    st.settings = prefs
    app.settings = prefs

    left = root / "a.jpg"
    right = root / "b.jpg"
    Image.new("RGB", (160, 90), (200, 0, 0)).save(left)
    Image.new("RGB", (160, 90), (0, 0, 200)).save(right)
    db = Database(root / "lib.sqlite3")
    project = db.ensure_default_studio_project()
    assert project is not None
    clip = db.add_studio_collage(project.id, preset="1+1", collage_duration_s=0.2)
    spec = collage_spec_from_raw(clip.collage_spec)
    leaves = iter_leaves(spec["root"])
    rid = db.add_root(root, label="sidecar")

    def add(path: Path, name: str) -> int:
        return db.upsert_media(
            {
                "root_id": rid,
                "primary_asset_id": None,
                "kind": "photo",
                "filename": name,
                "path": str(path.resolve()),
                "size_bytes": path.stat().st_size,
                "duration_s": None,
                "recorded_at": "2024-01-01T00:00:00",
                "sequence": None,
                "mode": None,
                "drone_model": None,
                "camera_model": None,
                "latitude": None,
                "longitude": None,
                "abs_alt": None,
                "has_srt": 0,
                "has_lrf": 0,
                "track_json": None,
            }
        )

    a = add(left, "a.jpg")
    b = add(right, "b.jpg")
    spec = assign_leaf_media(spec, leaves[0]["id"], {"source": "library", "media_id": a, "kind": "photo"})
    spec = assign_leaf_media(spec, leaves[1]["id"], {"source": "library", "media_id": b, "kind": "photo"})
    db.update_studio_collage(clip.id, collage_spec=spec, collage_duration_s=0.2)
    dest = root / "out.mp4"
    dest.write_bytes(b"sentinel")
    try:
        run_studio_export(
            db, height=720, output_path=dest, project_id=project.id, overwrite=True
        )
        print("UNEXPECTED_OK")
        return 1
    except StudioExportError as exc:
        print(f"ERR:{exc}")
        print(f"PRESERVED:{dest.read_bytes() == b'sentinel'}")
        return 0 if "Not enough temporary disk space" in str(exc) and dest.read_bytes() == b"sentinel" else 1


if __name__ == "__main__":
    raise SystemExit(main())
