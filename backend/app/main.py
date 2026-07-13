import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from .config import settings
from .routers import (
    account,
    auth_methods,
    files,
    keys,
    memory,
    memory_graph,
    meta,
    playground,
    projects,
    provider_keys,
    rag_v1,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Every sync-def endpoint runs on this AnyIO threadpool (default 40 tokens).
    # LLM-bound requests hold a thread for seconds, so 40 in-flight queries
    # would stall everything behind them; raise the ceiling to match the DB
    # pool (10+30 connections) so threads aren't the first limit hit.
    import anyio.to_thread

    anyio.to_thread.current_default_thread_limiter().total_tokens = 100

    stop_workers = threading.Event()
    if settings.database_url:
        # Durable ingestion: worker threads claim pending files from the DB
        # queue. A restart loses nothing - pending rows are re-claimed at boot
        # and interrupted (leased) rows re-queue when their lease expires.
        # (Replaces the old fail_stale_jobs boot hook, which bulk-failed every
        # in-flight file platform-wide on each deploy.)
        from .services.ingest_queue import start_workers
        from .services.maintenance import maintenance_loop

        start_workers(stop_workers)
        threading.Thread(
            target=maintenance_loop,
            args=(stop_workers,),
            name="maintenance",
            daemon=True,
        ).start()
    else:
        logger.warning("DATABASE_URL is not set - only /healthz will work")
    yield
    stop_workers.set()


app = FastAPI(title="Oreag API", version="0.1.0", lifespan=lifespan)

# Explicit origins from config, plus a regex that covers:
#  (a) any Vercel deployment - the stable production domain AND the per-commit
#      preview URLs whose hostname changes on every deploy, and
#  (b) localhost / any private-LAN address for local dev.
_ALLOWED_ORIGIN_REGEX = (
    r"^(https://([a-z0-9-]+\.)*vercel\.app"
    r"|http://(localhost|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?)$"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=_ALLOWED_ORIGIN_REGEX,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# The engine fails DB-connection checkout fast (pool_timeout=5) under
# saturation; surface that as a deliberate "at capacity, retry" instead of an
# opaque 500 so well-behaved clients back off.
@app.exception_handler(PoolTimeoutError)
async def _pool_saturated(request, exc):
    return JSONResponse(
        status_code=503,
        content={"detail": "Server is at capacity - please retry shortly"},
        headers={"Retry-After": "2"},
    )


app.include_router(auth_methods.router)
app.include_router(projects.router)
app.include_router(files.router)
app.include_router(keys.router)
app.include_router(provider_keys.router)
app.include_router(account.router)
app.include_router(memory.public_router)
app.include_router(memory.owner_router)
app.include_router(memory_graph.owner_router)
app.include_router(playground.router)
app.include_router(meta.router)
app.include_router(rag_v1.router)
app.include_router(memory_graph.public_router)


# GET and HEAD: uptime monitors (e.g. UptimeRobot) default to HEAD, and FastAPI
# does not auto-add HEAD to a GET route - without this a HEAD probe gets a 405.
# async def is load-bearing: a sync def would queue behind busy threadpool
# threads, so saturation would fail Render's health check and restart the
# instance exactly when it's busiest.
@app.api_route("/healthz", methods=["GET", "HEAD"])
async def healthz():
    return {"status": "ok"}
