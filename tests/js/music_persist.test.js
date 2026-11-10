import assert from "node:assert/strict";
import test from "node:test";
import {
  applyDeletedMusicTrack,
  bumpMusicPlaylistRevision,
  filterResurrectedMusicTracks,
  musicPlaylistRevisionOf,
  resolveMusicDeleteSuccess,
  shouldApplyMusicPlaylistResponse,
} from "../../src/orga_drone/static/js/studio/music-persist.js";

test("playlist revision bumps on a single shared counter", () => {
  const box = { value: 0 };
  assert.equal(bumpMusicPlaylistRevision(box), 1);
  assert.equal(bumpMusicPlaylistRevision(box), 2);
  assert.equal(musicPlaylistRevisionOf(box), 2);
  assert.equal(musicPlaylistRevisionOf(null), 0);
});

test("stale successful playlist responses must not fully apply", () => {
  assert.equal(shouldApplyMusicPlaylistResponse(2, 2), true);
  assert.equal(shouldApplyMusicPlaylistResponse(3, 2), false);
  assert.equal(shouldApplyMusicPlaylistResponse(1, 2), false);
});

test("local-remove drops only the deleted soundtrack id", () => {
  const tracks = [
    { id: 1, volume: 0.8 },
    { id: 2, volume: 0.35 },
  ];
  assert.deepEqual(applyDeletedMusicTrack(tracks, 1), [{ id: 2, volume: 0.35 }]);
  assert.deepEqual(applyDeletedMusicTrack(tracks, "2"), [{ id: 1, volume: 0.8 }]);
  assert.deepEqual(applyDeletedMusicTrack(tracks, ""), tracks);
});

test("stale DELETE keeps newer local volume while removing A", () => {
  const current = [
    { id: "1", volume: 0.8 },
    { id: "2", volume: 0.35 },
  ];
  const staleResponse = [{ id: "2", volume: 0.8 }];
  const resolved = resolveMusicDeleteSuccess({
    localRevision: 5,
    mutationRevision: 4,
    currentTracks: current,
    responseTracks: staleResponse,
    trackId: "1",
  });
  assert.equal(resolved.mode, "local-remove");
  assert.deepEqual(resolved.tracks, [{ id: "2", volume: 0.35 }]);
});

test("current DELETE may take the server playlist", () => {
  const resolved = resolveMusicDeleteSuccess({
    localRevision: 3,
    mutationRevision: 3,
    currentTracks: [
      { id: "1", volume: 0.8 },
      { id: "2", volume: 0.8 },
    ],
    responseTracks: [{ id: "2", volume: 0.8 }],
    trackId: "1",
  });
  assert.equal(resolved.mode, "full");
  assert.deepEqual(resolved.tracks, [{ id: "2", volume: 0.8 }]);
});

test("newer DELETE tombstones block stale payload resurrection", () => {
  const removed = new Set(["1"]);
  assert.deepEqual(
    filterResurrectedMusicTracks(
      [
        { id: "1", volume: 0.8 },
        { id: "2", volume: 0.35 },
      ],
      removed
    ),
    [{ id: "2", volume: 0.35 }]
  );
  assert.deepEqual(filterResurrectedMusicTracks([{ id: "2" }], removed), [{ id: "2" }]);
});
