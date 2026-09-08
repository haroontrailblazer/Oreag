#!/usr/bin/env python3
"""Regenerate backend/app/providers/prices.json from the upstream feed.

WHY A SNAPSHOT AT ALL

`providers/pricing.py` fetches the feed at runtime, but a process that has just
started has not fetched anything yet, and a deploy whose first fetch fails would
otherwise fall all the way back to the hand-written table. The snapshot is what
makes a cold start correct.

WHY IT IS TRIMMED

The upstream file is ~3800 entries and 2.3 MB. Committing that would make every
price change unreviewable - the diff nobody reads. This keeps only entries that
could ever match a model in CATALOG, under a vendor Oreag actually sells, which
is a small fraction and produces a diff a person can look at and judge.

    python scripts/refresh_prices.py           # rewrite the snapshot
    python scripts/refresh_prices.py --check   # exit 1 if it is out of date
"""
import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

SNAPSHOT = ROOT / "backend" / "app" / "providers" / "prices.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the snapshot is stale")
    args = ap.parse_args()

    import httpx

    from app.config import settings
    from app.providers import pricing
    from app.providers.registry import CATALOG

    wanted = set()
    for role in ("llm", "embedding"):
        for entries in CATALOG.get(role, {}).values():
            for entry in entries:
                model = entry if isinstance(entry, str) else entry["model"]
                wanted.add(model)
                wanted.add(model.split("/")[-1])

    print(f"fetching {settings.pricing_feed_url}")
    payload = httpx.get(settings.pricing_feed_url, timeout=90,
                        follow_redirects=True).json()
    print(f"  {len(payload)} entries upstream")

    if not pricing.is_usable(payload):
        print("REFUSED: the upstream payload did not validate. Snapshot unchanged.")
        return 1

    aliases = {a for names in pricing.PROVIDER_ALIASES.values() for a in names}
    trimmed = {
        key: entry for key, entry in payload.items()
        if isinstance(entry, dict)
        and entry.get("litellm_provider") in aliases
        and (key in wanted or key.split("/")[-1] in wanted
             or key.split("/", 1)[-1] in wanted)
    }
    print(f"  {len(trimmed)} entries relevant to this catalog")

    text = json.dumps(dict(sorted(trimmed.items())), indent=2) + "\n"
    if args.check:
        current = SNAPSHOT.read_text(encoding="utf-8") if SNAPSHOT.exists() else ""
        if current != text:
            print("STALE: run scripts/refresh_prices.py to update the snapshot.")
            return 1
        print("snapshot is current")
        return 0

    SNAPSHOT.write_text(text, encoding="utf-8")
    print(f"wrote {SNAPSHOT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
