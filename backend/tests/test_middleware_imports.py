"""The Next.js middleware must not import a `"use client"` module.

WHY THIS EXISTS: it took production down and nothing caught it.

`src/proxy.ts` imported a helper from `src/lib/mfa.ts`, which carries a
`"use client"` directive. Next turns such a module into a CLIENT REFERENCE
PROXY on the server, so the import resolves fine and only *calling* the function
throws. The call sat inside the authenticated branch, so:

  * `npx tsc --noEmit`  - passed (types are real)
  * `npm run build`     - passed (the boundary is legal to import)
  * `/`, `/login`       - 200, because the branch never ran
  * every signed-in page - 500 Internal Server Error

That combination is the worst possible signature: every local check green, and
the failure only reachable once you are logged in.

The middleware also runs in the EDGE runtime, so the same walk catches Node-only
imports (`fs`, `path`, `crypto`) that would fail there for a different reason.
"""
import pathlib
import re

FRONTEND = pathlib.Path(__file__).resolve().parents[2] / "frontend"
SRC = FRONTEND / "src"
MIDDLEWARE = SRC / "proxy.ts"

# Bare specifiers that cannot run in the Edge runtime.
NODE_ONLY = {"fs", "path", "os", "child_process", "crypto", "net", "tls", "dns"}

_IMPORT_RE = re.compile(r'^\s*import\s[^"\']*["\']([^"\']+)["\']', re.MULTILINE)


def _resolve(spec: str, importer: pathlib.Path) -> pathlib.Path | None:
    """Local module for an import specifier, or None for a package."""
    if spec.startswith("@/"):
        base = SRC / spec[2:]
    elif spec.startswith("."):
        base = (importer.parent / spec).resolve()
    else:
        return None
    for candidate in (
        base.with_suffix(".ts"),
        base.with_suffix(".tsx"),
        base / "index.ts",
        base / "index.tsx",
    ):
        if candidate.is_file():
            return candidate
    return None


def _graph(entry: pathlib.Path) -> dict[pathlib.Path, list[str]]:
    """Every local module reachable from `entry`, plus its bare specifiers."""
    seen: dict[pathlib.Path, list[str]] = {}
    queue = [entry]
    while queue:
        current = queue.pop()
        if current in seen:
            continue
        source = current.read_text(encoding="utf-8")
        bare: list[str] = []
        for spec in _IMPORT_RE.findall(source):
            target = _resolve(spec, current)
            if target is None:
                bare.append(spec)
            else:
                queue.append(target)
        seen[current] = bare
    return seen


def test_the_middleware_exists():
    """Guards the guard: a renamed file would make everything below vacuous."""
    assert MIDDLEWARE.is_file(), f"no middleware at {MIDDLEWARE}"


def test_middleware_imports_no_client_modules():
    offenders = []
    for module in _graph(MIDDLEWARE):
        head = module.read_text(encoding="utf-8").lstrip()[:40]
        if head.startswith('"use client"') or head.startswith("'use client'"):
            offenders.append(str(module.relative_to(FRONTEND)))
    assert offenders == [], (
        'middleware reaches a "use client" module: '
        + ", ".join(sorted(offenders))
        + " - Next makes it a client reference proxy, so the import type-checks "
        "and builds, and only CALLING it throws (500 on signed-in pages only)"
    )


def test_middleware_imports_nothing_node_only():
    """The Edge runtime has no Node built-ins."""
    offenders = {}
    for module, bare in _graph(MIDDLEWARE).items():
        bad = [
            s
            for s in bare
            if s.split("/")[0].removeprefix("node:") in NODE_ONLY
        ]
        if bad:
            offenders[str(module.relative_to(FRONTEND))] = bad
    assert offenders == {}, f"Node-only imports in the edge bundle: {offenders}"


def test_the_scan_actually_walks_past_the_entry_file():
    """A resolver that silently returned None for everything would make both
    assertions above pass on any codebase."""
    reached = _graph(MIDDLEWARE)
    assert len(reached) > 1, "the import graph never left proxy.ts"
    assert any("lib" in str(m) for m in reached), "no lib/* module was resolved"
