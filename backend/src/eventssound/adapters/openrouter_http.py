"""Shared OpenRouter HTTP core: bounded retries, size cap, error mapping, no secret leakage.

Everything raised is an `LlmError` subclass with a constant message. Provider bodies, URLs,
headers and the key are never copied into exceptions or logs; underlying httpx exceptions are
not chained (`from None`) because their text can carry hosts.
"""

import json
import logging
import random
import re
import time
from collections.abc import Callable, Mapping
from typing import Any, NamedTuple

import httpx

from eventssound.adapters.secret import Secret
from eventssound.application.llm import (
    LlmAuthError,
    LlmBadResponse,
    LlmError,
    LlmRateLimited,
    LlmTimeout,
    LlmUnavailable,
    LlmValidationError,
    is_finite_number,
)
from eventssound.domain.agent_config import MODEL_ID_PATTERN

DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
MAX_RETRY_AFTER_S = 5  # longest wait we accept before retrying
MAX_REPORTED_RETRY_AFTER_S = 86_400  # LlmRateLimited accepts 0..86400
_RETRYABLE_STATUS = frozenset({429, 502, 503, 504})
_BASE_URL = re.compile(r"https://[A-Za-z0-9.-]+(:[0-9]{1,5})?(/[A-Za-z0-9._~/-]*)?")
_DIGITS = re.compile(r"[0-9]{1,6}")

logger = logging.getLogger("eventssound.openrouter")


def check_model_id(value: object) -> str:
    if not isinstance(value, str) or not MODEL_ID_PATTERN.fullmatch(value):
        raise LlmValidationError("model must be a provider model id such as vendor/name")
    return value


def check_int(value: object, name: str, low: int, high: int) -> int:
    if type(value) is not int or not low <= value <= high:
        raise LlmValidationError(f"{name} must be an int within {low}..{high}")
    return value


def error_for_status(status: int, retry_after_s: int | None = None) -> LlmError:
    if status in (401, 403):
        return LlmAuthError()
    if status == 408:
        return LlmTimeout()
    if status == 429:
        return LlmRateLimited(retry_after_s)
    if status == 402 or 500 <= status <= 599:
        return LlmUnavailable()
    return LlmBadResponse()


class _Outcome(NamedTuple):
    data: dict[str, Any] | None = None
    error: LlmError | None = None
    retryable: bool = False
    retry_after: int | None = None


