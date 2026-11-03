"""Small, auditable Anthropic-compatible client (stdlib only).

Credentials are read only from environment variables and are never written to
the request/response logs. There are no automatic retries: an ambiguous network
failure might already have incurred a charge.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import threading
import time
from typing import Any
import urllib.error
import urllib.parse
import urllib.request
import uuid


class ProviderError(RuntimeError):
    """A deliberately sanitized API error, without headers or credentials."""

    def __init__(self, code: str, message: str, *, status: int | None = None):
        super().__init__(message)
        self.code = code
        self.status = status


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Even a same-host redirect can unexpectedly change the API resource.
        # In particular, never forward a bearer token to another host.
        return None


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (ValueError, TypeError):
        return 0


class Provider:
    def __init__(self, *, base_url: str, token: str, model: str,
                 log_dir: str | Path | None = None,
                 max_output_tokens: int = 1200, timeout: float = 60,
                 thinking: str = "disabled"):
        parsed = urllib.parse.urlsplit(base_url)
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment):
            raise ValueError("API base URL must be an HTTPS URL without credentials, query or fragment")
        if not token:
            raise ValueError("Missing ANTHROPIC_AUTH_TOKEN or ANTHROPIC_API_KEY")
        self.model = re.sub(r"\[[^\]]+\]$", "", model.strip())
        if not self.model:
            raise ValueError("Missing API model")
        self.base_url = base_url.rstrip("/")
        self.endpoint = (self.base_url + "/messages" if self.base_url.endswith("/v1")
                         else self.base_url + "/v1/messages")
        self._token = token
        self.max_output_tokens = int(max_output_tokens)
        self.timeout = float(timeout)
        if thinking not in ("enabled", "disabled"):
            raise ValueError("thinking must be enabled or disabled")
        self.thinking = thinking
        if self.max_output_tokens <= 0 or self.timeout <= 0:
            raise ValueError("Token limit and timeout must be positive")
        self.log_dir = Path(log_dir) if log_dir else None
        if self.log_dir:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._totals = {"attempts": 0, "successes": 0, "input_tokens": 0,
                        "output_tokens": 0, "cache_read_input_tokens": 0,
                        "failed_attempts_with_unknown_usage": 0}

    @classmethod
    def from_env(cls, model: str | None = None, log_dir: str | Path | None = None,
                 max_output_tokens: int = 1200, timeout: float = 60,
                 thinking: str = "disabled") -> "Provider":
        return cls(
            base_url=os.environ.get("ANTHROPIC_BASE_URL", "https://api.anthropic.com"),
            token=(os.environ.get("ANTHROPIC_AUTH_TOKEN")
                   or os.environ.get("ANTHROPIC_API_KEY", "")),
            model=(model or os.environ.get("ANTHROPIC_MODEL")
                   or os.environ.get("ANTHROPIC_DEFAULT_SONNET_MODEL", "")),
            log_dir=log_dir, max_output_tokens=max_output_tokens, timeout=timeout, thinking=thinking,
        )

    @property
    def totals(self) -> dict:
        with self._lock:
            return dict(self._totals)

    def _write_log(self, record: dict) -> None:
        if self.log_dir:
            path = self.log_dir / (record["local_request_id"] + ".json")
            path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def complete(self, system: str, prompt: str, max_tokens: int | None = None) -> dict:
        limit = self.max_output_tokens if max_tokens is None else int(max_tokens)
        if limit <= 0:
            raise ValueError("max_tokens must be positive")
        local_id = uuid.uuid4().hex
        start = time.perf_counter()
        payload = {
            "model": self.model, "max_tokens": limit,
            "temperature": 0.3, "thinking": {"type": self.thinking},
            "system": system, "messages": [{"role": "user", "content": prompt}],
        }
        # Do not add headers or the credential-bearing request object to logs.
        record = {"local_request_id": local_id, "model": self.model,
                  "system": system, "prompt": prompt, "requested_max_tokens": limit,
                  "temperature": 0.3, "thinking": self.thinking,
                  "temperature_effective": 1.0 if self.thinking == "enabled" and self.model.startswith("deepseek") else 0.3}
        request = urllib.request.Request(
            self.endpoint, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json",
                     "Authorization": "Bearer " + self._token,
                     "x-api-key": self._token,
                     "anthropic-version": "2023-06-01"},
        )
        with self._lock:
            self._totals["attempts"] += 1
        try:
            # A fresh opener per call avoids shared mutable HTTP state across threads.
            opener = urllib.request.build_opener(_NoRedirect())
            with opener.open(request, timeout=self.timeout) as response:
                raw = response.read()
                request_id = response.headers.get("request-id") or response.headers.get("x-request-id")
            try:
                data = json.loads(raw)
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise ProviderError("invalid_api_json", "API returned a non-JSON response") from exc
            if not isinstance(data, dict) or not isinstance(data.get("content"), list):
                raise ProviderError("invalid_api_response", "API response has no content list")
            usage = data.get("usage") or {}
            if not isinstance(usage, dict):
                raise ProviderError("invalid_api_usage", "API usage is not an object")
            # Anthropic and the compatible DeepSeek endpoint report cache hits
            # separately. Total model input must include all three categories.
            uncached = _nonnegative_int(usage.get("input_tokens"))
            cached = _nonnegative_int(usage.get("cache_read_input_tokens"))
            created = _nonnegative_int(usage.get("cache_creation_input_tokens"))
            text = "\n".join(block.get("text", "") for block in data["content"]
                             if isinstance(block, dict) and block.get("type") == "text"
                             and isinstance(block.get("text"), str))
            result = {
                "text": text, "input_tokens": uncached + cached + created,
                "uncached_input_tokens": uncached,
                "cache_read_input_tokens": cached,
                "cache_creation_input_tokens": created,
                "output_tokens": _nonnegative_int(usage.get("output_tokens")),
                "latency_s": time.perf_counter() - start,
                "model": data.get("model", self.model),
                "request_id": request_id or data.get("id"),
                "local_request_id": local_id, "stop_reason": data.get("stop_reason"),
                "requested_max_tokens": limit,
            }
            record.update(status="ok", result=result)
            with self._lock:
                self._totals["successes"] += 1
                for key in ("input_tokens", "output_tokens", "cache_read_input_tokens"):
                    self._totals[key] += result[key]
            self._write_log(record)
            return result
        except urllib.error.HTTPError as exc:
            # Do not echo a server-supplied body: it can contain a reflected
            # Authorization header, an account identifier, or other secrets.
            error = ProviderError("http_error", f"API returned HTTP {exc.code}; no retry attempted", status=exc.code)
        except ProviderError as exc:
            error = exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            error = ProviderError("network_error", f"API transport failed ({type(exc).__name__}); usage unknown")
        except Exception as exc:
            error = ProviderError("client_error", f"API client failed ({type(exc).__name__}); usage unknown")
        with self._lock:
            self._totals["failed_attempts_with_unknown_usage"] += 1
        record.update(status="error", error={"code": error.code,
                      "message": str(error), "http_status": error.status},
                      latency_s=time.perf_counter() - start, usage_unknown=True)
        self._write_log(record)
        raise error
