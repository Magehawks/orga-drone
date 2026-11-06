"""Validate the Story clock probe's sample filtering and stale-frame rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "packaging/e2e/studio_clock_probe.py"


@pytest.fixture
def probe(monkeypatch):
    monkeypatch.syspath_prepend(str(SCRIPT.parent))
    spec = importlib.util.spec_from_file_location("studio_clock_probe", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def video(current_time, *, src, ready=4, presented=None):
    return {
        "currentTime": current_time,
        "src": src,
        "ready": ready,
        "paused": False,
        "hidden": False,
        "seeking": False,
        "presented": presented,
        "events": {"timeupdate": 1, "seeking": 0, "seeked": 0},
    }


def sample(now, story, primary, outgoing):
    return {"now": now, "story": story, "videos": [primary, outgoing]}


def valid_report():
    source = "http://127.0.0.1/media/2/stream"
    outgoing = "http://127.0.0.1/media/1/stream"
    return {
        "transition": "crossfade",
        "playback": [
            sample(
                1000,
                2.2,
                video(0.0, src=outgoing, ready=0),
                video(
                    2.2,
                    src=outgoing,
                    presented={"mediaTime": 2.2, "observedAt": 1000},
                ),
            ),
            sample(
                1100,
                2.4,
                video(
                    0.4,
                    src=source,
                    presented={"mediaTime": 0.4, "observedAt": 1100},
                ),
                video(
                    2.4,
                    src=outgoing,
                    presented={"mediaTime": 2.4, "observedAt": 1100},
                ),
            ),
            sample(
                1200,
                2.6,
                video(
                    0.6,
                    src=source,
                    presented={"mediaTime": 0.6, "observedAt": 1200},
                ),
                video(
                    2.6,
                    src=outgoing,
                    presented={"mediaTime": 2.6, "observedAt": 1200},
                ),
            ),
        ],
    }


def test_empty_trace_is_insufficient(probe):
    assert probe.summarize({"transition": "crossfade", "playback": []}) == {
        "status": "INSUFFICIENT_SAMPLES"
    }


def test_cut_is_not_a_crossfade_trace(probe):
    report = valid_report()
    report["transition"] = "cut"
    assert probe.summarize(report)["status"] == "NOT_A_CROSSFADE_TRACE"


def test_unready_entry_sample_is_not_primary_drift(probe):
    result = probe.summarize(valid_report())
    assert result["primary_samples"] == 2
    assert result["primary_story_drift_max_s"] == pytest.approx(0.0)


def test_unready_primary_samples_cannot_claim_drift(probe):
    report = valid_report()
    for item in report["playback"]:
        item["videos"][0]["ready"] = 0
        item["videos"][0]["src"] = "http://127.0.0.1/media/1/stream"
    assert probe.summarize(report)["status"] == "NO_PRIMARY_SAMPLES"


def test_missing_presented_frames_are_not_zero_error(probe):
    report = valid_report()
    for item in report["playback"]:
        item["videos"][1]["presented"] = None
    result = probe.summarize(report)
    assert result["fresh_outgoing_presentations"] == 0
    assert result["stable_presented_pairs"] == 0
    assert result["presented_pair_drift_max_s"] is None
