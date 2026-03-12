from __future__ import annotations

import asyncio

import pytest

from governai.integrations.http_client import GovernedHTTPClient, GovernedHTTPError, HTTPResponse


def test_http_client_retries_then_succeeds() -> None:
    async def run() -> None:
        client = GovernedHTTPClient(retry_attempts=3, retry_backoff_seconds=0)
        calls = {"count": 0}

        def fake_sync_request(**kwargs):  # noqa: ARG001
            calls["count"] += 1
            if calls["count"] < 2:
                raise GovernedHTTPError("temporary", status_code=503)
            return HTTPResponse(status_code=200, headers={}, body=b'{"ok": true}')

        client._sync_request = staticmethod(fake_sync_request)  # type: ignore[assignment]
        response = await client.request(method="GET", url="http://example.test")
        assert response.status_code == 200
        assert response.json()["ok"] is True
        assert calls["count"] == 2

    asyncio.run(run())


def test_http_client_opens_circuit_after_failures() -> None:
    async def run() -> None:
        client = GovernedHTTPClient(retry_attempts=1, circuit_fail_max=2, retry_backoff_seconds=0)

        def fail_sync_request(**kwargs):  # noqa: ARG001
            raise GovernedHTTPError("down", status_code=503)

        client._sync_request = staticmethod(fail_sync_request)  # type: ignore[assignment]

        with pytest.raises(GovernedHTTPError):
            await client.request(method="GET", url="http://example.test")
        with pytest.raises(GovernedHTTPError):
            await client.request(method="GET", url="http://example.test")

        with pytest.raises(GovernedHTTPError, match="Circuit breaker is open"):
            await client.request(method="GET", url="http://example.test")

    asyncio.run(run())
