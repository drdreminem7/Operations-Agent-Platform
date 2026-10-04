import os
from collections.abc import Awaitable, Callable
from secrets import compare_digest

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse


def protected_path(path: str) -> bool:
    root = path.split("/", 2)[1] if path.startswith("/") else ""
    return root in {"incidents", "runs", "metrics"}


def install_api_key_auth(app: FastAPI) -> None:
    @app.middleware("http")
    async def require_api_key(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        configured = os.getenv("API_ACCESS_KEY")
        if configured and protected_path(request.url.path):
            supplied = request.headers.get("X-API-Key", "")
            if not compare_digest(supplied, configured):
                return JSONResponse(
                    status_code=401, content={"detail": "Invalid API key"}
                )
        return await call_next(request)
