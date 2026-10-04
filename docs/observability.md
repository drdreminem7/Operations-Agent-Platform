# Observability

The application emits three different kinds of evidence. PostgreSQL run steps are the durable audit trail. Structured logs describe what a process observed while running. Metrics summarize rates and durations. OpenTelemetry spans connect an HTTP request, agent step, policy decision, model call, tool call, and persistence operation; a background job carries the initiating request's `traceparent` through PostgreSQL to its worker.

## Run it locally

The API exposes Prometheus metrics at `GET /metrics`. Set `WORKER_METRICS_PORT=9001` in `.env` to expose worker metrics on `127.0.0.1:9001/metrics`. Start the API and worker as described in the README, then check both endpoints:

```bash
curl http://127.0.0.1:8000/metrics
curl http://127.0.0.1:9001/metrics
```

`ops/prometheus/prometheus.yml` scrapes both processes when Prometheus itself runs on the host. Import `ops/grafana/operations-agent.json` into Grafana with that Prometheus datasource to see active runs, completions/failures, p95 latency, model calls/tokens, tool failures, approvals, and policy denials. When Prometheus runs in a container, adjust scrape targets to addresses reachable *from that container*. Multiple worker processes need distinct metrics ports; the current code does not implement Prometheus multiprocess aggregation.

To export spans, set `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT` to the full HTTP traces endpoint of an OpenTelemetry collector, for example `http://127.0.0.1:4318/v1/traces`. When unset, spans still supply trace IDs to application logs and the `X-Trace-ID` response header, but are not sent to a tracing backend. The API and worker use different service names. A background run stores only the W3C `traceparent` value, not request headers, credentials, prompts, or model output. Manual steps and later approval requests have their own incoming HTTP context; `run_id` links those operations in logs and audit records. The approval wait is an event, not a span held open for minutes.

## What is measured

- Run creation, resolution/escalation, failure, terminal duration, and active-run count.
- Model calls, failures, duration, and available input/output tokens.
- Tool calls, failures, and duration by registered tool name.
- Approval requests/denials and policy denials.
- HTTP request counts and duration by method, route **template**, and status.

The API and worker have separate in-process counters. Scrape both and aggregate counters across jobs in Prometheus. `active_runs` queries PostgreSQL at scrape time and returns `NaN` if that query fails; it is not a counter and must not be summed across API and worker. The example dashboard uses `max(active_runs)`. Counters reset when a process restarts. Run and incident IDs, operator IDs, tool arguments, prompts, API keys, and raw URL paths are not metric labels. A metric label's possible values should remain small and predictable; per-run IDs would create a new time series for every run.

Application-owned log events are JSON lines with a timestamp, event, optional `run_id`, `incident_id`, `step_id`, `tool_name`, `model_name`, and active `trace_id`. Event fields are allowlisted. The model and tool boundaries log generic error types rather than exception messages or raw request/response bodies. Third-party library and server logs are outside that application log contract. Keep `/metrics` and any tracing collector on a trusted network; the local example does not add authentication to those endpoints.

Logs answer “what happened in this run?” Metrics answer “how often and how slowly is this happening across runs?” Traces answer “where did this request or job spend its time?” p50 is the median; p95 and p99 show slower tail behavior. Prometheus histogram quantiles are estimates over time windows, not exact per-request percentiles. Trace IDs let you correlate log lines with nested spans; IDs belong there, not in metric labels.

The current instrumentation is not a substitute for the persisted audit trail. Counters can lose increments on a crash, and a span export can fail even when a database transition committed. It also does not yet track model cost, evaluation quality, or real remote-service latency.

The implementation follows the [OpenTelemetry Python instrumentation guide](https://opentelemetry.io/docs/languages/python/instrumentation/) and the [Prometheus Python client instrumentation guide](https://prometheus.github.io/client_python/instrumenting/).
