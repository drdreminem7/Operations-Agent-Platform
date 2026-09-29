import os

from fastapi import FastAPI

from .routes.health import router as health_router
from .routes.incidents import router as incidents_router

app_name = os.getenv("APP_NAME", "Operations Agent Platform")
app = FastAPI(title=app_name)
app.include_router(health_router)
app.include_router(incidents_router)
