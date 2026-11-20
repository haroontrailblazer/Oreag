#!/usr/bin/env python3
"""Keep oreag.vercel.app pointed at whichever Render account still has free hours.

Two Render accounts run identical copies of the backend (same database, same
keys). Each account gets 750 free instance hours a month, so one of them runs
out mid-month and Render suspends every service in it. The rule:

    The first backend in OREAG_BACKENDS (Hexra) serves whenever it is up.
    The next one serves only while every backend before it is down.

.github/workflows/render-failover.yml runs this every 10 minutes. Each run
probes the backends in priority order and stops at the first one that answers,
so a standby account is never woken (and never burns hours) while the primary
serves. If the live frontend already points at that backend nothing happens.
Otherwise it sets NEXT_PUBLIC_API_BASE_URL on Vercel and redeploys production:
NEXT_PUBLIC_* values are inlined at build time, so a new build is the only way
to change where the browser sends requests.

The MCP connector does not depend on this job. The frontend route
/mcp/projects/<id>/mcp tries each account's MCP server on every request.

Environment:
    VERCEL_TOKEN     needed to switch; checking works without it
    VERCEL_TEAM      team slug or id (default: haroon-k-ms-projects)
    VERCEL_PROJECT   project name or id (default: oreag)
    APP_URL          live frontend (default: https://oreag.vercel.app)
    OREAG_BACKENDS   comma-separated, highest priority first
                     (default: Hexra's oreag.onrender.com, then oreag-tpsy)

Usage:
    python scripts/render_failover.py            # check and switch if needed
    python scripts/render_failover.py --dry-run  # check and report only
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_BACKENDS = "https://oreag.onrender.com,https://oreag-tpsy.onrender.com"
DEFAULT_APP_URL = "https://oreag.vercel.app"
DEFAULT_TEAM = "haroon-k-ms-projects"
DEFAULT_PROJECT = "oreag"
API_VAR = "NEXT_PUBLIC_API_BASE_URL"
VERCEL_API = "https://api.vercel.com"
USER_AGENT = "oreag-render-failover/1"

# A sleeping free instance takes up to about a minute to boot on the first
# request, so a probe has to wait that long before calling a backend down.
PROBE_TIMEOUT = 100.0
RETRY_DELAY = 30.0
BUSY_STATES = {"QUEUED", "INITIALIZING", "BUILDING"}


def log(message: str) -> None:
    print(message, flush=True)


def norm(url: str | None) -> str | None:
    return url.strip().rstrip("/") if url and url.strip() else None


def http(method, url, *, headers=None, body=None, timeout=30.0):
    """Return (status, lower-cased headers, text). HTTP errors are returned,
    not raised; network errors (OSError) propagate."""
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        url, data=data, method=method, headers={"User-Agent": USER_AGENT, **(headers or {})}
    )
    if data is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            status, raw_headers, raw = response.status, response.headers, response.read()
    except urllib.error.HTTPError as error:
        status, raw_headers, raw = error.code, error.headers, error.read()
    return status, {k.lower(): v for k, v in raw_headers.items()}, raw.decode("utf-8", "replace")


def probe(base: str, *, timeout: float = PROBE_TIMEOUT) -> str:
    """'up', 'suspended' (Render says the service is suspended), or 'down'."""
    try:
        status, headers, _ = http("GET", f"{base}/healthz", timeout=timeout)
    except (OSError, ValueError):
        return "down"
    if status == 200:
        return "up"
    if status == 503 and "suspend" in headers.get("x-render-routing", "").lower():
        return "suspended"
    return "down"


def pick_backend(backends, *, check=probe, sleep=time.sleep, retry_delay=RETRY_DELAY):
    """First backend in priority order that is up, or None.

    'suspended' is Render's own answer and final. 'down' gets one retry, so a
    blip or a slow boot does not flip production back and forth."""
    for base in backends:
        state = check(base)
        if state == "down":
            sleep(retry_delay)
            state = check(base)
        log(f"{base}: {state}")
        if state == "up":
            return base
    return None


def live_backend(app_url: str) -> str | None:
    """The backend the live frontend build talks to, from /api/active-backend.

    Read from the app because the Vercel variable is stored as sensitive and
    the API will not return its value."""
    try:
        status, _, text = http("GET", f"{app_url}/api/active-backend", timeout=30.0)
        if status == 200:
            return norm(json.loads(text).get("apiBase"))
    except (OSError, ValueError):
        pass
    return None


class Vercel:
    def __init__(self, token: str, team: str, project: str):
        self._token = token
        self._scope = {"teamId": team} if team.startswith("team_") else {"slug": team}
        self._project = project

    def _call(self, method, path, body=None, **params):
        query = urllib.parse.urlencode({**self._scope, **params})
        status, _, text = http(
            method,
            f"{VERCEL_API}{path}?{query}",
            headers={"Authorization": f"Bearer {self._token}"},
            body=body,
        )
        if status >= 300:
            raise RuntimeError(f"Vercel {method} {path} -> {status}: {text[:300]}")
        return json.loads(text) if text else {}

    def project(self) -> dict:
        return self._call("GET", f"/v9/projects/{urllib.parse.quote(self._project)}")

    def production_deployments(self, project_id: str) -> list[dict]:
        return self._call(
            "GET", "/v6/deployments", projectId=project_id, target="production", limit=10
        ).get("deployments", [])

    def set_production_env(self, project_id: str, key: str, value: str) -> None:
        self._call(
            "POST",
            f"/v10/projects/{project_id}/env",
            body={"key": key, "value": value, "type": "sensitive", "target": ["production"]},
            upsert="true",
        )

    def redeploy(self, name: str, deployment_id: str) -> dict:
        return self._call(
            "POST",
            "/v13/deployments",
            # Same request `vercel redeploy` sends; a rebuild reads current env.
            body={
                "name": name,
                "deploymentId": deployment_id,
                "target": "production",
                "meta": {"action": "redeploy"},
            },
            forceNew="1",
        )


def switch(vercel: Vercel, backend: str) -> None:
    project = vercel.project()
    deployments = vercel.production_deployments(project["id"])
    vercel.set_production_env(project["id"], API_VAR, backend)
    log(f"set {API_VAR}={backend} for production")

    # A build already under way may have read the old value. Leave it alone:
    # the next run compares the live build again and redeploys if it is wrong.
    if any(d.get("state") in BUSY_STATES for d in deployments):
        log("a production build is already running; the next run re-checks it")
        return
    ready = [d for d in deployments if d.get("state") == "READY"]
    if not ready:
        raise RuntimeError("no READY production deployment to redeploy")
    deployment = vercel.redeploy(project["name"], ready[0]["uid"])
    log(f"redeploying production: https://{deployment.get('url', '?')}")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--dry-run", action="store_true", help="report only, change nothing")
    args = parser.parse_args(argv)

    backends = [b for b in map(norm, os.environ.get("OREAG_BACKENDS", DEFAULT_BACKENDS).split(",")) if b]
    app_url = norm(os.environ.get("APP_URL")) or DEFAULT_APP_URL

    desired = pick_backend(backends)
    if desired is None:
        log("::error::no backend is up; leaving production unchanged")
        return 1

    current = live_backend(app_url)
    log(f"live frontend uses {current}; first healthy backend is {desired}")
    if current is None:
        # Never switch blind: an unreadable app would otherwise trigger a
        # redeploy on every run.
        log(f"::error::could not read {app_url}/api/active-backend; not switching")
        return 1
    if current == desired:
        log("no change")
        return 0
    if args.dry_run:
        log(f"dry run: would point production at {desired} and redeploy")
        return 0

    token = os.environ.get("VERCEL_TOKEN", "").strip()
    if not token:
        log("::error::VERCEL_TOKEN is not set; cannot switch")
        return 1
    switch(
        Vercel(
            token,
            os.environ.get("VERCEL_TEAM", "").strip() or DEFAULT_TEAM,
            os.environ.get("VERCEL_PROJECT", "").strip() or DEFAULT_PROJECT,
        ),
        desired,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
