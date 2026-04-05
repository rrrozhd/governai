"""Tests for SecretsProvider, NullSecretsProvider, SecretRegistry, RedactingAuditEmitter,
and ExecutionContext.resolve_secret (SEC-01, SEC-02, SEC-03, D-08, D-09, D-10, D-11).
"""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from governai.models.audit import AuditEvent, AuditExtension
from governai.models.common import EventType


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


class MockSecretsProvider:
    """Simple provider backed by a dict for testing."""

    def __init__(self, secrets: dict[str, str]) -> None:
        self._secrets = secrets

    async def resolve(self, key: str) -> str:
        if key not in self._secrets:
            raise KeyError(f"Secret not found: {key}")
        return self._secrets[key]


# ---------------------------------------------------------------------------
# Task 1: SecretsProvider protocol tests
# ---------------------------------------------------------------------------


def test_secrets_provider_protocol():
    """A class with async resolve(key) -> str satisfies SecretsProvider protocol."""
    from governai.runtime.secrets import SecretsProvider

    provider = MockSecretsProvider({"k": "v"})
    assert isinstance(provider, SecretsProvider)


def test_null_provider_raises():
    """NullSecretsProvider.resolve() raises KeyError with descriptive message."""
    from governai.runtime.secrets import NullSecretsProvider

    provider = NullSecretsProvider()
    with pytest.raises(KeyError, match="No SecretsProvider configured"):
        asyncio.run(provider.resolve("any_key"))


def test_secret_registry_register_and_redact():
    """SecretRegistry register then redact replaces secret value."""
    from governai.runtime.secrets import SecretRegistry

    reg = SecretRegistry()
    reg.register("my-secret-value")
    result = reg.redact("data: my-secret-value here")
    assert result == "data: [REDACTED] here"
    assert "my-secret-value" not in result


def test_secret_registry_multiple_values():
    """SecretRegistry redacts multiple registered secrets."""
    from governai.runtime.secrets import SecretRegistry

    reg = SecretRegistry()
    reg.register("aaa")
    reg.register("bbb")
    result = reg.redact("aaa and bbb")
    assert result == "[REDACTED] and [REDACTED]"


def test_secret_registry_empty_string_not_registered():
    """Registering empty string does not break redaction."""
    from governai.runtime.secrets import SecretRegistry

    reg = SecretRegistry()
    reg.register("")
    result = reg.redact("some text")
    assert result == "some text"


def test_secret_registry_no_match():
    """SecretRegistry redact is a no-op when secret not in text."""
    from governai.runtime.secrets import SecretRegistry

    reg = SecretRegistry()
    reg.register("secret-value-xyz")
    result = reg.redact("safe text with nothing sensitive")
    assert result == "safe text with nothing sensitive"


def test_redacting_emitter_removes_secret_from_payload():
    """RedactingAuditEmitter replaces secret in payload before emit."""
    from governai.audit.memory import InMemoryAuditEmitter
    from governai.runtime.secrets import RedactingAuditEmitter, SecretRegistry

    inner = InMemoryAuditEmitter()
    reg = SecretRegistry()
    reg.register("super-secret-123")
    emitter = RedactingAuditEmitter(inner, reg)

    event = AuditEvent(
        event_id="e1",
        run_id="r1",
        workflow_name="wf",
        event_type=EventType.RUN_STARTED,
        payload={"key": "super-secret-123"},
    )
    asyncio.run(emitter.emit(event))

    assert len(inner.events) == 1
    emitted = inner.events[0]
    assert "super-secret-123" not in str(emitted.payload)
    assert emitted.payload.get("key") == "[REDACTED]"


def test_redacting_emitter_removes_secret_from_extensions():
    """RedactingAuditEmitter redacts secrets in extensions.data."""
    from governai.audit.memory import InMemoryAuditEmitter
    from governai.runtime.secrets import RedactingAuditEmitter, SecretRegistry

    inner = InMemoryAuditEmitter()
    reg = SecretRegistry()
    reg.register("secret-xyz")
    emitter = RedactingAuditEmitter(inner, reg)

    event = AuditEvent(
        event_id="e2",
        run_id="r1",
        workflow_name="wf",
        event_type=EventType.RUN_STARTED,
        extensions=[AuditExtension(type_key="t", data={"token": "secret-xyz"})],
    )
    asyncio.run(emitter.emit(event))

    assert len(inner.events) == 1
    emitted = inner.events[0]
    assert emitted.extensions[0].data["token"] == "[REDACTED]"


