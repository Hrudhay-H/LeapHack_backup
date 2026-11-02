from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db
from .routes import admin_router, assisted_router, dev_router, farmer_router, verdict_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


LOCAL_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]


def cors_origins() -> list[str]:
    """Origins allowed to call the API from a browser.

    AGRISCOUT_CORS_ORIGINS is a comma-separated list (for example the Vercel site's URL). The local dev origins are
    always allowed. "*" allows any origin: acceptable only because auth is a bearer token sent in a header, never a cookie.
    """
    raw = os.environ.get("AGRISCOUT_CORS_ORIGINS", "").strip()
    if raw == "*":
        return ["*"]
    return [o.strip().rstrip("/") for o in raw.split(",") if o.strip()] + LOCAL_ORIGINS


app = FastAPI(title="AgriScout AI", version="0.1.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins(),
    # Optional regex, e.g. https://agriscout-.*\.vercel\.app to also allow Vercel preview deployments.
    allow_origin_regex=os.environ.get("AGRISCOUT_CORS_REGEX") or None,
    allow_methods=["*"],
    allow_headers=["*"],
)
for r in (farmer_router, verdict_router, assisted_router, admin_router, dev_router):
    app.include_router(r)


@app.get("/api/health")
def health():
    return {"ok": True}
