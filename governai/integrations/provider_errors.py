from __future__ import annotations

from enum import StrEnum
from typing import Any, TypedDict


class ProviderErrorCode(StrEnum):
    NO_OPTIONS = "NO_OPTIONS"
    UPSTREAM_ERROR = "UPSTREAM_ERROR"
    INVALID_INPUT = "INVALID_INPUT"
    TIMEOUT = "TIMEOUT"
    AUTH_ERROR = "AUTH_ERROR"
    UNKNOWN = "UNKNOWN"


class ProviderError(TypedDict, total=False):
    code: str
    message: str
    retriable: bool
    provider: str
    context: dict[str, Any]


def is_truthy_error(value: Any) -> bool:
    """Is truthy error."""
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "error"}
    if isinstance(value, (int, float)):
        return value != 0
    return bool(value)


def parse_provider_error(response: dict[str, Any]) -> ProviderError | None:
    """Parse provider error."""
    if not isinstance(response, dict):
        return None

    status = str(response.get("status") or "").lower()
    has_error = is_truthy_error(response.get("error")) or is_truthy_error(response.get("compat_error"))
    code = str(response.get("error_code") or "").upper()
    message = str(response.get("error_message") or response.get("error") or "").strip()

    if not (has_error or status == "error" or code):
        return None

    known = {item.value for item in ProviderErrorCode}
    normalized_code = code if code in known else ProviderErrorCode.UNKNOWN.value

    return ProviderError(
        code=normalized_code,
        message=message or "unknown_error",
        retriable=normalized_code
        in {
            ProviderErrorCode.UPSTREAM_ERROR.value,
            ProviderErrorCode.TIMEOUT.value,
            ProviderErrorCode.UNKNOWN.value,
        },
        provider=str((response.get("details") or {}).get("provider") or ""),
        context={"status": status, "details": response.get("details")},
    )