class OpenRouterHttp:
    def __init__(
        self,
        api_key: object,
        *,
        base_url: object = DEFAULT_BASE_URL,
        transport: httpx.BaseTransport | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        jitter: Callable[[], float] = random.random,
        max_retries: int = 2,
        backoff_base_s: float = 0.5,
        max_response_bytes: int = 1_000_000,
    ) -> None:
        self._key = Secret.wrap(api_key)
        if not isinstance(base_url, str) or not _BASE_URL.fullmatch(base_url):
            raise LlmValidationError("base_url must be a plain https URL")
        self._url = base_url.rstrip("/")
        self._max_retries = check_int(max_retries, "max_retries", 0, 5)
        self._max_bytes = check_int(max_response_bytes, "max_response_bytes", 1, 50_000_000)
        if not is_finite_number(backoff_base_s) or not 0 <= backoff_base_s <= 60:  # type: ignore[operator]
            raise LlmValidationError("backoff_base_s must be a number within 0..60")
        self._backoff = float(backoff_base_s)  # type: ignore[arg-type]
        self._sleep, self._clock, self._jitter = sleep, clock, jitter
        self._client = httpx.Client(transport=transport, follow_redirects=False)

    def now(self) -> float:
        return self._clock()

    def close(self) -> None:
        self._client.close()

    def post_json(
        self, path: str, payload: Mapping[str, Any], *, timeout_s: float, label: str, model: str
    ) -> dict[str, Any]:
        """POST `payload`; return the decoded JSON object of a 200 or raise an `LlmError`."""
        body = json.dumps(payload).encode()
        started = self._clock()
        deadline = started + timeout_s
        for attempt in range(self._max_retries + 1):
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise LlmTimeout()
            out = self._attempt(path, body, deadline, label, model, attempt)
            if out.data is not None:
                return out.data
            error = out.error
            assert error is not None
            wait_ok = out.retry_after is None or out.retry_after <= MAX_RETRY_AFTER_S
            if not out.retryable or attempt == self._max_retries or not wait_ok:
                raise error
            delay = (
                float(out.retry_after)
                if out.retry_after is not None
                else self._jitter() * self._backoff * 2**attempt
            )
            if self._clock() + delay >= deadline:
                raise error
            self._sleep(delay)
        raise LlmUnavailable()  # pragma: no cover - the loop always returns or raises

    def _attempt(
        self, path: str, body: bytes, deadline: float, label: str, model: str, attempt: int
    ) -> "_Outcome":
        began = self._clock()
        status_text = "error"
        try:
            status, retry_after, content = self._send(path, body, deadline)
            status_text = str(status)
            if status != 200:
                return _Outcome(
                    error=error_for_status(status, retry_after),
                    retryable=status in _RETRYABLE_STATUS,
                    retry_after=retry_after,
                )
            return _decode(content)
        except httpx.TimeoutException:
            status_text = "timeout"
            return _Outcome(error=LlmTimeout())
        except httpx.ConnectError:
            status_text = "connect_error"
            return _Outcome(error=LlmUnavailable(), retryable=True)
        except httpx.DecodingError:
            status_text = "decoding_error"
            return _Outcome(error=LlmBadResponse())
        except httpx.HTTPError:
            status_text = "transport_error"
            return _Outcome(error=LlmUnavailable())
        except LlmError as error:
            return _Outcome(error=error)
        finally:
            logger.info(
                "openrouter_call node=%s model=%s attempt=%d status=%s ms=%d",
                label,
                model,
                attempt + 1,
                status_text,
                int((self._clock() - began) * 1000),
            )

    def _send(self, path: str, body: bytes, deadline: float) -> tuple[int, int | None, bytes]:
        remaining = deadline - self._clock()
        if remaining <= 0:
            raise LlmTimeout()
        # The Authorization value is built inline, never bound to a name, so it cannot show up
        # in frame locals captured from a traceback. `identity` keeps the size cap on raw bytes.
        with self._client.stream(
            "POST",
            f"{self._url}{path}",
            headers={
                "Authorization": f"Bearer {self._key.get_secret_value()}",
                "Content-Type": "application/json",
                "Accept-Encoding": "identity",
                "X-Title": "EventSoundDR",
            },
            content=body,
            timeout=httpx.Timeout(
                connect=min(5.0, remaining),
                read=remaining,
                write=min(10.0, remaining),
                pool=min(5.0, remaining),
            ),
        ) as response:
            status = response.status_code
            retry_after = _retry_after(response.headers.get("retry-after"))
            if status != 200:
                return status, retry_after, b""  # error bodies are never read
            encoding = response.headers.get("content-encoding", "identity").strip().lower()
            declared = response.headers.get("content-length", "")
            if encoding not in ("", "identity") or (
                _DIGITS.fullmatch(declared) and int(declared) > self._max_bytes
            ):
                raise LlmBadResponse()
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > self._max_bytes:
                    raise LlmBadResponse()
                if self._clock() >= deadline:
                    raise LlmTimeout()
                chunks.append(chunk)
        return status, None, b"".join(chunks)


def _retry_after(value: str | None) -> int | None:
    if value is None or not _DIGITS.fullmatch(value.strip()):
        return None
    return min(int(value.strip()), MAX_REPORTED_RETRY_AFTER_S)


def _decode(content: bytes) -> "_Outcome":
    """Decode a 200 body; an `error` object inside it is mapped by its numeric code."""
    try:
        data = json.loads(content)
    except (ValueError, RecursionError):  # includes UnicodeDecodeError
        return _Outcome(error=LlmBadResponse())
    if type(data) is not dict:
        return _Outcome(error=LlmBadResponse())
    if data.get("error") is not None:
        embedded = data["error"]
        code = embedded.get("code") if isinstance(embedded, dict) else None
        if type(code) is int and 100 <= code <= 599:
            return _Outcome(error=error_for_status(code))
        return _Outcome(error=LlmUnavailable())
    return _Outcome(data=data)
