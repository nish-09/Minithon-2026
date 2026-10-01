import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from . import bootstrap
from .config import get_settings
from .db import SessionLocal, get_db
from .routers import admin, ai, auth, community, incidents, matching, relationships, requests, triage, users
from .security import user_from_token
from .services import orchestrator
from .services.realtime import hub

log = logging.getLogger("nexa")


def _sweep_once() -> None:
    db = SessionLocal()
    try:
        stats = orchestrator.process_timeouts(db)
        db.commit()
        if any(stats.values()):
            log.info("sweeper: %s", stats)
    except Exception:
        db.rollback()
        log.exception("sweeper failed")
    finally:
        db.close()


async def _sweeper(interval: int) -> None:
    while True:
        await asyncio.sleep(interval)
        await asyncio.to_thread(_sweep_once)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    if s.environment == "production" and s.jwt_secret.startswith("dev-only"):
        raise RuntimeError("NEXA_JWT_SECRET must be set in production")
    bootstrap.init_schema()
    with SessionLocal() as db:
        bootstrap.ensure_reference_data(db)
    hub.loop = asyncio.get_running_loop()
    task = asyncio.create_task(_sweeper(s.sweeper_interval_s)) if s.sweeper_interval_s > 0 else None
    yield
    if task:
        task.cancel()


def create_app() -> FastAPI:
    s = get_settings()
    app = FastAPI(title="NEXA API", version="1.0.0", lifespan=lifespan,
                  docs_url="/docs" if s.environment != "production" else None, redoc_url=None)
    app.add_middleware(CORSMiddleware, allow_origins=s.cors_list, allow_methods=["*"], allow_headers=["*"], allow_credentials=False)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError):
        errs = [{"field": ".".join(str(p) for p in e["loc"][1:]) or e["loc"][0], "message": e["msg"]} for e in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "Validation failed", "errors": errs})

    @app.exception_handler(Exception)
    async def unhandled(request: Request, exc: Exception):
        log.exception("unhandled error on %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Something went wrong on our side. Please try again."})

    for r in (auth.router, users.router, relationships.router, requests.router, matching.router, ai.router, incidents.router, triage.router,
              community.router, admin.router):
        app.include_router(r)

    @app.get("/api/health")
    def health(db: Session = Depends(get_db)):
        db.execute(text("SELECT 1"))
        return {"status": "ok", "llm_configured": bool(s.anthropic_api_key), "stt_configured": bool(s.stt_url)}

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket, token: str = ""):
        with SessionLocal() as db:
            user = user_from_token(db, token) if token else None
            uid = user.id if user else None
        if uid is None:
            await ws.close(code=4401)
            return
        await ws.accept()
        await hub.connect(uid, ws)
        await ws.send_json({"type": "hello", "user_id": uid})
        try:
            while True:
                msg = await ws.receive_text()
                if msg == "ping":
                    await ws.send_json({"type": "pong"})
        except WebSocketDisconnect:
            pass
        finally:
            hub.disconnect(uid, ws)

    return app


app = create_app()
