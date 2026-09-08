#!/usr/bin/env python3
"""Compare Oreag's pricing table against what Langfuse charged for the same calls.

WHY THIS EXISTS

`MODEL_PRICES_USD_PER_MTOK` in backend/app/providers/registry.py is hand-written
and dated. Vendors change prices, retire model ids and re-tier them, and nothing
in the codebase would notice: `usage_events.cost_usd` is computed at write time
from that table, so a stale entry produces invoices that are quietly, uniformly
wrong. There is no test that can catch it - the table IS the expected value.

Langfuse maintains its own model price table, and THAT is the second opinion.

READ THIS BEFORE TRUSTING A GREEN RUN. This script used to compare our cost
against `calculatedTotalCost` on each observation. That stopped being a second
opinion the moment services/tracing.py began sending `cost_details`: a supplied
cost takes precedence over Langfuse's own derivation, so `calculatedTotalCost`
became our own number handed back to us, and the drift arm compared our
arithmetic against itself - printing a clean bill forever, for a table whose
whole problem is that nothing else can check it.

The comparison is therefore made against Langfuse's PRICE TABLE - GET
/api/public/models - and the token counts it recorded, which is a number we did
not supply. Where that endpoint has no definition matching a model id, the model
is reported as having no independent price rather than skipped: an un-checkable
row must never read as a passing one.

WHAT THIS DOES NOT DO

It does not rewrite anything. `usage_events` stays the billing record and our
table stays the pricing authority - Langfuse's free tier keeps 30 days of data
and can be unreachable, neither of which is acceptable for an invoice. This
reports; a person decides.

USAGE

    python scripts/reconcile_pricing.py                # last 7 days
    python scripts/reconcile_pricing.py --days 30
    python scripts/reconcile_pricing.py --tolerance 0.02   # 2% before flagging
"""
import argparse
import pathlib
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load_env() -> None:
    env = ROOT / "backend" / ".env"
    if not env.exists():
        sys.exit(f"No {env}")
    import os

    for line in env.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def fetch_langfuse_prices(base: str, auth) -> list:
    """Langfuse's own managed + project model definitions, every page.

    This is the independent opinion the whole script rests on, so failing to
    read it is reported rather than degraded into a pass.
    """
    import httpx

    out: list = []
    try:
        with httpx.Client(base_url=base, auth=auth, timeout=60) as http:
            page = 1
            while page <= 20:
                resp = http.get(
                    "/api/public/models", params={"page": page, "limit": 100}
                )
                resp.raise_for_status()
                body = resp.json()
                out.extend(body.get("data", []))
                meta = body.get("meta") or {}
                if page >= int(meta.get("totalPages") or 1):
                    break
                page += 1
    except Exception as exc:  # noqa: BLE001 - this is a report, not a service
        print(f"  could not read Langfuse's model table: {exc}")
        return []
    return out


