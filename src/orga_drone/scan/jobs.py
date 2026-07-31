"""In-memory library scan job store (one active scan; ephemeral history)."""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from orga_drone.scan.progress import ScanProgress

ACTIVE_STATES = frozenset({"pending", "running"})
FINISHED_STATES = frozenset({"completed", "failed"})


@dataclass
class ScanJob:
    id: str
    state: str = "pending"
    phase: str | None = None
    discovered: int = 0
    processed: int = 0
    current_path: str | None = None
    root_id: int | None = None
    error: str | None = None
    counts: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "state": self.state,
            "phase": self.phase,
            "discovered": self.discovered,
            "processed": self.processed,
            "current_path": self.current_path,
            "root_id": self.root_id,
            "error": self.error,
            "counts": self.counts,
        }


class ScanJobStore:
    """Thread-safe in-memory jobs. At most one active library scan."""

    def __init__(
        self,
        *,
        max_finished: int = 20,
        finished_ttl_s: float = 600.0,
    ) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, ScanJob] = {}
        self._active_id: str | None = None
        self.max_finished = max_finished
        self.finished_ttl_s = finished_ttl_s

    def has_active(self) -> bool:
        with self._lock:
            self._cleanup_locked()
            return self._active_id is not None

    def try_create(self, *, root_id: int | None = None) -> ScanJob | None:
        """Create a pending job, or return None if a scan is already active."""
        with self._lock:
            self._cleanup_locked()
            if self._active_id is not None:
                return None
            job = ScanJob(id=str(uuid.uuid4()), root_id=root_id)
            self._jobs[job.id] = job
            self._active_id = job.id
            return job

    def get(self, job_id: str) -> ScanJob | None:
        with self._lock:
            self._cleanup_locked()
            job = self._jobs.get(job_id)
            return None if job is None else self._copy(job)

    def mark_running(self, job_id: str) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in ACTIVE_STATES:
                return
            job.state = "running"
            job.updated_at = time.time()

    def apply_progress(self, job_id: str, progress: ScanProgress) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None or job.state not in ACTIVE_STATES:
                return
            if job.state == "pending":
                job.state = "running"
            job.phase = progress.phase
            job.discovered = progress.discovered
            job.processed = progress.processed
            job.current_path = progress.current_path
            if progress.root_id is not None:
                job.root_id = progress.root_id
            job.updated_at = time.time()

    def complete(
        self,
        job_id: str,
        counts: dict[str, Any] | list[dict[str, Any]] | None = None,
    ) -> None:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                return
            now = time.time()
            job.state = "completed"
            job.phase = "done"
            job.current_path = None
            job.counts = counts
            job.error = None
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
            job.error = (error or "Scan failed")[:500]
            job.updated_at = now
            job.finished_at = now
            if self._active_id == job_id:
                self._active_id = None
            self._cleanup_locked()

    def cleanup(self) -> None:
        with self._lock:
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
    def _copy(job: ScanJob) -> ScanJob:
        counts = job.counts
        if isinstance(counts, dict):
            counts_copy: dict[str, Any] | list[dict[str, Any]] | None = dict(counts)
        elif isinstance(counts, list):
            counts_copy = [dict(item) for item in counts]
        else:
            counts_copy = None
        return ScanJob(
            id=job.id,
            state=job.state,
            phase=job.phase,
            discovered=job.discovered,
            processed=job.processed,
            current_path=job.current_path,
            root_id=job.root_id,
            error=job.error,
            counts=counts_copy,
            created_at=job.created_at,
            updated_at=job.updated_at,
            finished_at=job.finished_at,
        )
