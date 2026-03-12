from __future__ import annotations

from governai.integrations.provider_errors import ProviderErrorCode, parse_provider_error


def test_parse_provider_error_known_code() -> None:
    parsed = parse_provider_error(
        {
            "status": "error",
            "error": True,
            "error_code": "TIMEOUT",
            "error_message": "timeout",
        }
    )
    assert parsed is not None
    assert parsed["code"] == ProviderErrorCode.TIMEOUT.value
    assert parsed["retriable"] is True


def test_parse_provider_error_unknown_code_maps_to_unknown() -> None:
    parsed = parse_provider_error(
        {
            "status": "error",
            "error": "true",
            "error_code": "WHATEVER",
            "error_message": "boom",
        }
    )
    assert parsed is not None
    assert parsed["code"] == ProviderErrorCode.UNKNOWN.value
