import logging
import re
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import TimeoutError as PoolTimeoutError

from .config import settings
from .routers import (
    account,
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
    # would stall everything behind them. Deliberately kept well above the DB
    # pool (now 10+10, sized to Supavisor's transaction-mode Pool Size): a
    # thread waiting on a provider has usually released its connection, and
    # when connections really do run out we want the fast PoolTimeoutError ->
    # 503 below, not requests silently queueing for a threadpool token.
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

# localhost / any private-LAN address, for local dev. Load-bearing: getApiBase()
# in frontend/src/lib/api.ts follows window.location.hostname, so opening the
# dashboard at http://192.168.1.50:3000 produces an Origin that CORS_ORIGINS
# does not list. Gated by cors_allow_local_network so production can drop it.
_LOCAL_ORIGIN = (
    r"http://(?:localhost|127\.0\.0\.1"
    r"|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3}"
    r"|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(?::\d{1,5})?"
)

# The middle segment of a Vercel-generated preview hostname: the branch slug
# ("git-my-branch") or a deployment hash. One hostname label, so dots cannot
# smuggle in another domain - but otherwise deliberately permissive, because
# constraining its SHAPE buys no security (see _preview_origin) while a Vercel
# change to the hash format would silently break every preview.
_PREVIEW_MIDDLE = r"[a-z0-9][a-z0-9-]{0,63}"


def _preview_origin(project: str, scope: str) -> str | None:
    """Vercel's auto-generated preview hostnames for ONE project in ONE scope.

    Vercel mints https://<project>-git-<branch>-<scope>.vercel.app and
    https://<project>-<hash>-<scope>.vercel.app. The stable production alias is
    NOT covered here - it belongs in CORS_ORIGINS as a literal.

    This is a SHAPE filter, not an ownership check, and the difference matters:
    *.vercel.app is one namespace shared with everybody, so anyone can register
    a free project called "oreag-attacker" under their own team and be served
    https://oreag-attacker-myteam.vercel.app - which matches this pattern, as
    tests/test_cors.py pins explicitly. No prefix/suffix pattern over a shared
    namespace can do better. What actually keeps that harmless is
    allow_credentials=False below (see the note there): it is the control, this
    is only a filter that keeps unrelated origins out.

    An empty project or scope emits no pattern at all, so the default is
    fail-closed. re.escape stops a value containing regex metacharacters from
    widening the pattern.
    """
    project, scope = project.strip(), scope.strip()
    if not project or not scope:
        return None
    return (
        r"https://"
        + re.escape(project)
        + r"-"
        + _PREVIEW_MIDDLE
        + r"-"
        + re.escape(scope)
        + r"\.vercel\.app"
    )


def build_origin_regex(project: str, scope: str, allow_local: bool) -> str | None:
    """Assemble the CORS origin regex, or None when nothing extra is allowed.

    A pure function of its arguments so it is unit-testable without building the
    app. Returning None rather than "" matters: an empty pattern fullmatches
    only the empty string, which is confusing dead config.
    """
    parts = [
        part
        for part in (
            _preview_origin(project, scope),
            _LOCAL_ORIGIN if allow_local else None,
        )
        if part
    ]
    if not parts:
        return None
    return "^(?:" + "|".join(parts) + ")$"


# allow_credentials=False is the ONLY thing making a mistakenly allowed origin
# harmless - the preview regex is a filter, not a control (see _preview_origin:
# any *.vercel.app tenant can register a project whose hostname satisfies it).
# Every frontend transport (api, apiStream and uploadWithProgress in
# frontend/src/lib/api.ts) authenticates with an "Authorization: Bearer"
# header; none sets credentials:"include" or withCredentials, and the backend
# reads no cookies at all (both auth paths are HTTPBearer). The Supabase
# session cookie lives on the frontend's own origin. So there is no ambient
# cross-origin credential to steal, and an allowed origin gains nothing a
# server-side curl does not already have. The previous "any *.vercel.app" regex
# combined with Access-Control-Allow-Credentials: true was what handed every
# attacker-deployed Vercel app a credentialed channel.
#
# Therefore: DO NOT set allow_credentials=True while a preview regex is in
# play. Adding cookie auth means enumerating preview origins in CORS_ORIGINS
# with VERCEL_PROJECT / VERCEL_SCOPE left empty (the fail-closed default), or
# moving previews to a custom domain - the only airtight options over a shared
# namespace. tests/test_cors.py enforces this pairing.
#
# assert_credentials_safe below turns that paragraph into an invariant the
# process cannot violate: a comment can be ignored by whoever adds cookie auth
# in six months, a refused boot cannot.


def assert_credentials_safe(allow_credentials: bool, preview_regex: str | None) -> None:
    """Refuse to run the one CORS combination that is actually exploitable.

    Credentials plus a *.vercel.app preview pattern is the dangerous pair, and
    only that pair: the pattern matches on hostname SHAPE, and *.vercel.app is
    a namespace shared with everyone, so any tenant can register a project
    whose production alias satisfies it (tests/test_cors.py pins a working
    example). With credentials off such an origin gains nothing over a plain
    server-side request. With credentials on it would get an authenticated
    channel into somebody else's account.

    Failing at import is deliberate. A warning would scroll past in Render's
    log and the service would keep serving the vulnerable combination; a hard
    failure is caught by the health check and the deploy rolls back.
    """
    if allow_credentials and preview_regex:
        raise RuntimeError(
            "Refusing to start: CORS_ALLOW_CREDENTIALS is on while a Vercel "
            "preview origin pattern is active (VERCEL_PROJECT / VERCEL_SCOPE). "
            "*.vercel.app is a shared namespace, so that pattern cannot prove "
            "ownership and this combination would expose an authenticated "
            "cross-origin channel. Either clear VERCEL_PROJECT/VERCEL_SCOPE and "
            "list preview origins explicitly in CORS_ORIGINS, or move previews "
            "to a custom domain, or leave CORS_ALLOW_CREDENTIALS off."
        )


_origin_regex = build_origin_regex(
    settings.vercel_project,
    settings.vercel_scope,
    settings.cors_allow_local_network,
)
_preview_regex = _preview_origin(settings.vercel_project, settings.vercel_scope)
assert_credentials_safe(settings.cors_allow_credentials, _preview_regex)

if _preview_regex:
    # Not a problem, but the operator should know the guarantee they have: this
    # keeps unrelated origins out, it does not prove the origin is theirs.
    logger.info(
        "CORS: Vercel preview origins enabled for project=%s scope=%s. This "
        "matches hostname shape only and cannot prove ownership; it is safe "
        "because credentials are disabled.",
        settings.vercel_project,
        settings.vercel_scope,
    )

app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
    allow_origin_regex=_origin_regex,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
    # Retry-After is part of the documented 429 contract (api-tab.tsx) but is
    # unreadable by cross-origin JS unless it is explicitly exposed.
    expose_headers=[h.strip() for h in settings.cors_expose_headers.split(",") if h.strip()],
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
