import logging
import os

from fastapi import FastAPI

from .database import engine
from .observability.http import instrument_http, metrics_response
from .observability.metrics import configure_active_runs
from .observability.tracing import configure_tracing
from .routes.approvals import router as approvals_router
from .routes.health import router as health_router
from .routes.incidents import router as incidents_router
from .routes.runs import router as runs_router
from .security import install_api_key_auth

app_name = os.getenv("APP_NAME", "Operations Agent Platform")
logging.getLogger("app").setLevel(os.getenv("LOG_LEVEL", "INFO").upper())
app = FastAPI(title=app_name)
configure_tracing("operations-agent-api")
configure_active_runs(engine)
instrument_http(app)
install_api_key_auth(app)
app.add_api_route(
    "/metrics", metrics_response, methods=["GET"], include_in_schema=False
)
app.include_router(health_router)
app.include_router(incidents_router)
app.include_router(runs_router)
app.include_router(approvals_router)
