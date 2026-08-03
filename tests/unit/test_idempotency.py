"""Unit tests for in-memory idempotency state machine."""

from __future__ import annotations

from ai_bridge.persistence.idempotency import (
    Completed,
    Conflict,
    InMemoryIdempotencyStore,
    NewClaim,
    Processing,
)


def test_first_claim_is_new() -> None:
    store = InMemoryIdempotencyStore()
    assert isinstance(store.claim("r1", "h1"), NewClaim)


def test_processing_duplicate() -> None:
    store = InMemoryIdempotencyStore()
    store.claim("r1", "h1")
    assert isinstance(store.claim("r1", "h1"), Processing)


def test_completed_replay() -> None:
    store = InMemoryIdempotencyStore()
    store.claim("r1", "h1")
    response = {"req_id": "r1", "status": "success", "result": {"ok": True}}
    store.complete("r1", "h1", response)
    second = store.claim("r1", "h1")
    assert isinstance(second, Completed)
    assert second.response["status"] == "success"
    # Mutating returned dict must not corrupt store
    second.response["status"] = "tampered"
    third = store.claim("r1", "h1")
    assert isinstance(third, Completed)
    assert third.response["status"] == "success"


def test_conflict_different_hash() -> None:
    store = InMemoryIdempotencyStore()
    store.claim("r1", "h1")
    result = store.claim("r1", "h2")
    assert isinstance(result, Conflict)
    assert result.existing_payload_hash == "h1"


def test_failed_is_replayable() -> None:
    store = InMemoryIdempotencyStore()
    store.claim("r1", "h1")
    store.fail("r1", "h1", {"status": "error", "error_code": "timeout"})
    result = store.claim("r1", "h1")
    assert isinstance(result, Completed)
    assert result.response["error_code"] == "timeout"
