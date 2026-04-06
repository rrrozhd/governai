from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from governai.audit.emitter import AuditEmitter
from governai.memory.auditing import AuditingMemoryConnector
from governai.memory.connector import MemoryConnector
from governai.memory.scoped import ScopedMemoryConnector
from governai.models.approval import ApprovalRequest
from governai.runtime.secrets import NullSecretsProvider, SecretRegistry, SecretsProvider


class ExecutionContext:
    def __init__(
        self,
        *,
        run_id: str,
        workflow_name: str,
        step_name: str,
        artifacts: Mapping[str, Any],
        channels: Mapping[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        approval_request: ApprovalRequest | None = None,
        secrets_provider: SecretsProvider | None = None,
        secret_registry: SecretRegistry | None = None,
        memory_connector: MemoryConnector | None = None,
        audit_emitter: AuditEmitter | None = None,
        thread_id: str | None = None,
    ) -> None:
        """Initialize ExecutionContext."""
        self.run_id = run_id
        self.workflow_name = workflow_name
        self.step_name = step_name
        self._artifacts = dict(artifacts)
        self._channels = dict(channels or {})
        self._metadata = metadata if metadata is not None else {}
        self.approval_request = approval_request
        self._secrets_provider = secrets_provider or NullSecretsProvider()
        self._secret_registry = secret_registry

        # Memory wiring: per-execution audit wrapping (not at init time)
        if memory_connector is not None and audit_emitter is not None:
            auditing = AuditingMemoryConnector(
                inner=memory_connector,
                emitter=audit_emitter,
                run_id=run_id,
                thread_id=thread_id,
                workflow_name=workflow_name,
            )
            self._memory: ScopedMemoryConnector | None = ScopedMemoryConnector(
                auditing, run_id=run_id, thread_id=thread_id, workflow_name=workflow_name
            )
        elif memory_connector is not None:
            self._memory = ScopedMemoryConnector(
                memory_connector, run_id=run_id, thread_id=thread_id, workflow_name=workflow_name
            )
        else:
            self._memory = None

    def get_artifact(self, key: str, default: Any = None) -> Any:
        """Get artifact."""
        return self._artifacts.get(key, default)

    def require_artifact(self, key: str) -> Any:
        """Require artifact."""
        if key not in self._artifacts:
            raise KeyError(f"Missing artifact: {key}")
        return self._artifacts[key]

    def artifacts_snapshot(self) -> dict[str, Any]:
        """Artifacts snapshot."""
        return deepcopy(self._artifacts)

    def get_channel(self, key: str, default: Any = None) -> Any:
        """Get channel."""
        return self._channels.get(key, default)

    def channels_snapshot(self) -> dict[str, Any]:
        """Channels snapshot."""
        return deepcopy(self._channels)

    def set_metadata(self, key: str, value: Any) -> None:
        """Set metadata."""
        self._metadata[key] = value

    def get_metadata(self, key: str, default: Any = None) -> Any:
        """Get metadata."""
        return self._metadata.get(key, default)

    @property
    def memory(self) -> ScopedMemoryConnector | None:
        """Access scoped memory connector. None if no connector configured."""
        return self._memory

    async def resolve_secret(self, key: str) -> str:
        """Resolve a secret by key. Registers value for audit redaction.

        Per SEC-02: Tools call this at execution time. The resolved value
        is registered with SecretRegistry so the emitter can redact it.
        """
        value = await self._secrets_provider.resolve(key)
        if self._secret_registry is not None:
            self._secret_registry.register(value)
        return value
