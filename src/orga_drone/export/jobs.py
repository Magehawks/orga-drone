"""In-memory Studio export job store (one active export; ephemeral)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

ACTIVE_STATES = frozenset({"pending", "running"})
FINISHED_STATES = frozenset({"completed", "failed"})


def estimate_eta_s(elapsed_s: float, percent: int) -> float | None:
    """Rough remaining seconds from elapsed wall time and percent complete.

    Returns None until enough progress exists for a stable estimate.
    """
    p = int(percent)
    if p < 5 or p >= 100 or elapsed_s <= 0:
        return None
    total = float(elapsed_s) / (p / 100.0)
    remaining = total - float(elapsed_s)
    return max(0.0, remaining)


@dataclass
class ExportJob:
    id: str
    state: str = "pending"
    phase: str | None = None  # preparing | rendering | concat | done
    clip_index: int = 0
    clip_total: int = 0
    percent: int = 0
    current_label: str | None = None
    error: str | None = None
    output_path: str | None = None
    directory: str | None = None
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        now = time.time()
        start = self.started_at if self.started_at is not None else self.created_at
        if self.state in FINISHED_STATES and self.finished_at is not None:
            end = self.finished_at
        else:
            end = now
        elapsed_s = max(0.0, end - start)
        eta: float | None = None
        if self.state in ACTIVE_STATES:
            eta = estimate_eta_s(elapsed_s, self.percent)
        return {
            "id": self.id,
            "state": self.state,
            "phase": self.phase,
            "clip_index": self.clip_index,
            "clip_total": self.clip_total,
            "percent": self.percent,
            "current_label": self.current_label,
            "error": self.error,
            "output_path": self.output_path,
            "directory": self.directory,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "elapsed_s": round(elapsed_s, 1),
            "eta_s": None if eta is None else round(eta, 1),
        }


class ExportJobStore:
    """Thread-safe in-memory jobs. At most one active Studio export."""

    def __init__(
        self,
        *,
        max_finished: int = 20,
        finished_ttl_s: float = 600.0,
    ) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, ExportJob] = {}
        self._active_id: str | None = None
        self.max_finished = max_finished
        self.finished_ttl_s = finished_ttl_s

    def has_active(self) -> bool:
        with self._lock:
            self._cleanup_locked()
            return self._active_id is not None

    def try_create(self) -> ExportJob | None:
        with self._lock:
            self._cleanup_locked()
            if self._active_id is not None:
                return None
            job = ExportJob(id=str(uuid.uuid4()))
            self._jobs[job.id] = job
            self._active_id = job.id
            return job

    def get(self, job_id: str) -> ExportJob | None:
        with self._lock:
            self._cleanup_locked()
            job = self._jobs.get(job_id)
            return None if job is None else self._copy(job)

    def mark_running(self, job_id: str, *, clip_total: int = 0) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in ACTIVE_STATES:
                return
            now = time.time()
            job.state = "running"
            job.phase = "preparing"
            job.clip_total = max(0, int(clip_total))
            job.clip_index = 0
            job.percent = 0
            job.current_label = None
            job.started_at = now
            job.updated_at = now

    def apply_progress(self, job_id: str, progress: dict[str, Any]) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in ACTIVE_STATES:
                return
            if job.state == "pending":
                job.state = "running"
                if job.started_at is None:
                    job.started_at = time.time()
            if "phase" in progress and progress["phase"] is not None:
                job.phase = str(progress["phase"])
            if "clip_index" in progress and progress["clip_index"] is not None:
                job.clip_index = int(progress["clip_index"])
            if "clip_total" in progress and progress["clip_total"] is not None:
                job.clip_total = int(progress["clip_total"])
            if "percent" in progress and progress["percent"] is not None:
                # Never move percent backwards during a run (heartbeat / race).
                job.percent = max(job.percent, max(0, min(100, int(progress["percent"]))))
            if "current_label" in progress:
                label = progress["current_label"]
                job.current_label = None if label is None else str(label)[:200]
            job.updated_at = time.time()

    def complete(
        self,
        job_id: str,
        *,
        output_path: str,
        directory: str,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            now = time.time()
            job.state = "completed"
            job.phase = "done"
            job.percent = 100
            job.error = None
            job.output_path = output_path
            job.directory = directory
            job.current_label = None
            job.updated_at = now
            job.finished_at = now
            if self._active_id == job_id:
                self._active_id = None
            self._cleanup_locked()

    def fail(self, job_id: str, error: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            now = time.time()
            job.state = "failed"
            job.error = (error or "Export failed")[:500]
            job.updated_at = now
            job.finished_at = now
            if self._active_id == job_id:
                self._active_id = None
            self._cleanup_locked()

    def _cleanup_locked(self) -> None:
        now = time.time()
        stale = [
            jid
            for jid, job in self._jobs.items()
            if job.state in FINISHED_STATES
            and job.finished_at is not None
            and (now - job.finished_at) > self.finished_ttl_s
        ]
        for jid in stale:
            del self._jobs[jid]

        finished = sorted(
            (
                job
                for job in self._jobs.values()
                if job.state in FINISHED_STATES and job.finished_at is not None
            ),
            key=lambda j: j.finished_at or 0.0,
        )
        overflow = len(finished) - self.max_finished
        if overflow > 0:
            for job in finished[:overflow]:
                del self._jobs[job.id]

        if self._active_id is not None and self._active_id not in self._jobs:
            self._active_id = None
        elif self._active_id is not None:
            active = self._jobs.get(self._active_id)
            if active is None or active.state not in ACTIVE_STATES:
                self._active_id = None

    @staticmethod
    def _copy(job: ExportJob) -> ExportJob:
        return ExportJob(
            id=job.id,
            state=job.state,
            phase=job.phase,
            clip_index=job.clip_index,
            clip_total=job.clip_total,
            percent=job.percent,
            current_label=job.current_label,
            error=job.error,
            output_path=job.output_path,
            directory=job.directory,
            created_at=job.created_at,
            started_at=job.started_at,
            updated_at=job.updated_at,
            finished_at=job.finished_at,
        )
