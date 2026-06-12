import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .routers import files, keys, meta, playground, projects, rag_v1

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    if settings.database_url:
        from .services.ingestion import fail_stale_jobs

        try:
            fail_stale_jobs()
        except Exception:
            logger.exception("Stale-job cleanup failed (is the database reachable?)")
    else:
        logger.warning("DATABASE_URL is not set — only /healthz will work")
    yield


app = FastAPI(title="Oreag API", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(projects.router)
app.include_router(files.router)
app.include_router(keys.router)
app.include_router(playground.router)
app.include_router(meta.router)
app.include_router(rag_v1.router)


@app.get("/healthz")
def healthz():
    return {"status": "ok"}