def match_langfuse_model(model: str, definitions: list):
    """(input, output) USD per 1M tokens from Langfuse's table, or None.

    Langfuse resolves a model by regex `matchPattern`, not equality, and several
    definitions can match one id - a project-scoped model overrides a managed
    one, and among equals the latest `startDate` wins. Mirrored here so the
    comparison uses the rates the Langfuse UI would show. None means Langfuse
    has no opinion, which is reported, never treated as agreement.
    """
    import re

    candidates = []
    for definition in definitions:
        try:
            if re.search(definition.get("matchPattern") or "", model):
                candidates.append(definition)
        except re.error:
            continue
    if not candidates:
        return None
    candidates.sort(
        key=lambda d: (not d.get("isLangfuseManaged"), d.get("startDate") or ""),
        reverse=True,
    )
    prices = candidates[0].get("prices") or {}

    def rate(key):
        value = prices.get(key)
        if isinstance(value, dict):
            value = value.get("price")
        return None if value is None else value * 1_000_000

    input_rate, output_rate = rate("input"), rate("output")
    if input_rate is None or output_rate is None:
        return None
    return input_rate, output_rate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="fractional difference tolerated before a model is flagged",
    )
    args = ap.parse_args()

    load_env()
    sys.path.insert(0, str(ROOT / "backend"))

    import os
    from datetime import datetime, timedelta, timezone

    import httpx

    from app.providers.base import TokenUsage
    from app.providers.registry import MODEL_PRICES_USD_PER_MTOK, cost_for

    base = os.environ.get("LANGFUSE_BASE_URL", "").rstrip("/")
    auth = (
        os.environ.get("LANGFUSE_PUBLIC_KEY", ""),
        os.environ.get("LANGFUSE_SECRET_KEY", ""),
    )
    if not base or not all(auth):
        sys.exit("Langfuse is not configured in backend/.env")

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)

    # Per model: what Langfuse charged, and the tokens it charged for. Summed
    # rather than compared per call, because a single generation rounds to six
    # decimal places and the rounding noise would swamp a real 1% drift.
    # `charged` is retained only to show how much of the window carried a cost
    # we supplied; it is NOT the comparison any more. See the docstring.
    charged: dict[str, float] = defaultdict(float)
    tokens: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    counted: dict[str, int] = defaultdict(int)

    print(f"Reading generations since {cutoff:%Y-%m-%d} ...")
    page = 1
    with httpx.Client(base_url=base, auth=auth, timeout=60) as http:
        while page <= 50:
            resp = http.get(
                "/api/public/observations",
                params={
                    "type": "GENERATION",
                    "fromStartTime": cutoff.isoformat(),
                    "page": page,
                    "limit": 100,
                },
            )
            if resp.status_code == 429:
                print("  rate limited; reporting on what was read so far")
                break
            resp.raise_for_status()
            batch = resp.json().get("data", [])
            if not batch:
                break
            for obs in batch:
                model = obs.get("model")
                cost = obs.get("calculatedTotalCost")
                usage = obs.get("usageDetails") or {}
                # Only generations Langfuse actually priced AND that carry the
                # token counts our own table needs. Anything else cannot be
                # compared, and guessing at the missing half is exactly the
                # failure mode this script exists to detect.
                if not model or cost is None:
                    continue
                prompt = usage.get("input")
                completion = usage.get("output")
                if prompt is None or completion is None:
                    continue
                charged[model] += float(cost)
                tokens[model][0] += int(prompt)
                tokens[model][1] += int(completion)
                counted[model] += 1
            if len(batch) < 100:
                break
            page += 1

    if not charged:
        print("No priced generations in this window - nothing to reconcile.")
        return 0

    langfuse_prices = fetch_langfuse_prices(base, auth)
    if not langfuse_prices:
        print("Could not read Langfuse's model table (GET /api/public/models) "
              "- there is no independent price to compare against, so nothing "
              "was reconciled.")
        return 1

    rows = []
    unmatched = []
    for model in sorted(charged):
        prompt, completion = tokens[model]
        ours = cost_for(model, TokenUsage(prompt, completion, model))
        rates = match_langfuse_model(model, langfuse_prices)
        if rates is None:
            unmatched.append(model)
            continue
        theirs = (prompt * rates[0] + completion * rates[1]) / 1_000_000
        rows.append((model, counted[model], ours, theirs))

    if not rows:
        print("Langfuse's table matched none of the models in this window, so "
              "there was nothing to compare.")
        for model in unmatched:
            print(f"  no Langfuse definition: {model}")
        return 1

    width = max(len(r[0]) for r in rows)
    print()
    print(f"{'model':{width}}  {'calls':>6}  {'ours':>12}  {'langfuse':>12}  diff")
    print("-" * (width + 46))

    problems = 0
    for model, calls, ours, theirs in rows:
        if ours is None:
            # We have no price at all. Not a mismatch - a gap, and a real one:
            # every call on this model writes NULL cost into usage_events.
            print(f"{model:{width}}  {calls:>6}  {'unpriced':>12}  "
                  f"{theirs:>12.6f}  <- NOT IN OUR TABLE")
            problems += 1
            continue
        if theirs == 0:
            continue
        drift = (ours - theirs) / theirs
        flag = ""
        if abs(drift) > args.tolerance:
            flag = "  <- DRIFT"
            problems += 1
        print(f"{model:{width}}  {calls:>6}  {ours:>12.6f}  {theirs:>12.6f}  "
              f"{drift:+7.1%}{flag}")

    print()
    if problems:
        print(f"{problems} model(s) need a look. Our table is in "
              f"backend/app/providers/registry.py "
              f"(MODEL_PRICES_USD_PER_MTOK), dated in its comments.")
        print("Nothing was changed - usage_events remains the billing record.")
    else:
        print(f"Every priced model agrees within {args.tolerance:.0%}.")

    if unmatched:
        print()
        print("No Langfuse price definition for: " + ", ".join(unmatched))
        print("These could NOT be checked - our figure for them is "
              "unverified, not agreed.")

    missing = sorted(set(charged) - set(MODEL_PRICES_USD_PER_MTOK))
    if missing:
        print(f"\nModels Langfuse priced that we do not: {', '.join(missing)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
