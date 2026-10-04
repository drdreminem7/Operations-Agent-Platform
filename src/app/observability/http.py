from time import perf_counter

from fastapi import FastAPI, Request, Response
from opentelemetry import propagate, trace
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from starlette.middleware.base import RequestResponseEndpoint

from .metrics import http_request_duration_seconds, http_requests_total

tracer = trace.get_tracer(__name__)


def instrument_http(app: FastAPI) -> None:
    @app.middleware("http")
    async def observe_request(
        request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        context = propagate.extract(dict(request.headers))
        started = perf_counter()
        status = 500
        response: Response | None = None
        with tracer.start_as_current_span("http.request", context=context) as span:
            try:
                response = await call_next(request)
                status = response.status_code
                return response
            finally:
                route = request.scope.get("route")
                template = getattr(route, "path", "unmatched")
                span.update_name(f"{request.method} {template}")
                span.set_attribute("http.request.method", request.method)
                span.set_attribute("http.route", template)
                span.set_attribute("http.response.status_code", status)
                http_requests_total.labels(request.method, template, str(status)).inc()
                http_request_duration_seconds.labels(request.method, template).observe(
                    perf_counter() - started
                )
                if response is not None:
                    span_context = span.get_span_context()
                    response.headers["X-Trace-ID"] = format(
                        span_context.trace_id, "032x"
                    )


def metrics_response() -> Response:
    return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)
