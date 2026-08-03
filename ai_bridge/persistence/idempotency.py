"""In-memory disposable idempotency store for AI requests.

WARNING: Process-lifetime only. Restart clears all state. Not production-safe.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from enum import Enum, auto
from typing import Any, Protocol


class EntryState(Enum):
    PROCESSING = auto()
    COMPLETED = auto()
    FAILED = auto()


@dataclass(frozen=True, slots=True)
class NewClaim:
    """First claim for this req_id + payload_hash."""


@dataclass(frozen=True, slots=True)
class Processing:
    """Same key is already being processed."""


@dataclass(frozen=True, slots=True)
class Completed:
    """Terminal response already stored for this key."""

    response: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Conflict:
    """Same req_id was seen with a different payload_hash."""

    existing_payload_hash: str


ClaimResult = NewClaim | Processing | Completed | Conflict


class IdempotencyStore(Protocol):
    def claim(self, req_id: str, payload_hash: str) -> ClaimResult:
        """Atomically claim work for req_id + payload_hash."""

    def complete(self, req_id: str, payload_hash: str, response: dict[str, Any]) -> None:
        """Mark the key completed and store the replayable response."""

    def fail(self, req_id: str, payload_hash: str, response: dict[str, Any]) -> None:
        """Mark the key failed/terminal and store the replayable response."""


@dataclass
class _Entry:
    payload_hash: str
    state: EntryState
    response: dict[str, Any] | None = None


class InMemoryIdempotencyStore:
    """Thread-safe process-local store. Disposable; not restart-safe."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        # Index by req_id so conflict detection works across hashes.
        self._by_req_id: dict[str, _Entry] = {}

    def claim(self, req_id: str, payload_hash: str) -> ClaimResult:
        with self._lock:
            existing = self._by_req_id.get(req_id)
            if existing is None:
                self._by_req_id[req_id] = _Entry(
                    payload_hash=payload_hash,
                    state=EntryState.PROCESSING,
                )
                return NewClaim()

            if existing.payload_hash != payload_hash:
                return Conflict(existing_payload_hash=existing.payload_hash)

            if existing.state is EntryState.PROCESSING:
                return Processing()

            # COMPLETED or FAILED are both terminal and replayable for this slice.
            if existing.response is None:
                # Should not happen; treat as still processing defensively.
                return Processing()
            return Completed(response=dict(existing.response))

    def complete(self, req_id: str, payload_hash: str, response: dict[str, Any]) -> None:
        with self._lock:
            entry = self._by_req_id.get(req_id)
            if entry is None:
                self._by_req_id[req_id] = _Entry(
                    payload_hash=payload_hash,
                    state=EntryState.COMPLETED,
                    response=dict(response),
                )
                return
            if entry.payload_hash != payload_hash:
                return
            entry.state = EntryState.COMPLETED
            entry.response = dict(response)

    def fail(self, req_id: str, payload_hash: str, response: dict[str, Any]) -> None:
        with self._lock:
            entry = self._by_req_id.get(req_id)
            if entry is None:
                self._by_req_id[req_id] = _Entry(
                    payload_hash=payload_hash,
                    state=EntryState.FAILED,
                    response=dict(response),
                )
                return
            if entry.payload_hash != payload_hash:
                return
            entry.state = EntryState.FAILED
            entry.response = dict(response)

    def clear(self) -> None:
        """Test helper: wipe all state."""
        with self._lock:
            self._by_req_id.clear()
