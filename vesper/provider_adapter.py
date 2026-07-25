"""Secure provider transport shared by connection validation and invocation."""
from __future__ import annotations

import ipaddress
import json
import socket
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Protocol


class ProviderTransportError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class ProviderResponseError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class SecretReader(Protocol):
    def get(self, ref: str) -> str | None: ...


@dataclass(frozen=True)
class ProviderConnection:
    connection_id: str
    provider: str
    base_url: str
    model_id: str
    api_style: str
    credential_ref: str | None
    endpoint_type: str = "custom"


@dataclass(frozen=True)
class AdapterResult:
    status: str
    output: str | None = None
    models: tuple[str, ...] = ()
    error: str | None = None


@dataclass(frozen=True)
class ProviderTrace:
    http_status: int | None
    content_type: str | None
    response_paths: tuple[str, ...]
    candidate_lengths: tuple[tuple[str, int], ...]


def _forbidden(ip: Any, *, local: bool) -> bool:
    if ip.is_unspecified or ip.is_multicast or ip.is_link_local or ip.is_reserved:
        return True
    if str(ip) in {"169.254.169.254", "100.100.100.200"}:
        return True
    if not local and (ip.is_loopback or ip.is_private):
        return True
    return False


def validate_url(url: str, *, endpoint_type: str) -> urllib.parse.ParseResult:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in ({"http", "https"} if endpoint_type == "local" else {"https"}):
        raise ProviderTransportError("INVALID_SCHEME", "HTTPS is required for remote provider connections")
    if not parsed.hostname or parsed.username or parsed.password:
        raise ProviderTransportError("INVALID_URL", "endpoint must contain a valid hostname")
    local = endpoint_type == "local"
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ProviderTransportError("DNS_RESOLUTION_FAILED", "endpoint hostname could not be resolved") from exc
    addresses = {ipaddress.ip_address(info[4][0]) for info in infos}
    if not addresses or any(_forbidden(address, local=local) for address in addresses):
        raise ProviderTransportError("UNSAFE_DESTINATION", "endpoint resolves to a forbidden network address")
    return parsed


