"""Thin OpenAI-compatible chat client with an explicit error taxonomy.

The point of the taxonomy is that module D can show a sensible message and
module E can group failures, instead of everyone seeing a stack trace.
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import dataclass, field
from typing import Any, Callable

import requests

from .config import Config


class LLMError(Exception):
    """Base error. ``code`` is stable and safe to branch on."""

    code = "LLM_ERROR"
    retryable = False

    def __init__(self, message: str, *, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.status = status
        self.body = body[:500]


class AuthError(LLMError):
    code = "AUTH"


class BadRequestError(LLMError):
    code = "BAD_REQUEST"


class RateLimitError(LLMError):
    code = "RATE_LIMIT"
    retryable = True

    def __init__(self, message: str, *, retry_after: float | None = None, **kw: Any) -> None:
        super().__init__(message, **kw)
        self.retry_after = retry_after


class ServerError(LLMError):
    code = "SERVER"
    retryable = True


class NetworkError(LLMError):
    code = "NETWORK"
    retryable = True


class CallTimeout(LLMError):
    code = "TIMEOUT"
    retryable = True


class EmptyResponseError(LLMError):
    code = "EMPTY_RESPONSE"


class OutputLimitError(LLMError):
    code = "OUTPUT_LIMIT"


@dataclass
class LLMResponse:
    text: str
    model: str
    latency_ms: int
    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    finish_reason: str | None = None
    attempts: int = 1
    raw: dict = field(default_factory=dict)


class ChatClient:
    """One method: ``chat(messages)``. Retries transient failures with backoff."""

    def __init__(
        self,
        cfg: Config,
        session: requests.Session | None = None,
        transport: Callable[[dict], tuple[int, dict, str]] | None = None,
    ) -> None:
        self.cfg = cfg
        self._session = session or requests.Session()
        self._transport = transport
        self._json_mode_ok = cfg.json_mode

    # -- public ---------------------------------------------------------
    def chat(self, messages: list[dict], *, max_tokens: int | None = None) -> LLMResponse:
        if not self.cfg.api_key and self._transport is None:
            raise AuthError("no API key: set DEEPSEEK_API_KEY (or RECO_API_KEY)")
        attempt = 0
        last: LLMError | None = None
        while attempt <= self.cfg.max_retries:
            attempt += 1
            try:
                return self._call_once(messages, attempt, max_tokens)
            except RateLimitError as exc:
                last = exc
                if attempt > self.cfg.max_retries:
                    break
                self._sleep(exc.retry_after if exc.retry_after else self._backoff(attempt))
            except (ServerError, NetworkError, CallTimeout) as exc:
                last = exc
                if attempt > self.cfg.max_retries:
                    break
                self._sleep(self._backoff(attempt))
            except EmptyResponseError as exc:
                last = exc
                if attempt > self.cfg.max_retries:
                    break
                self._sleep(self._backoff(attempt))
        assert last is not None
        raise last

    # -- internals ------------------------------------------------------
    def _backoff(self, attempt: int) -> float:
        return min(8.0, 0.8 * (2 ** (attempt - 1))) + random.uniform(0, 0.3)

    @staticmethod
    def _sleep(seconds: float) -> None:
        time.sleep(min(seconds, 20.0))

    def _payload(self, messages: list[dict], max_tokens: int | None) -> dict:
        payload: dict[str, Any] = {
            "model": self.cfg.model,
            "messages": messages,
            "temperature": self.cfg.temperature,
            "max_tokens": max_tokens or self.cfg.max_tokens,
        }
        if self._json_mode_ok:
            payload["response_format"] = {"type": "json_object"}
        return payload

    def _call_once(self, messages: list[dict], attempt: int, max_tokens: int | None) -> LLMResponse:
        payload = self._payload(messages, max_tokens)
        started = time.perf_counter()
        status, headers, body = self._send(payload)

        # Some providers reject response_format; retry the same call without it.
        if status == 400 and self._json_mode_ok and _mentions_json_mode(body):
            self._json_mode_ok = False
            payload = self._payload(messages, max_tokens)
            started = time.perf_counter()
            status, headers, body = self._send(payload)

        latency_ms = int((time.perf_counter() - started) * 1000)
        self._raise_for_status(status, headers, body)

        try:
            data = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ServerError(f"response is not JSON: {exc}", status=status, body=body) from exc

        text = _extract_text(data)
        usage = data.get("usage") or {}
        choice = (data.get("choices") or [{}])[0]
        if choice.get("finish_reason") == "length":
            raise OutputLimitError(
                "The model reached its output limit. Increase RECO_MAX_TOKENS and retry.",
                status=status, body=body,
            )
        if not text.strip():
            raise EmptyResponseError(
                f"model returned empty content (finish_reason={choice.get('finish_reason')})",
                status=status,
                body=body,
            )
        return LLMResponse(
            text=text,
            model=data.get("model") or self.cfg.model,
            latency_ms=latency_ms,
            prompt_tokens=_as_int(usage.get("prompt_tokens")),
            completion_tokens=_as_int(usage.get("completion_tokens")),
            finish_reason=choice.get("finish_reason"),
            attempts=attempt,
            raw=data,
        )

    def _send(self, payload: dict) -> tuple[int, dict, str]:
        if self._transport is not None:
            return self._transport(payload)
        url = self.cfg.base_url.rstrip("/") + "/chat/completions"
        try:
            resp = self._session.post(
                url,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.cfg.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=(10, self.cfg.timeout_s),
            )
        except requests.exceptions.Timeout as exc:
            raise CallTimeout(f"request timed out after {self.cfg.timeout_s:.0f}s") from exc
        except requests.exceptions.ConnectionError as exc:
            raise NetworkError(f"cannot reach {url}: {exc}") from exc
        return resp.status_code, dict(resp.headers), resp.text

    @staticmethod
    def _raise_for_status(status: int, headers: dict, body: str) -> None:
        if 200 <= status < 300:
            return
        if status in (401, 403):
            raise AuthError(f"authentication failed ({status}): check the API key", status=status, body=body)
        if status == 429:
            retry_after = None
            try:
                retry_after = float(headers.get("Retry-After", "") or 0) or None
            except ValueError:
                retry_after = None
            raise RateLimitError("rate limited (429)", status=status, body=body, retry_after=retry_after)
        if status >= 500:
            raise ServerError(f"provider error ({status})", status=status, body=body)
        raise BadRequestError(f"request rejected ({status})", status=status, body=body)


def _mentions_json_mode(body: str) -> bool:
    low = body.lower()
    return "response_format" in low or "json_object" in low or "json mode" in low


def _extract_text(data: dict) -> str:
    choices = data.get("choices") or []
    if not choices:
        return ""
    content = (choices[0].get("message") or {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):  # some gateways return content parts
        parts = []
        for part in content:
            if isinstance(part, dict) and part.get("type") in {"text", "output_text"}:
                parts.append(str(part.get("text", "")))
            elif isinstance(part, str):
                parts.append(part)
        return "".join(parts)
    return ""


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
