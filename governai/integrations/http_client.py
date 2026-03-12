from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class HTTPResponse:
    status_code: int
    headers: dict[str, str]
    body: bytes

    def json(self) -> Any:
        """Json."""
        return json.loads(self.body.decode("utf-8"))

    def text(self) -> str:
        """Text."""
        return self.body.decode("utf-8", errors="replace")


class GovernedHTTPError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None, body: str = "") -> None:
        """Initialize GovernedHTTPError."""
        super().__init__(message)
        self.status_code = status_code
        self.body = body


@dataclass
class _CircuitState:
    failures: int = 0
    opened_at: float | None = None


@dataclass
class GovernedHTTPClient:
    timeout_seconds: float = 30.0
    retry_attempts: int = 3
    retry_backoff_seconds: float = 0.5
    retry_status_codes: set[int] = field(default_factory=lambda: {408, 429, 500, 502, 503, 504})
    circuit_fail_max: int = 5
    circuit_reset_seconds: float = 60.0

    def __post_init__(self) -> None:
        """Validate and normalize dataclass fields after initialization."""
        self._circuit = _CircuitState()

    def _circuit_open(self) -> bool:
        """Internal helper to circuit open."""
        if self._circuit.opened_at is None:
            return False
        if time.monotonic() - self._circuit.opened_at >= self.circuit_reset_seconds:
            self._circuit.failures = 0
            self._circuit.opened_at = None
            return False
        return True

    def _record_success(self) -> None:
        """Internal helper to record success."""
        self._circuit.failures = 0
        self._circuit.opened_at = None

    def _record_failure(self) -> None:
        """Internal helper to record failure."""
        self._circuit.failures += 1
        if self._circuit.failures >= self.circuit_fail_max:
            self._circuit.opened_at = time.monotonic()

    @staticmethod
    def _sync_request(
        *, method: str, url: str, timeout: float, headers: dict[str, str], payload: bytes | None
    ) -> HTTPResponse:
        """Internal helper to sync request."""
        req = Request(url=url, method=method.upper(), headers=headers, data=payload)
        try:
            with urlopen(req, timeout=timeout) as response:
                body = response.read()
                status = int(response.status)
                resp_headers = {k.lower(): v for k, v in response.headers.items()}
                return HTTPResponse(status_code=status, headers=resp_headers, body=body)
        except HTTPError as exc:
            body = exc.read() if hasattr(exc, "read") else b""
            raise GovernedHTTPError(
                f"HTTP request failed: {exc.code}", status_code=exc.code, body=body.decode("utf-8", errors="replace")
            ) from exc
        except URLError as exc:
            raise GovernedHTTPError(f"HTTP request network error: {exc}") from exc

    async def request(
        self,
        *,
        method: str,
        url: str,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        accept_status: set[int] | None = None,
    ) -> HTTPResponse:
        """Request."""
        if self._circuit_open():
            raise GovernedHTTPError("Circuit breaker is open")

        req_headers = dict(headers or {})
        payload: bytes | None = None
        if json_body is not None:
            payload = json.dumps(json_body).encode("utf-8")
            req_headers.setdefault("Content-Type", "application/json")

        attempts = max(1, int(self.retry_attempts))
        accepted = accept_status or set()

        for attempt in range(1, attempts + 1):
            try:
                response = await asyncio.to_thread(
                    self._sync_request,
                    method=method,
                    url=url,
                    timeout=self.timeout_seconds,
                    headers=req_headers,
                    payload=payload,
                )
                if accepted and response.status_code not in accepted:
                    raise GovernedHTTPError(
                        "HTTP status not accepted",
                        status_code=response.status_code,
                        body=response.text(),
                    )
                self._record_success()
                return response
            except GovernedHTTPError as exc:
                retryable = exc.status_code in self.retry_status_codes if exc.status_code is not None else True
                self._record_failure()
                if attempt >= attempts or not retryable:
                    raise
                await asyncio.sleep(self.retry_backoff_seconds * attempt)

        raise GovernedHTTPError("HTTP request exhausted retries")
