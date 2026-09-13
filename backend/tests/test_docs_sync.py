"""The documentation drift harness, wired into the test suite.

Docs rot silently. Running the harness as a test means a PR that changes an
endpoint, a tuning constant, a provider or an MCP tool fails until the
architecture model, README, flow doc, docs page and API tab are updated too.

Run just this check:

    pytest backend/tests/test_docs_sync.py -q
    python scripts/check_docs_sync.py        # same checks, friendlier output
"""
import importlib.util
import json
import re
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


def _replace_read(monkeypatch, harness, path, replacement):
    original = harness.read
    monkeypatch.setattr(
        harness, "read", lambda candidate: replacement if candidate == path else original(candidate)
    )


def test_feature_must_be_documented_in_its_own_guide(harness, monkeypatch):
    sections = json.loads(harness.read(harness.DOCS_JSON))
    for section in sections:
        if section["id"] == "usage-analytics":
            section["body"] = section["body"].replace("Why did spending change?", "Spending")
        elif section["id"] == "overview":
            section["body"] += "\nWhy did spending change?\n"
    _replace_read(monkeypatch, harness, harness.DOCS_JSON, json.dumps(sections))
    report = harness.Report()
    harness.check_dashboard_features(report)
    assert any("Spending-change insights is missing from its usage-analytics guide" in item for item in report.failures)


def test_diagram_mentions_do_not_replace_a_component(harness, monkeypatch):
    model = harness.read(harness.C4).replace(
        "spendingInsights = component",
        "// spendingInsights = component\n      renamedSpending = component",
    )
    _replace_read(monkeypatch, harness, harness.C4, model)
    report = harness.Report()
    harness.check_dashboard_features(report)
    assert any("has no spendingInsights component" in item for item in report.failures)


def test_diagram_component_needs_a_model_relationship(harness, monkeypatch):
    model = harness.read(harness.C4)
    model = "\n".join(
        "// " + line if "->" in line and re.search(r"\bsavedViews\b", line) else line
        for line in model.splitlines()
    )
    _replace_read(monkeypatch, harness, harness.C4, model)
    report = harness.Report()
    harness.check_dashboard_features(report)
    assert any("Saved views (savedViews) is disconnected" in item for item in report.failures)


def test_documented_navigation_must_match_sidebar_order(harness, monkeypatch):
    sections = json.loads(harness.read(harness.DOCS_JSON))
    dashboard = next(section for section in sections if section["id"] == "dashboard")
    rows = dashboard["body"].splitlines()
    nav_rows = [index for index, row in enumerate(rows) if re.match(r"\|\s*\*\*[^*]+\*\*\s*\|\s*`/", row)]
    assert len(nav_rows) >= 2
    first, second = nav_rows[:2]
    rows[first], rows[second] = rows[second], rows[first]
    dashboard["body"] = "\n".join(rows)
    _replace_read(monkeypatch, harness, harness.DOCS_JSON, json.dumps(sections))
    report = harness.Report()
    harness.check_dashboard_navigation(report)
    assert any("sidebar links/order differ" in item for item in report.failures)


def test_documentation_images_must_exist(harness, monkeypatch):
    sections = json.loads(harness.read(harness.DOCS_JSON))
    sections[0]["body"] += "\n![Missing screenshot](/docs/missing-audit-image.png)\n"
    _replace_read(monkeypatch, harness, harness.DOCS_JSON, json.dumps(sections))
    report = harness.Report()
    harness.check_documentation_images(report)
    assert any("missing image /docs/missing-audit-image.png" in item for item in report.failures)


@pytest.mark.parametrize("malformation", ["duplicate", "invalid-json"])
def test_invalid_documentation_structure_is_reported(harness, monkeypatch, malformation):
    sections = json.loads(harness.read(harness.DOCS_JSON))
    replacement = json.dumps(sections + [sections[0]]) if malformation == "duplicate" else "{"
    _replace_read(monkeypatch, harness, harness.DOCS_JSON, replacement)
    report = harness.Report()
    assert harness.documentation_sections(report) == {}
    assert any("[docs-structure]" in item for item in report.failures)


def test_documentation_file_names_work_on_case_sensitive_filesystems(harness):
    for path in (harness.C4, harness.README, harness.FLOW, harness.DOCS_JSON):
        assert path.name in {entry.name for entry in path.parent.iterdir()}
