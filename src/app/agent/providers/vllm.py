import ipaddress
import math
from time import perf_counter
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel

from ...observability.metrics import (
    model_call_duration_seconds,
    model_calls_total,
    model_errors_total,
    model_input_tokens_total,
    model_output_tokens_total,
)
from .errors import (
    ModelProviderError,
    ModelProviderResponseError,
    ModelProviderTimeoutError,
)
from .gemini import GeneratedContent


def _is_loopback(hostname: str | None) -> bool:
    if hostname == "localhost":
        return True
    if hostname is None:
        return False
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _token_count(value: object) -> int | None:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return None


class VLLMStructuredOutputGenerator:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str = "",
        timeout_seconds: float = 30,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("vLLM URL must be HTTP or HTTPS")
        if parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("vLLM URL cannot contain credentials or query data")
        if parsed.path.rstrip("/") != "/v1":
            raise ValueError("vLLM URL must end in /v1")
        if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
            raise ValueError("Remote vLLM requires HTTPS")
        if not _is_loopback(parsed.hostname) and not api_key.strip():
            raise ValueError("Remote vLLM requires an API key")
        if not model.strip():
            raise ValueError("vLLM model cannot be empty")
        if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
            raise ValueError("vLLM timeout must be a finite positive number")
        self._endpoint = base_url.rstrip("/") + "/chat/completions"
        self._model = model
        self._api_key = api_key
        self._timeout = timeout_seconds
        self._transport = transport

    async def generate(
        self,
        *,
        prompt: str,
        response_schema: type[BaseModel],
    ) -> GeneratedContent:
        started = perf_counter()
        model_calls_total.inc()
        headers = (
            {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        )
        body = {
            "model": self._model,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": response_schema.__name__,
                    "schema": response_schema.model_json_schema(),
                    "strict": True,
                },
            },
        }
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                transport=self._transport,
                trust_env=False,
            ) as client:
                response = await client.post(self._endpoint, json=body, headers=headers)
                response.raise_for_status()
            payload = response.json()
            if not isinstance(payload, dict):
                raise ModelProviderResponseError("vLLM returned an invalid response")
            choices = payload.get("choices")
            if not isinstance(choices, list) or not choices:
                raise ModelProviderResponseError("vLLM returned no choices")
            first = choices[0]
            if not isinstance(first, dict):
                raise ModelProviderResponseError("vLLM returned an invalid choice")
            message = first.get("message")
            if not isinstance(message, dict):
                raise ModelProviderResponseError("vLLM returned no message")
            content = message.get("content")
            if not isinstance(content, str) or not content.strip():
                raise ModelProviderResponseError("vLLM returned empty content")
            usage = payload.get("usage")
            usage = usage if isinstance(usage, dict) else {}
            input_tokens = _token_count(usage.get("prompt_tokens"))
            output_tokens = _token_count(usage.get("completion_tokens"))
            total_tokens = _token_count(usage.get("total_tokens"))
            if input_tokens is not None:
                model_input_tokens_total.inc(input_tokens)
            if output_tokens is not None:
                model_output_tokens_total.inc(output_tokens)
            reported_model = payload.get("model")
            actual_model = (
                reported_model if isinstance(reported_model, str) else self._model
            )
            return GeneratedContent(
                text=content,
                model=actual_model,
                latency_ms=int((perf_counter() - started) * 1000),
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                total_tokens=total_tokens,
            )
        except httpx.TimeoutException as error:
            model_errors_total.inc()
            raise ModelProviderTimeoutError("vLLM request timed out") from error
        except httpx.HTTPError as error:
            model_errors_total.inc()
            raise ModelProviderError("vLLM request failed") from error
        except ValueError as error:
            model_errors_total.inc()
            raise ModelProviderResponseError("vLLM returned malformed JSON") from error
        except ModelProviderError:
            model_errors_total.inc()
            raise
        finally:
            model_call_duration_seconds.observe(perf_counter() - started)
