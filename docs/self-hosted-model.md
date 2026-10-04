# Self-hosted model adapter

`DECISION_PROVIDER=vllm` selects an HTTP adapter for a vLLM server's
OpenAI-compatible `/v1/chat/completions` endpoint. Configure
`VLLM_BASE_URL` (ending in `/v1`), `VLLM_MODEL`, optional local
`VLLM_API_KEY`, and `VLLM_TIMEOUT_SECONDS` in `.env`. The adapter requests a
JSON-schema response and feeds it through the same validated decision schemas,
evidence guard, policy, and approval workflow as the Gemini provider. It
records model name, latency, and token counts when the server returns usage.

The code rejects plain HTTP to non-loopback hosts and requires an API key for
remote HTTPS URLs. These are client-side guardrails, not server security. The
[vLLM server documentation](https://docs.vllm.ai/en/latest/serving/online_serving/openai_compatible_server/)
describes the chat-completions and structured-output interface. Its
[security guidance](https://docs.vllm.ai/en/latest/usage/security/) warns that
the server API key does not protect every endpoint; put a remotely exposed
server behind network access controls and an authenticated reverse proxy.

`tests/test_vllm_provider.py` uses a mocked HTTP transport to verify request
shape, schema validation, token metadata, timeout mapping, and unsafe URL
rejection. No GPU-backed vLLM process was started for this project, so the
adapter has not been live-tested against a selected open model. Time to first
token, tokens per second, GPU memory, structured-output success, end-to-end
agent quality, and cost cannot be reported honestly yet. Those measurements
require a named model, compatible GPU host, protected server endpoint, and a
run of the same reviewed evaluation set against both local and cloud providers.
