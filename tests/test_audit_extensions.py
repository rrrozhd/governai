"""Tests for AUD-01, AUD-02, AUD-03: AuditExtension model, AuditEvent extensions field,
new EventType values, and emit_event extensions parameter.
"""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from governai.audit.emitter import emit_event
from governai.audit.memory import InMemoryAuditEmitter
from governai.models.audit import AuditEvent, AuditExtension
from governai.models.common import EventType


# ---------------------------------------------------------------------------
# AuditExtension model tests
# ---------------------------------------------------------------------------


def test_extension_model() -> None:
    ext = AuditExtension(type_key="zeroth.trace", data={"span_id": "abc"})
    assert ext.type_key == "zeroth.trace"
    assert ext.data == {"span_id": "abc"}


def test_extension_empty_data_default() -> None:
    ext = AuditExtension(type_key="foo")
    assert ext.data == {}


def test_extension_validation_rejects_missing_type_key() -> None:
    with pytest.raises(ValidationError):
        AuditExtension(data={"x": 1})  # type: ignore[call-arg]


# ---------------------------------------------------------------------------
# AuditEvent extensions field tests
# ---------------------------------------------------------------------------


def test_extensions_roundtrip() -> None:
    event = AuditEvent(
        event_id="e1",
        run_id="r1",
        workflow_name="w",
        event_type=EventType.RUN_STARTED,
        extensions=[AuditExtension(type_key="test", data={"k": "v"})],
    )
    serialized = event.model_dump_json()
    restored = AuditEvent.model_validate_json(serialized)
    assert len(restored.extensions) == 1
    assert restored.extensions[0].type_key == "test"
    assert restored.extensions[0].data == {"k": "v"}


def test_v022_backward_compat() -> None:
    """v0.2.2-era AuditEvent JSON without 'extensions' key deserializes to extensions=[]."""
    json_str = (
        '{"event_id":"e1","run_id":"r1","workflow_name":"w",'
        '"event_type":"run_started","payload":{}}'
    )
    event = AuditEvent.model_validate_json(json_str)
    assert event.extensions == []


# ---------------------------------------------------------------------------
# emit_event extensions parameter tests
# ---------------------------------------------------------------------------


def test_emit_event_with_extensions() -> None:
    emitter = InMemoryAuditEmitter()
    event = asyncio.run(
        emit_event(
            emitter,
            run_id="r1",
            workflow_name="w",
            event_type=EventType.RUN_STARTED,
            extensions=[AuditExtension(type_key="t", data={"a": 1})],
        )
    )
    assert len(event.extensions) == 1
    assert event.extensions[0].type_key == "t"
    assert event.extensions[0].data == {"a": 1}


def test_emit_event_without_extensions() -> None:
    emitter = InMemoryAuditEmitter()
    event = asyncio.run(
        emit_event(
            emitter,
            run_id="r1",
            workflow_name="w",
            event_type=EventType.RUN_STARTED,
        )
    )
    assert event.extensions == []


# ---------------------------------------------------------------------------
# New EventType values
# ---------------------------------------------------------------------------


def test_new_event_types_exist() -> None:
    assert EventType.THREAD_CREATED == "thread_created"
    assert EventType.THREAD_ACTIVE == "thread_active"
    assert EventType.THREAD_INTERRUPTED == "thread_interrupted"
    assert EventType.THREAD_IDLE == "thread_idle"
    assert EventType.THREAD_ARCHIVED == "thread_archived"
    assert EventType.CAPABILITY_DENIED == "capability_denied"