def test_redacting_emitter_passthrough_no_secrets():
    """With empty registry, event passes through unchanged."""
    from governai.audit.memory import InMemoryAuditEmitter
    from governai.runtime.secrets import RedactingAuditEmitter, SecretRegistry

    inner = InMemoryAuditEmitter()
    reg = SecretRegistry()
    emitter = RedactingAuditEmitter(inner, reg)

    event = AuditEvent(
        event_id="e3",
        run_id="r1",
        workflow_name="wf",
        event_type=EventType.RUN_STARTED,
        payload={"safe": "value"},
    )
    asyncio.run(emitter.emit(event))

    assert len(inner.events) == 1
    assert inner.events[0].payload == {"safe": "value"}


def test_execution_context_resolve_secret():
    """ExecutionContext.resolve_secret resolves via provider and registers value."""
    from governai.runtime.context import ExecutionContext
    from governai.runtime.secrets import SecretRegistry

    provider = MockSecretsProvider({"db_pass": "hunter2"})
    reg = SecretRegistry()

    ctx = ExecutionContext(
        run_id="r1",
        workflow_name="wf",
        step_name="step1",
        artifacts={},
        secrets_provider=provider,
        secret_registry=reg,
    )

    result = asyncio.run(ctx.resolve_secret("db_pass"))
    assert result == "hunter2"
    # Value should now be registered for redaction
    assert reg.redact("hunter2") == "[REDACTED]"


def test_execution_context_resolve_secret_no_provider():
    """ExecutionContext without secrets_provider raises KeyError via NullSecretsProvider."""
    from governai.runtime.context import ExecutionContext

    ctx = ExecutionContext(
        run_id="r1",
        workflow_name="wf",
        step_name="step1",
        artifacts={},
    )

    with pytest.raises(KeyError, match="No SecretsProvider configured"):
        asyncio.run(ctx.resolve_secret("any"))


# ---------------------------------------------------------------------------
# Task 2: LocalRuntime wiring tests
# ---------------------------------------------------------------------------


def test_local_runtime_grants_wiring():
    """LocalRuntime(grants=[...]) registers capability_policy in policy_engine."""
    from governai.policies.capability import CapabilityGrant
    from governai.runtime.local import LocalRuntime

    runtime = LocalRuntime(grants=[CapabilityGrant(capability="x")])
    policy_names = [name for name, _ in runtime.policy_engine._global]
    assert "capability_policy" in policy_names


def test_local_runtime_secrets_wraps_emitter():
    """LocalRuntime(secrets_provider=...) wraps audit_emitter with RedactingAuditEmitter."""
    from governai.runtime.local import LocalRuntime
    from governai.runtime.secrets import RedactingAuditEmitter

    provider = MockSecretsProvider({"k": "v"})
    runtime = LocalRuntime(secrets_provider=provider)
    assert isinstance(runtime.audit_emitter, RedactingAuditEmitter)


def test_local_runtime_no_secrets_no_wrapping():
    """LocalRuntime() without secrets_provider has InMemoryAuditEmitter (not wrapped)."""
    from governai.audit.memory import InMemoryAuditEmitter
    from governai.runtime.local import LocalRuntime

    runtime = LocalRuntime()
    assert isinstance(runtime.audit_emitter, InMemoryAuditEmitter)


def test_local_runtime_thread_store_default():
    """LocalRuntime().thread_store is an InMemoryThreadStore."""
    from governai.runtime.local import LocalRuntime
    from governai.runtime.thread_store import InMemoryThreadStore

    runtime = LocalRuntime()
    assert isinstance(runtime.thread_store, InMemoryThreadStore)


def test_archive_thread_emits_audit_event():
    """archive_thread() transitions thread to ARCHIVED and emits THREAD_ARCHIVED event (D-08)."""
    from governai.audit.memory import InMemoryAuditEmitter
    from governai.runtime.local import LocalRuntime
    from governai.runtime.thread_store import InMemoryThreadStore, ThreadStatus

    inner_emitter = InMemoryAuditEmitter()
    thread_store = InMemoryThreadStore()
    runtime = LocalRuntime(audit_emitter=inner_emitter, thread_store=thread_store)

    async def run():
        await thread_store.create("t1")
        await thread_store.transition("t1", ThreadStatus.ACTIVE)
        await thread_store.transition("t1", ThreadStatus.IDLE)
        return await runtime.archive_thread("t1", run_id="r1", workflow_name="wf")

    record = asyncio.run(run())

    # Thread should now be ARCHIVED
    assert record.status == ThreadStatus.ARCHIVED

    # An audit event with THREAD_ARCHIVED should have been emitted
    thread_archived_events = [
        e for e in inner_emitter.events if e.event_type == EventType.THREAD_ARCHIVED
    ]
    assert len(thread_archived_events) == 1
    event = thread_archived_events[0]
    assert event.payload.get("thread_id") == "t1"
