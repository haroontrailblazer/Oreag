"""The documentation drift harness, wired into the test suite.

Docs rot silently. Running the harness as a test means a PR that changes an
endpoint, a tuning constant, a provider or an MCP tool fails until the
architecture model, README, flow doc, docs page and API tab are updated too.

Run just this check:

    pytest backend/tests/test_docs_sync.py -q
    python scripts/check_docs_sync.py        # same checks, friendlier output
"""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
HARNESS = ROOT / "scripts" / "check_docs_sync.py"


def _load():
    spec = importlib.util.spec_from_file_location("check_docs_sync", HARNESS)
    module = importlib.util.module_from_spec(spec)
    sys.modules["check_docs_sync"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def harness():
    if not HARNESS.exists():
        pytest.skip(f"harness not found at {HARNESS}")
    return _load()


def test_documentation_is_in_sync_with_the_code(harness):
    report = harness.run()
    if report.failures:
        detail = "\n\n".join(report.failures)
        pytest.fail(
            f"{len(report.failures)} documentation drift issue(s). "
            f"The code is the source of truth - update the files named below."
            f"\n\n{detail}",
            pytrace=False,
        )


def test_harness_can_extract_its_facts(harness):
    """A guard on the harness itself: if extraction silently returns nothing,
    every check would vacuously pass."""
    assert harness.settings_from_config(), "no settings parsed from config.py"
    assert harness.provider_catalog()["keyed"], "no keyed providers parsed"
    assert harness.mcp_tools(), "no MCP tools parsed"
    assert harness.http_routes(), "no HTTP routes parsed"
    assert harness.service_modules(), "no service modules found"
    assert harness.migration_count() > 0, "no migrations found"
