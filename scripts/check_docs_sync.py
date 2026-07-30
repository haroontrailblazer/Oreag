#!/usr/bin/env python3
"""Documentation drift harness.

The code is the source of truth. This script extracts facts FROM the code and
asserts that every place we describe the system still agrees:

    surface            file
    ------------------------------------------------------------------
    architecture model  oreag_1.c4
    README              Readme.md
    flow doc            flow.md
    in-app docs page    frontend/src/app/docs/content.json
    in-app API tab      frontend/src/components/project/api-tab.tsx

Run it after ANY change to a flow, an endpoint, a tuning constant, a provider,
or an MCP tool:

    python scripts/check_docs_sync.py          # report drift, exit 1 if any
    python scripts/check_docs_sync.py --list   # just print the extracted facts

Every check names the file to edit, so a failure tells you exactly what to
update rather than just that something is stale.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

C4 = ROOT / "oreag_1.c4"
README = ROOT / "Readme.md"
FLOW = ROOT / "flow.md"
DOCS_JSON = ROOT / "frontend/src/app/docs/content.json"
API_TAB = ROOT / "frontend/src/components/project/api-tab.tsx"
CONFIG_PY = ROOT / "backend/app/config.py"
REGISTRY_PY = ROOT / "backend/app/providers/registry.py"
MCP_SERVER = ROOT / "mcp-server/oreag_mcp/server.py"
ROUTERS_DIR = ROOT / "backend/app/routers"
SERVICES_DIR = ROOT / "backend/app/services"
MIGRATIONS = ROOT / "supabase/migrations"


# ── findings ────────────────────────────────────────────────────────────────


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def fail(self, check: str, detail: str, fix_in: str) -> None:
        self.failures.append(f"[{check}] {detail}\n    -> update: {fix_in}")

    def note(self, msg: str) -> None:
        self.notes.append(msg)


def read(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8")


# ── fact extraction: the code is the truth ──────────────────────────────────


def settings_from_config() -> dict[str, object]:
    """Parse backend/app/config.py for Settings defaults (no import needed)."""
    tree = ast.parse(read(CONFIG_PY))
    out: dict[str, object] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.value is None:
                        continue
                    try:
                        out[stmt.target.id] = ast.literal_eval(stmt.value)
                    except (ValueError, SyntaxError):
                        pass
    return out


def provider_catalog() -> dict[str, set[str]]:
    """Provider ids in registry.CATALOG, split into keyed vs keyless."""
    src = read(REGISTRY_PY)
    tree = ast.parse(src)
    catalog: dict = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "CATALOG" and node.value is not None:
                try:
                    catalog = ast.literal_eval(node.value)
                except (ValueError, SyntaxError):
                    catalog = {}
    providers: set[str] = set()
    for section in ("embedding", "llm"):
        providers |= set(catalog.get(section, {}).keys())

    keyless = set()
    resolver = read(ROOT / "backend/app/providers/resolver.py")
    m = re.search(r"KEYLESS_PROVIDERS\s*=\s*\{([^}]*)\}", resolver)
    if m:
        keyless = set(re.findall(r'"([^"]+)"', m.group(1)))
    return {"all": providers, "keyless": keyless, "keyed": providers - keyless}


def mcp_tools() -> set[str]:
    """Tool names registered with @mcp.tool in the MCP server."""
    src = read(MCP_SERVER)
    tools: set[str] = set()
    tree = ast.parse(src) if src else None
    if tree is None:
        return tools
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for dec in node.decorator_list:
                target = dec.func if isinstance(dec, ast.Call) else dec
                if isinstance(target, ast.Attribute) and target.attr == "tool":
                    tools.add(node.name)
    return tools


def http_routes() -> set[tuple[str, str]]:
    """(METHOD, path) for every FastAPI route, by parsing the router files."""
    routes: set[tuple[str, str]] = set()
    for path in sorted(ROUTERS_DIR.glob("*.py")):
        src = read(path)
        tree = ast.parse(src)
        # router variable -> prefix
        prefixes: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
                fn = node.value.func
                if isinstance(fn, ast.Name) and fn.id == "APIRouter":
                    prefix = ""
                    for kw in node.value.keywords:
                        if kw.arg == "prefix":
                            try:
                                prefix = ast.literal_eval(kw.value)
                            except (ValueError, SyntaxError):
                                prefix = ""
                    for tgt in node.targets:
                        if isinstance(tgt, ast.Name):
                            prefixes[tgt.id] = prefix
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call):
                    continue
                fn = dec.func
                if not isinstance(fn, ast.Attribute):
                    continue
                method = fn.attr.upper()
                if method not in {"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD"}:
                    continue
                owner = fn.value
                prefix = prefixes.get(owner.id, "") if isinstance(owner, ast.Name) else ""
                if not dec.args:
                    continue
                try:
                    suffix = ast.literal_eval(dec.args[0])
                except (ValueError, SyntaxError):
                    continue
                routes.add((method, f"{prefix}{suffix}"))
    return routes


def service_modules() -> set[str]:
    return {
        p.stem
        for p in SERVICES_DIR.glob("*.py")
        if p.stem != "__init__"
    }


def migration_count() -> int:
    return len(list(MIGRATIONS.glob("*.sql")))


# ── checks ──────────────────────────────────────────────────────────────────


def check_public_endpoints_documented(rep: Report, routes: set[tuple[str, str]]) -> None:
    """Every public /v1 route must appear in the docs page and the C4 model."""
    docs = read(DOCS_JSON)
    c4 = read(C4)
    public = sorted({p for m, p in routes if p.startswith("/v1")})
    for path in public:
        # Compare on the tail after the project id, and treat {param},
        # <param> and :param as equivalent - prose and code spell them
        # differently but they are the same route.
        tail = path.split("}", 1)[-1] or "/"
        if not tail or tail == "/":
            continue
        pattern = re.escape(tail)
        pattern = re.sub(r"\\\{[a-z_]+\\\}", r"[<{:]?[a-z_\\-]+[>}]?", pattern)
        if not re.search(pattern, docs, re.I):
            rep.fail(
                "endpoints",
                f"public route {path} is not documented on the docs page",
                f"{DOCS_JSON.relative_to(ROOT)} (reference section)",
            )
        if not re.search(pattern, c4, re.I):
            rep.note(f"note: {path} is not named in the C4 model")


def check_tuning_constants(rep: Report, cfg: dict) -> None:
    """Numbers we quote in prose must match config.py."""
    docs = read(DOCS_JSON)
    c4 = read(C4)
    readme = read(README)

    def hours(seconds: int) -> int:
        return seconds // 3600

    checks = [
        # (label, expected string that MUST appear, where to look, surfaces)
        (
            "semantic cache threshold",
            str(cfg.get("semantic_cache_min_similarity", "")),
            [(docs, DOCS_JSON), (c4, C4)],
        ),
        (
            "L1 cache TTL hours",
            f"{hours(int(cfg.get('query_cache_ttl_seconds', 0)))} h",
            [(c4, C4)],
        ),
        (
            "L2 cache TTL hours",
            f"{hours(int(cfg.get('semantic_cache_ttl_seconds', 0)))} h",
            [(c4, C4)],
        ),
        (
            "std rate limit per key",
            str(cfg.get("query_rate_per_minute_per_key", "")),
            [(docs, DOCS_JSON)],
        ),
        (
            "heavy rate limit per key",
            str(cfg.get("heavy_rate_per_minute_per_key", "")),
            [(docs, DOCS_JSON)],
        ),
        (
            "max files per project",
            f"{int(cfg.get('max_files_per_project', 0)):,}",
            [(docs, DOCS_JSON)],
        ),
        (
            "max memories per project",
            f"{int(cfg.get('max_memories_per_project', 0)):,}",
            [(docs, DOCS_JSON)],
        ),
    ]
    for label, expected, surfaces in checks:
        if not expected or expected in ("0", "0 h"):
            continue
        for text, path in surfaces:
            if not text:
                continue
            plain = expected.replace(",", "")
            if expected not in text and plain not in text:
                rep.fail(
                    "constants",
                    f"{label} is {expected!r} in config.py but not stated there",
                    str(path.relative_to(ROOT)),
                )

    # the L2 TTL is the classic drift: prose often still says "1 hour"
    l2_hours = hours(int(cfg.get("semantic_cache_ttl_seconds", 0)))
    if l2_hours != 1 and re.search(r"semantic[^.]{0,120}?expire[^.]{0,40}?1 hour", docs, re.I):
        rep.fail(
            "constants",
            f"docs say the semantic cache expires after 1 hour, config says {l2_hours} h",
            str(DOCS_JSON.relative_to(ROOT)),
        )


def check_provider_counts(rep: Report, providers: dict) -> None:
    """"16 keyed providers" style claims must match the catalog."""
    keyed = len(providers["keyed"])
    keyless = len(providers["keyless"])
    for path in (README, C4, DOCS_JSON):
        text = read(path)
        if not text:
            continue
        for claimed in {int(n) for n in re.findall(r"(\d+)\s+keyed provider", text)}:
            if claimed != keyed:
                rep.fail(
                    "providers",
                    f"claims {claimed} keyed providers, catalog has {keyed}",
                    str(path.relative_to(ROOT)),
                )
        for claimed in {int(n) for n in re.findall(r"(\d+)\s+keyless", text)}:
            if claimed != keyless:
                rep.fail(
                    "providers",
                    f"claims {claimed} keyless providers, resolver has {keyless}",
                    str(path.relative_to(ROOT)),
                )


def check_mcp_tools(rep: Report, tools: set[str]) -> None:
    """Every registered MCP tool must be named wherever tools are listed."""
    n = len(tools)
    surfaces = [
        (DOCS_JSON, read(DOCS_JSON)),
        (C4, read(C4)),
        (FLOW, read(FLOW)),
        (ROOT / "mcp-server/README.md", read(ROOT / "mcp-server/README.md")),
    ]
    for path, text in surfaces:
        if not text:
            continue
        missing = sorted(t for t in tools if t not in text)
        if missing:
            rep.fail(
                "mcp-tools",
                f"{len(missing)} of {n} MCP tools never mentioned: {', '.join(missing)}",
                str(path.relative_to(ROOT)),
            )
        for claimed in {int(x) for x in re.findall(r"(?:The\s+)?(\d+)\s+tools", text)}:
            if claimed != n:
                rep.fail(
                    "mcp-tools",
                    f"claims {claimed} MCP tools, server registers {n}",
                    str(path.relative_to(ROOT)),
                )


def check_c4_covers_services(rep: Report, modules: set[str]) -> None:
    """Every service module should be represented in the architecture model.

    Mapping is by a loose name match, so ingest_queue -> ingestQueue counts.
    """
    c4 = read(C4).lower()
    # infrastructural helpers that are deliberately folded into another box
    folded = {
        "storage",          # part of the File Storage container
        "admin",            # one service-role call inside account deletion
        "query",            # the orchestrator, drawn as the routers + services it calls
        "query_cache",      # drawn as Answer Cache + Conversation Memory
        "semantic_cache",   # drawn as the L2 half of Answer Cache
        "usage",            # present as Usage Metering
    }
    missing = []
    for mod in sorted(modules):
        if mod in folded:
            continue
        squashed = mod.replace("_", "")
        if squashed not in c4:
            missing.append(mod)
    if missing:
        rep.fail(
            "c4-coverage",
            f"service modules with no component in the model: {', '.join(missing)}",
            str(C4.relative_to(ROOT)),
        )


def check_readme_freshness(rep: Report, n_migrations: int) -> None:
    readme = read(README)
    if not readme:
        return
    # migration range claim, e.g. "0001…0012" or "0001-0012"
    for hi in re.findall(r"00\d\d\s*[.…\-–]{1,3}\s*(00\d\d)", readme):
        if int(hi) != n_migrations:
            rep.fail(
                "readme",
                f"claims migrations up to {hi}, there are {n_migrations}",
                str(README.relative_to(ROOT)),
            )
    # files it points at must exist
    for ref in set(re.findall(r"\b([A-Za-z0-9_\-]+\.md)\b", readme)):
        if ref.lower() in {"readme.md", "flow.md"}:
            continue
        if not (ROOT / ref).exists() and not list(ROOT.glob(f"**/{ref}")):
            rep.fail(
                "readme",
                f"references {ref}, which does not exist in the repo",
                str(README.relative_to(ROOT)),
            )


def check_feature_surfaces(rep: Report) -> None:
    """Load-bearing features must be described on every surface that claims to
    describe the system. Keyed on a marker phrase per surface."""
    internal = {
        "C4 model": (C4, read(C4)),
        "README": (README, read(README)),
        "flow doc": (FLOW, read(FLOW)),
    }
    user_facing = {"docs page": (DOCS_JSON, read(DOCS_JSON))}

    # (feature, markers, also required on the user-facing docs page?)
    features = [
        ("streaming (SSE)", ["stream"], True),
        ("two-layer answer cache", ["l2", "semantic cache"], True),
        ("hybrid retrieval", ["hybrid", "rrf"], True),
        ("Matryoshka dimensions", ["matryoshka", "mrl"], True),
        ("rate limiting", ["rate limit", "429"], True),
        # operational internals: they belong in the architecture docs, but a
        # user of the API has no way to observe them.
        ("usage metering", ["usage_events", "usage metering", "metering"], False),
        ("ingestion queue", ["skip locked", "queue"], False),
        # Phase 3, structural scale. All three are invisible to an API caller -
        # same request, same response, same similarity values - so none of them
        # belongs on the user-facing docs page. They are load-bearing for anyone
        # reasoning about capacity, though, so the architecture surfaces must
        # keep describing them.
        ("approximate vector search", ["hnsw"], False),
        ("fleet-wide single-flight", ["single-flight", "single flight"], False),
        ("connection release / pooling", ["transaction pooler", "release_connection"], False),
    ]
    for feature, markers, needs_user_docs in features:
        surfaces = dict(internal)
        if needs_user_docs:
            surfaces.update(user_facing)
        for label, (path, text) in surfaces.items():
            if not text:
                continue
            low = text.lower()
            if not any(m in low for m in markers):
                rep.fail(
                    "feature-coverage",
                    f"{label} never mentions {feature}",
                    str(path.relative_to(ROOT)),
                )


def check_api_tab(rep: Report, cfg: dict) -> None:
    """The in-app API tab is a user-facing contract; keep it honest."""
    tab = read(API_TAB)
    if not tab:
        return
    if "query/stream" not in tab:
        rep.fail(
            "api-tab",
            "the streaming endpoint /query/stream is not shown in the API reference",
            str(API_TAB.relative_to(ROOT)),
        )
    if "cache_layer" not in tab:
        rep.fail(
            "api-tab",
            "the response example omits cache_layer / cache_similarity",
            str(API_TAB.relative_to(ROOT)),
        )
    expected = str(cfg.get("query_rate_per_minute_per_key", ""))
    if expected and expected not in tab:
        rep.fail(
            "api-tab",
            f"rate limit {expected}/min per key is not stated",
            str(API_TAB.relative_to(ROOT)),
        )


# ── entry point ─────────────────────────────────────────────────────────────


def run() -> Report:
    rep = Report()
    cfg = settings_from_config()
    providers = provider_catalog()
    tools = mcp_tools()
    routes = http_routes()
    modules = service_modules()
    n_migrations = migration_count()

    check_public_endpoints_documented(rep, routes)
    check_tuning_constants(rep, cfg)
    check_provider_counts(rep, providers)
    check_mcp_tools(rep, tools)
    check_c4_covers_services(rep, modules)
    check_readme_freshness(rep, n_migrations)
    check_feature_surfaces(rep)
    check_api_tab(rep, cfg)
    return rep


def print_facts() -> None:
    cfg = settings_from_config()
    providers = provider_catalog()
    routes = http_routes()
    print("Extracted from code (the source of truth)\n")
    print(f"  providers keyed   : {len(providers['keyed'])}")
    print(f"  providers keyless : {len(providers['keyless'])} "
          f"({', '.join(sorted(providers['keyless']))})")
    print(f"  MCP tools         : {len(mcp_tools())} "
          f"({', '.join(sorted(mcp_tools()))})")
    print(f"  HTTP routes       : {len(routes)} "
          f"({len([p for _, p in routes if p.startswith('/v1')])} public)")
    print(f"  service modules   : {len(service_modules())}")
    print(f"  migrations        : {migration_count()}")
    print("\n  tuning constants:")
    for key in sorted(
        k for k in cfg
        if any(t in k for t in ("cache", "rate", "max_", "agentic", "rag_", "explore", "ingest"))
    ):
        print(f"    {key:38} {cfg[key]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print extracted facts and exit")
    args = ap.parse_args()

    if args.list:
        print_facts()
        return 0

    rep = run()
    if rep.notes:
        print("Notes:")
        for n in rep.notes:
            print(f"  {n}")
        print()
    if not rep.failures:
        print("Docs are in sync with the code. "
              f"({len(http_routes())} routes, {len(mcp_tools())} MCP tools checked)")
        return 0
    print(f"Documentation drift: {len(rep.failures)} issue(s)\n")
    for f in rep.failures:
        print(f"  {f}\n")
    print("The code is the source of truth. Update the files named above.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
