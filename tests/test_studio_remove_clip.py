"""Remove the selected Story clip without touching the file (Issue #155)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from orga_drone.db import make_identity_key
from tests.test_studio_history import _client, _seed


def test_trash_button_and_menu_are_labeled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    client, db = _client(tmp_path, monkeypatch)
    _seed(db, tmp_path / "videos", "A.MP4", 8.0)
    page = client.get("/studio", cookies={"lang": "en"})
    assert page.status_code == 200
    transport = page.text.split('class="studio-transport"', 1)[1].split("</div>", 1)[0]
    cut_at = transport.find('data-transport="cut"')
    remove_at = transport.find('data-transport="remove"')
    assert 0 <= cut_at < remove_at
    button = re.search(r'<button[^>]*id="studio-remove"[^>]*>', page.text)
    assert button is not None
    assert "disabled" in button.group(0)
    assert 'aria-label="Remove from story (Delete)"' in page.text
    assert "lucide-trash-2" in page.text[button.end() : button.end() + 250]
    assert 'id="studio-clip-menu"' in page.text
    assert 'id="studio-clip-menu-remove"' in page.text
    german = client.get("/studio", cookies={"lang": "de"})
    assert 'aria-label="Aus der Geschichte entfernen (Entf)"' in german.text
    script = Path("src/orga_drone/static/js/studio.js").read_text(encoding="utf-8")
    assert 'grid.addEventListener("contextmenu"' in script
    assert "function privacyMaskDeleteActive" in script
    assert "function removeSelectedStoryClip" in script
    assert "function storyClipDeleteContext" in script
    assert 'document.querySelector("dialog[open]")' in script
    assert 'node.closest("#studio-grid, #studio-playhead")' in script
    assert "clipMenuReturnFocus" in script
    assert 'item.focus()' in script
    handler = script.split('if (event.key === "Escape") hideClipMenu();', 1)[1]
    handler = handler.split("window.addEventListener", 1)[0]
    assert 'event.key !== "Delete"' in handler
    assert "Backspace" not in handler
    assert "storyClipDeleteContext(document.activeElement)" in handler
    assert 'if (isTextEditingTarget(document.activeElement)) return;' in handler
    assert 'if (privacyMaskDeleteActive()) return;' in handler


def test_remove_keeps_the_file_and_undo_restores_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, db = _client(tmp_path, monkeypatch)
    first = _seed(db, tmp_path / "a", "A.MP4", 12.0)
    second = _seed(db, tmp_path / "b", "B.MP4", 6.0)
    opened = db.resolve_studio_page_project()
    assert opened is not None
    source = tmp_path / "a" / "A.MP4"
    before = source.read_bytes()
    item = next(clip for clip in db.list_studio_items(opened.id) if clip.id == first)
    other = db.create_studio_project("Other")
    other_clip, _created = db.add_studio_item(
        item.media_path or "",
        identity_key=make_identity_key(item.filename, source.stat().st_size, item.recorded_at),
        filename=item.filename,
        recorded_at=item.recorded_at,
        kind="video",
        project_id=other.id,
    )
    trimmed = client.patch(
        f"/api/studio/{first}/section",
        json={"source_in_s": 1.0, "source_out_s": 4.0, "repeats": 2},
    )
    assert trimmed.status_code == 200

    removed = client.post(f"/studio/{first}/remove", follow_redirects=False)
    assert removed.status_code == 303
    assert [clip.id for clip in db.list_studio_items(opened.id)] == [second]
    assert source.read_bytes() == before
    with db.connect() as conn:
        media = conn.execute("SELECT COUNT(*) AS n FROM media").fetchone()
        assert media is not None and int(media["n"]) == 2
    assert any(clip.id == other_clip for clip in db.list_studio_items(other.id))

    undo = client.post("/api/studio/history/undo")
    assert undo.status_code == 200
    restored_items = db.list_studio_items(opened.id)
    restored = {clip.id: clip for clip in restored_items}
    assert [clip.id for clip in restored_items] == [first, second]
    assert restored[first].source_start == pytest.approx(1.0)
    assert restored[first].source_end == pytest.approx(4.0)
    redo = client.post("/api/studio/history/redo")
    assert redo.status_code == 200
    assert [clip.id for clip in db.list_studio_items(opened.id)] == [second]
    assert source.read_bytes() == before

    photo = _seed(db, tmp_path / "c", "C.JPG", 0.0)
    with db.connect() as conn:
        conn.execute("UPDATE media SET kind = 'photo' WHERE filename = 'C.JPG'")
        conn.execute("UPDATE studio_clips SET kind_snapshot = 'photo' WHERE id = ?", (photo,))
    card = client.post("/api/studio/title-cards")
    assert card.status_code == 200
    card_id = int(card.json()["id"])
    for clip_id in (photo, card_id):
        gone = client.post(f"/studio/{clip_id}/remove", follow_redirects=False)
        assert gone.status_code == 303
    left = [clip.id for clip in db.list_studio_items(opened.id)]
    assert photo not in left
    assert card_id not in left
    assert second in left
    assert source.read_bytes() == before
