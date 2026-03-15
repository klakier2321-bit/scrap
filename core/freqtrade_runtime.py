"""Read-only client for the internal Freqtrade runtime API."""

from __future__ import annotations

import base64
import json
from typing import Any
from urllib import error, request


class FreqtradeRuntimeError(RuntimeError):
    """Structured runtime error returned by the read-only bridge."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class FreqtradeRuntimeClient:
    """Small, read-only HTTP client for the internal Freqtrade REST API."""

    def __init__(
        self,
        *,
        base_url: str,
        username: str,
        password: str,
        timeout_seconds: int = 5,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.password = password
        self.timeout_seconds = timeout_seconds

    def ping(self) -> dict[str, Any]:
        return self._request_json("ping", require_auth=False)

    def show_config(self) -> dict[str, Any]:
        return self._request_json("show_config")

    def balance(self) -> dict[str, Any]:
        return self._request_json("balance")

    def profit(self) -> dict[str, Any]:
        return self._request_json("profit")

    def trades(self) -> Any:
        return self._request_json("trades")

    def count(self) -> dict[str, Any]:
        return self._request_json("count")

    def performance(self) -> Any:
        return self._request_json("performance")

    def status(self) -> Any:
        return self._request_json("status")

    def _request_json(self, path: str, *, require_auth: bool = True) -> Any:
        url = f"{self.base_url}/{path.lstrip('/')}"
        headers = {"Accept": "application/json"}
        if require_auth:
            headers["Authorization"] = self._basic_auth_header()

        http_request = request.Request(url, headers=headers, method="GET")
        try:
            with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
                payload = response.read().decode("utf-8")
        except error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise self._translate_http_error(path=path, status=exc.code, body=body) from exc
        except error.URLError as exc:
            reason = getattr(exc, "reason", exc)
            raise FreqtradeRuntimeError(
                "runtime_unavailable",
                f"Freqtrade runtime API is unavailable: {reason}",
            ) from exc

        try:
            return json.loads(payload) if payload else {}
        except json.JSONDecodeError as exc:
            raise FreqtradeRuntimeError(
                "invalid_payload",
                f"Freqtrade runtime API returned invalid JSON for '{path}'.",
            ) from exc

    def _basic_auth_header(self) -> str:
        if not self.username or not self.password:
            raise FreqtradeRuntimeError(
                "bridge_misconfigured",
                "Freqtrade runtime bridge credentials are missing in control layer settings.",
            )
        token = base64.b64encode(f"{self.username}:{self.password}".encode("utf-8")).decode("ascii")
        return f"Basic {token}"

    def _translate_http_error(self, *, path: str, status: int, body: str) -> FreqtradeRuntimeError:
        if status == 401:
            return FreqtradeRuntimeError(
                "auth_failed",
                f"Freqtrade runtime API rejected the read-only bridge credentials for '{path}'.",
            )
        if status == 404:
            return FreqtradeRuntimeError(
                "endpoint_unavailable",
                f"Freqtrade runtime endpoint '{path}' is not available in this build.",
            )
        if status == 503:
            message = body.strip() or "Freqtrade runtime is not ready yet."
            return FreqtradeRuntimeError(
                "runtime_unavailable",
                f"Freqtrade runtime endpoint '{path}' is not ready: {message}",
            )
        return FreqtradeRuntimeError(
            "runtime_http_error",
            f"Freqtrade runtime endpoint '{path}' returned HTTP {status}.",
        )
