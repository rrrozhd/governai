from __future__ import annotations

from typing import Protocol, runtime_checkable

from governai.audit.emitter import AuditEmitter
from governai.models.audit import AuditEvent


@runtime_checkable
class SecretsProvider(Protocol):
    """Protocol for late-bound secret resolution.

    Per D-09: typing.Protocol with async resolve(key) -> str.
    Inject into LocalRuntime to enable secret access from tools.
    """

    async def resolve(self, key: str) -> str:
        """Resolve a secret by key. Raises KeyError if not found."""
        ...


class NullSecretsProvider:
    """Default no-op provider. Raises on any resolve() call.

    Per D-09: Ships as default — tools that call resolve() without
    a real provider get an immediate, descriptive error.
    """

    async def resolve(self, key: str) -> str:
        raise KeyError(
            f"No SecretsProvider configured. Cannot resolve secret '{key}'. "
            "Inject a SecretsProvider into LocalRuntime to enable secret resolution."
        )


class SecretRegistry:
    """Accumulates resolved secret values for emitter-level redaction.

    Per D-11: When SecretsProvider.resolve() is called, the value is
    registered here. The emitter's redaction pass scans for all registered values.

    Scope: per-runtime (not per-run). Asyncio is single-threaded — no lock needed.
    Extra redaction (from prior runs) is safe; missing redaction is a regulatory violation.
    """

    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, value: str) -> None:
        if value:  # never register empty string
            self._values.add(value)

    def redact(self, text: str) -> str:
        for secret in self._values:
            text = text.replace(secret, "[REDACTED]")
        return text


class RedactingAuditEmitter(AuditEmitter):
    """Wraps another emitter, applying secret redaction before persistence.

    Per D-10: Redaction at emitter level (pre-persist).
    Per Pitfall 2: Operates on full model_dump_json() to catch secrets
    in payload, extensions.data, and any other field.
    """

    def __init__(self, inner: AuditEmitter, registry: SecretRegistry) -> None:
        self._inner = inner
        self._registry = registry

    async def emit(self, event: AuditEvent) -> None:
        redacted_json = self._registry.redact(event.model_dump_json())
        redacted_event = AuditEvent.model_validate_json(redacted_json)
        await self._inner.emit(redacted_event)
