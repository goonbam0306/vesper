import socket
from unittest.mock import patch

import pytest

from vesper.provider_adapter import ProviderTransportError, validate_url


def _info(ip: str):
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))]


@pytest.mark.parametrize("ip", ["127.0.0.1", "192.168.1.20", "169.254.169.254"])
def test_custom_remote_rejects_private_and_metadata(ip):
    with patch("vesper.provider_adapter.socket.getaddrinfo", return_value=_info(ip)):
        with pytest.raises(ProviderTransportError) as exc:
            validate_url("https://provider.example/v1", endpoint_type="custom")
    assert exc.value.code == "UNSAFE_DESTINATION"


def test_remote_requires_https():
    with pytest.raises(ProviderTransportError) as exc:
        validate_url("http://provider.example/v1", endpoint_type="custom")
    assert exc.value.code == "INVALID_SCHEME"


def test_local_allows_loopback_but_not_metadata():
    with patch("vesper.provider_adapter.socket.getaddrinfo", return_value=_info("127.0.0.1")):
        validate_url("http://localhost:8080/v1", endpoint_type="local")
    with patch("vesper.provider_adapter.socket.getaddrinfo", return_value=_info("169.254.169.254")):
        with pytest.raises(ProviderTransportError):
            validate_url("http://metadata.local", endpoint_type="local")


def test_dns_private_result_is_rejected():
    with patch("vesper.provider_adapter.socket.getaddrinfo", return_value=_info("10.0.0.4")):
        with pytest.raises(ProviderTransportError):
            validate_url("https://rebinding.example", endpoint_type="custom")


def test_ephemeral_secret_lifecycle():
    from vesper.secret_store import EphemeralTestSecretStore

    store = EphemeralTestSecretStore()
    ref = store.put("unique-secret-marker", label="e2e")
    assert store.get(ref) == "unique-secret-marker"
    store.delete(ref)
    assert store.get(ref) is None
    assert "unique-secret-marker" not in repr(store)


def test_no_plaintext_in_route_reference():
    from vesper.model_runtime import ModelRoute

    route = ModelRoute("route", "model", "custom", frozenset({"text"}), "remote", 1.0, 0.0, 1.0, True, "secret://test/ref")
    assert "unique-secret-marker" not in repr(route)


@pytest.mark.parametrize("ip", ["224.0.0.1", "0.0.0.0"])
def test_special_destinations_rejected(ip):
    with patch("vesper.provider_adapter.socket.getaddrinfo", return_value=_info(ip)):
        with pytest.raises(ProviderTransportError):
            validate_url("https://provider.example", endpoint_type="custom")


def test_redirect_handler_rechecks_destination():
    from vesper.provider_adapter import _SafeRedirectHandler

    with patch("vesper.provider_adapter.validate_url", side_effect=ProviderTransportError("UNSAFE_DESTINATION", "blocked")):
        with pytest.raises(ProviderTransportError):
            _SafeRedirectHandler("custom").redirect_request(None, None, 302, "", None, "https://private.example")  # type: ignore[arg-type]


def test_secret_failure_has_no_value_in_error():
    from vesper.secret_store import SecretStoreError

    marker = "unique-secret-marker"
    error = SecretStoreError("could not save credential to the local keychain")
    assert marker not in str(error)


__all__ = []
