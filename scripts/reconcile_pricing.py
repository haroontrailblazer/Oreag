#!/usr/bin/env python3
"""Compare Oreag's pricing table against what Langfuse charged for the same calls.

WHY THIS EXISTS

`MODEL_PRICES_USD_PER_MTOK` in backend/app/providers/registry.py is hand-written
and dated. Vendors change prices, retire model ids and re-tier them, and nothing
in the codebase would notice: `usage_events.cost_usd` is computed at write time
from that table, so a stale entry produces invoices that are quietly, uniformly
wrong. There is no test that can catch it - the table IS the expected value.

Langfuse prices the same generations independently, from a model table it
maintains. That makes it a genuine second opinion, and disagreement between the
two is the signal: either our price is stale, or theirs is, and a human should
look.

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

    rows = []
    for model in sorted(charged):
        prompt, completion = tokens[model]
        ours = cost_for(model, TokenUsage(prompt, completion, model))
        theirs = charged[model]
        rows.append((model, counted[model], ours, theirs))

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

    missing = sorted(set(charged) - set(MODEL_PRICES_USD_PER_MTOK))
    if missing:
        print(f"\nModels Langfuse priced that we do not: {', '.join(missing)}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
