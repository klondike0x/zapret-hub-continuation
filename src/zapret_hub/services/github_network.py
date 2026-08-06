from __future__ import annotations

import json
import ssl
import time
from pathlib import Path
from typing import Callable, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import certifi

from zapret_hub import __version__
from zapret_hub.services.logging_service import LoggingManager

T = TypeVar("T")


class GitHubRateLimitError(RuntimeError):
    pass


def is_github_rate_limit_error(error: BaseException) -> bool:
    if isinstance(error, GitHubRateLimitError):
        return True
    if isinstance(error, HTTPError):
        if error.code == 429:
            return True
        if error.code == 403:
            remaining = str(error.headers.get("X-RateLimit-Remaining", "") or "").strip()
            if remaining == "0":
                return True
    text = str(error).lower()
    return "rate limit" in text or "api rate limit exceeded" in text


def is_recoverable_github_error(error: BaseException) -> bool:
    if is_github_rate_limit_error(error):
        return False
    if isinstance(error, HTTPError):
        return error.code in {500, 502, 503, 504}
    if isinstance(error, (URLError, TimeoutError, OSError, ssl.SSLError)):
        return True
    text = str(error).lower()
    return any(marker in text for marker in ("timed out", "timeout", "temporary failure", "certificate"))


class GitHubNetworkClient:
    def __init__(
        self,
        logging: LoggingManager,
        *,
        recovery_runner: Callable[[Callable[[], T], str], T] | None = None,
    ) -> None:
        self.logging = logging
        self.recovery_runner = recovery_runner

    def github_json(self, url: str, *, timeout: int = 20, purpose: str = "github-json") -> object:
        return self._run(lambda: self._request_json(url, timeout=timeout), purpose)

    def github_bytes(self, url: str, *, timeout: int = 60, purpose: str = "github-download") -> bytes:
        return self._run(lambda: self._download_bytes_once(url, timeout=timeout), purpose)

    def github_download(
        self,
        url: str,
        destination: Path,
        *,
        timeout: int = 60,
        purpose: str = "github-download",
        min_bytes: int = 1,
    ) -> None:
        data = self.github_bytes(url, timeout=timeout, purpose=purpose)
        if len(data) < max(1, min_bytes):
            raise OSError("Downloaded archive is unexpectedly small")
        destination.write_bytes(data)

    def _run(self, operation: Callable[[], T], purpose: str) -> T:
        errors: list[str] = []
        for attempt in range(2):
            try:
                return operation()
            except Exception as error:
                errors.append(str(error))
                if is_github_rate_limit_error(error):
                    raise
                if not is_recoverable_github_error(error):
                    raise
                self.logging.log("warning", "GitHub request retry", purpose=purpose, attempt=attempt + 1, error=str(error))
                time.sleep(0.8)
        if self.recovery_runner is not None:
            try:
                return self.recovery_runner(operation, purpose)
            except Exception as error:
                errors.append(str(error))
                raise RuntimeError("; ".join(errors)) from error
        raise RuntimeError("; ".join(errors) or "GitHub request failed")

    def _request_json(self, url: str, *, timeout: int) -> object:
        payload = self._download_bytes_once(url, timeout=timeout)
        if not payload.strip():
            raise RuntimeError("GitHub returned an empty response.")
        text = payload.decode("utf-8", errors="replace").strip()
        try:
            return json.loads(text)
        except json.JSONDecodeError as error:
            preview = text[:120].replace("\r", " ").replace("\n", " ")
            raise RuntimeError(f"GitHub returned invalid JSON: {preview}") from error

    def _download_bytes_once(self, url: str, *, timeout: int) -> bytes:
        request = Request(url, headers={"User-Agent": f"ZapretHub/{__version__}"})
        errors: list[str] = []
        for label, context in self._ssl_context_chain():
            try:
                with urlopen(request, timeout=timeout, context=context) as response:
                    self.logging.log("info", "GitHub request succeeded", url=url, ssl_path=label)
                    return response.read()
            except HTTPError as error:
                if self._is_rate_limit_response(error):
                    raise GitHubRateLimitError(self._format_rate_limit_error(error)) from error
                raise
            except Exception as error:
                errors.append(f"{label}: {error}")
                if not self._is_certificate_error(error):
                    raise
                self.logging.log("warning", "GitHub certificate fallback", url=url, ssl_path=label, error=str(error))
        raise RuntimeError("; ".join(errors) or "GitHub request failed")

    def _ssl_context_chain(self) -> list[tuple[str, ssl.SSLContext]]:
        return [
            ("system", ssl.create_default_context()),
            ("certifi", ssl.create_default_context(cafile=certifi.where())),
        ]

    def _is_certificate_error(self, error: BaseException) -> bool:
        if isinstance(error, ssl.SSLCertVerificationError):
            return True
        if isinstance(error, URLError):
            reason = getattr(error, "reason", None)
            if isinstance(reason, ssl.SSLCertVerificationError):
                return True
            if isinstance(reason, ssl.SSLError) and "CERTIFICATE_VERIFY_FAILED" in str(reason).upper():
                return True
        return "CERTIFICATE_VERIFY_FAILED" in str(error).upper()

    def _is_rate_limit_response(self, error: HTTPError) -> bool:
        if error.code == 429:
            return True
        if error.code != 403:
            return False
        remaining = str(error.headers.get("X-RateLimit-Remaining", "") or "").strip()
        if remaining == "0":
            return True
        text = ""
        try:
            text = error.read(4096).decode("utf-8", errors="replace").lower()
        except Exception:
            text = ""
        return "rate limit" in text or "api rate limit exceeded" in text

    def _format_rate_limit_error(self, error: HTTPError) -> str:
        reset = str(error.headers.get("X-RateLimit-Reset", "") or "").strip()
        if reset.isdigit():
            try:
                wait_seconds = max(0, int(reset) - int(time.time()))
                minutes = max(1, int((wait_seconds + 59) / 60))
                return f"GitHub API rate limit exceeded. Try again in about {minutes} min."
            except ValueError:
                pass
        return "GitHub API rate limit exceeded. Please try again later."
