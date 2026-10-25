"""Process-wide lock for in-app renames and export destination approval.

The lock covers an in-app rename from the first file move through the database
update, and an export while it reads protected paths, records their file
identities, and approves the destination. It is not held during encoding.
Renames performed by other programs are outside this lock. A confirmed
overwrite is then limited to the handle opened at approval, and a name that
was free is created exclusively.
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager

media_mutation_lock = threading.Lock()

# Test seam. Called on the acquiring thread immediately before the lock is taken.
before_media_mutation_lock: Callable[[], None] | None = None


@contextmanager
def hold_media_mutation() -> Iterator[None]:
    """Hold the in-app rename and export-approval lock."""
    hook = before_media_mutation_lock
    if hook is not None:
        hook()
    media_mutation_lock.acquire()
    try:
        yield
    finally:
        media_mutation_lock.release()