class ProviderAdapter:
    def __init__(self, connection: ProviderConnection, secrets: SecretReader, *, timeout: float = 8.0):
        self.connection, self.secrets, self.timeout = connection, secrets, timeout
        self.last_trace: ProviderTrace | None = None

    def _request(self, path: str, *, method: str = "POST", payload: dict[str, Any] | None = None) -> dict[str, Any]:
        base = validate_url(self.connection.base_url, endpoint_type=self.connection.endpoint_type)
        url = urllib.parse.urljoin(base.geturl().rstrip("/") + "/", path.lstrip("/"))
        credential = self.secrets.get(self.connection.credential_ref) if self.connection.credential_ref else None
        if self.connection.credential_ref and credential is None:
            raise ProviderTransportError("CREDENTIAL_UNAVAILABLE", "provider credential is unavailable")
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if credential:
            if self.connection.provider == "anthropic":
                headers.update({"x-api-key": credential, "anthropic-version": "2023-06-01"})
            else:
                headers["Authorization"] = f"Bearer {credential}"
        request = urllib.request.Request(url, method=method, headers=headers, data=json.dumps(payload or {}).encode() if method != "GET" else None)
        opener = urllib.request.build_opener(_SafeRedirectHandler(self.connection.endpoint_type))
        try:
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read(2_000_000).decode("utf-8")
                decoded = json.loads(raw)
                if not isinstance(decoded, dict):
                    raise ValueError("provider response is not an object")
                response_payload: dict[str, Any] = decoded
                content_type = response.headers.get("Content-Type", "application/json") if hasattr(response, "headers") else "application/json"
                self.last_trace = ProviderTrace(response.status, content_type, tuple(self._response_paths(response_payload)), tuple(self._candidate_lengths(response_payload)))
                return response_payload
        except ProviderTransportError:
            raise
        except urllib.error.HTTPError as exc:
            code = "AUTHENTICATION_FAILED" if exc.code in {401, 403} else "MODEL_NOT_AVAILABLE" if exc.code == 404 else "PROVIDER_ERROR" if exc.code >= 500 else "PROVIDER_REQUEST_FAILED"
            raise ProviderTransportError(code, "provider request failed") from exc
        except (OSError, urllib.error.URLError, TimeoutError) as exc:
            raise ProviderTransportError("PROVIDER_UNREACHABLE", "provider is unreachable") from exc
        except ValueError as exc:
            raise ProviderTransportError("PROVIDER_ERROR", "provider returned invalid data") from exc

    def validate_and_invoke(self) -> AdapterResult:
        try:
            payload = self._request(self._generation_path(), payload=self._generation_payload())
            return self._result_from_payload(payload)
        except ProviderResponseError as exc:
            return AdapterResult("FAILED", error=exc.code)
        except ProviderTransportError as exc:
            return AdapterResult("REACHABLE", error=exc.code)

    def invoke(self, prompt: str, *, max_output_tokens: int | None = None) -> AdapterResult:
        try:
            payload = self._request(self._generation_path(), payload=self._generation_payload(prompt, max_output_tokens=max_output_tokens))
            return self._result_from_payload(payload)
        except ProviderResponseError as exc:
            return AdapterResult("FAILED", error=exc.code)
        except ProviderTransportError as exc:
            return AdapterResult("FAILED", error=exc.code)

    def _result_from_payload(self, payload: dict[str, Any]) -> AdapterResult:
        output = self._extract_output(payload)
        if output is None:
            raise ProviderResponseError("PROVIDER_RESPONSE_MALFORMED", "provider response has no supported assistant output field")
        if not output.strip():
            raise ProviderResponseError("MODEL_EMPTY_OUTPUT", "provider returned no final assistant text")
        return AdapterResult("MODEL_READY", output, self._extract_models(payload))

    def _generation_path(self) -> str:
        if self.connection.provider == "anthropic":
            return "/messages"
        if self.connection.provider == "gemini":
            return f"/models/{self.connection.model_id}:generateContent"
        return "/chat/completions"

    def _generation_payload(self, prompt: str = "Reply with exactly: VESPER_MODEL_READY", *, max_output_tokens: int | None = None) -> dict[str, Any]:
        """Build protocol payload; prompt is the already-normalized ContextPack wire input."""
        if max_output_tokens is not None and max_output_tokens <= 0:
            raise ValueError("max_output_tokens must be positive")
        if self.connection.provider == "anthropic":
            payload: dict[str, Any] = {"model": self.connection.model_id, "messages": [{"role": "user", "content": prompt}]}
            if max_output_tokens is not None:
                payload["max_tokens"] = max_output_tokens
            return payload
        if self.connection.provider == "gemini":
            payload = {"contents": [{"parts": [{"text": prompt}]}]}
            if max_output_tokens is not None:
                payload["generationConfig"] = {"maxOutputTokens": max_output_tokens}
            return payload
        # The route owns generation policy. Generic adapters only translate a
        # configured budget to the token parameter expected by this API style.
        payload = {"model": self.connection.model_id, "messages": [{"role": "user", "content": prompt}]}
        if max_output_tokens is not None:
            payload["max_tokens"] = max_output_tokens
        return payload

    @staticmethod
    def _response_paths(payload: dict[str, Any]) -> list[str]:
        paths: list[str] = []
        if "choices" in payload:
            paths.append("choices")
            if payload["choices"] and isinstance(payload["choices"][0], dict):
                choice = payload["choices"][0]
                if "message" in choice:
                    paths.append("choices[0].message")
                    if isinstance(choice["message"], dict) and "content" in choice["message"]:
                        paths.append("choices[0].message.content")
                if "text" in choice:
                    paths.append("choices[0].text")
        for key in ("output", "output_text", "content", "text", "reasoning", "candidates"):
            if key in payload:
                paths.append(key)
        return paths

    @staticmethod
    def _candidate_lengths(payload: dict[str, Any]) -> list[tuple[str, int]]:
        lengths: list[tuple[str, int]] = []
        for path, value in (("output_text", payload.get("output_text")), ("text", payload.get("text"))):
            if isinstance(value, str):
                lengths.append((path, len(value)))
        return lengths

    @staticmethod
    def _extract_output(payload: dict[str, Any]) -> str | None:
        if payload.get("choices"):
            choice = payload["choices"][0]
            if not isinstance(choice, dict):
                raise ProviderResponseError("PROVIDER_RESPONSE_MALFORMED", "provider choices item is malformed")
            message = choice.get("message", {})
            if not isinstance(message, dict):
                raise ProviderResponseError("PROVIDER_RESPONSE_MALFORMED", "provider message item is malformed")
            content = message.get("content")
            if isinstance(content, str):
                return content
            if isinstance(content, list):
                parts = [part.get("text", "") for part in content if isinstance(part, dict) and isinstance(part.get("text"), str)]
                return "".join(parts) or None
            if isinstance(choice.get("text"), str):
                return choice["text"]
            return None
        if payload.get("content"):
            if isinstance(payload["content"], list):
                parts = [part.get("text", "") for part in payload["content"] if isinstance(part, dict) and isinstance(part.get("text"), str)]
                return "".join(parts) or None
            return str(payload["content"])
        if isinstance(payload.get("output_text"), str):
            return payload["output_text"]
        if isinstance(payload.get("text"), str):
            return payload["text"]
        if payload.get("output") and isinstance(payload["output"], list):
            parts = []
            for item in payload["output"]:
                for content in item.get("content", []) if isinstance(item, dict) else []:
                    if isinstance(content, dict) and isinstance(content.get("text"), str):
                        parts.append(content["text"])
            return "".join(parts) or None
        if payload.get("candidates"):
            parts = payload["candidates"][0].get("content", {}).get("parts", [])
            text = "".join(part.get("text", "") for part in parts if isinstance(part, dict) and isinstance(part.get("text"), str))
            return text or None
        raise ProviderResponseError("PROVIDER_RESPONSE_MALFORMED", "provider response has no supported assistant text field")

    @staticmethod
    def _extract_models(payload: dict[str, Any]) -> tuple[str, ...]:
        return tuple(item.get("id", "").removeprefix("models/") for item in payload.get("data", []) if item.get("id"))


class _SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    def __init__(self, endpoint_type: str):
        self.endpoint_type = endpoint_type

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        validate_url(newurl, endpoint_type=self.endpoint_type)
        return super().redirect_request(req, fp, code, msg, headers, newurl)