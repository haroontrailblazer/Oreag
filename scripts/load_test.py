"""Opt-in HTTP capacity probe. No production target or provider calls by default."""
import argparse
import asyncio
from collections import Counter
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse
import uuid

import httpx


def p95(values):
    if not values:
        return None
    ordered = sorted(values)
    return round(ordered[min(len(ordered)-1, int(.95*(len(ordered)-1)))], 2)


async def stage(client, base, project, scenario, count, concurrency, question, suite):
    semaphore = asyncio.Semaphore(concurrency)
    statuses, latency, tokens = Counter(), [], []
    async def request(index):
        async with semaphore:
            start = time.perf_counter()
            try:
                path = f"{base}/v1/projects/{project}"
                if scenario == "stream":
                    done, error = False, False
                    async with client.stream("POST", path+"/query/stream", json={"question": question}) as response:
                        status = str(response.status_code)
                        first = False
                        async for line in response.aiter_lines():
                            if not line.startswith("data:"):
                                continue
                            event = json.loads(line[5:])
                            if event.get("type") == "token" and event.get("text") and not first:
                                tokens.append((time.perf_counter()-start)*1000); first = True
                            done |= event.get("type") == "done"
                            error |= event.get("type") == "error"
                        if response.is_success and (error or not done): status = "stream_error"
                elif scenario == "upload":
                    response = await client.post(path+"/files", files={"uploads": (f"load-{uuid.uuid4()}.txt", b"Synthetic load test document.", "text/plain")}, headers={"Idempotency-Key": str(uuid.uuid4())})
                    status = str(response.status_code)
                elif scenario == "evaluation":
                    response = await client.post(path+"/evaluations/runs", json={"id":str(uuid.uuid4()), "suite":suite}, headers={"Idempotency-Key":str(uuid.uuid4())})
                    status = str(response.status_code)
                elif scenario == "readiness":
                    response = await client.get(base+"/readyz"); status = str(response.status_code)
                else:
                    response = await client.post(path+"/query", json={"question":question}, headers={"Idempotency-Key":str(uuid.uuid4())})
                    status = str(response.status_code)
                statuses[status] += 1
            except (httpx.HTTPError, ValueError):
                statuses["transport_error"] += 1
            finally:
                latency.append((time.perf_counter()-start)*1000)
    start = time.perf_counter()
    await asyncio.gather(*(request(i) for i in range(count)))
    elapsed = time.perf_counter()-start
    success = sum(v for k,v in statuses.items() if k.isdigit() and 200 <= int(k) < 300)
    return {"concurrency":concurrency,"requests":count,"seconds":round(elapsed,2),"requests_per_second":round(count/elapsed,2),
            "p95_latency_ms":p95(latency),"p95_first_token_ms":p95(tokens),"statuses":dict(statuses),"success_percent":round(100*success/count,2)}


async def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--scenario", choices=["readiness","query","stream","upload","evaluation"], default="readiness")
    parser.add_argument("--concurrency", default="10,50,100")
    parser.add_argument("--requests", type=int, default=100)
    parser.add_argument("--allow-remote", action="store_true", help="Explicitly target an authorized staging system")
    parser.add_argument("--allow-paid-work", action="store_true", help="Queries/uploads/evaluations can incur charges and persist records")
    parser.add_argument("--suite", type=Path)
    parser.add_argument("--question", default="What is the synthetic test policy?")
    parser.add_argument("--max-p95-ms", type=float, default=10000)
    parser.add_argument("--min-success-percent", type=float, default=99)
    parser.add_argument("--output", type=Path, default=Path("load-report.json"))
    args = parser.parse_args()
    target = urlparse(args.base_url)
    if target.scheme not in ("http","https") or not target.hostname or target.username or target.password or target.query or target.fragment:
        parser.error("Use an HTTP(S) base URL without credentials, query or fragment")
    if target.hostname not in ("localhost","127.0.0.1","::1") and not args.allow_remote:
        parser.error("Remote tests require --allow-remote and an authorized staging target")
    if target.hostname not in ("localhost","127.0.0.1","::1") and target.scheme != "https":
        parser.error("Remote targets require HTTPS")
    if args.scenario != "readiness" and (not args.allow_paid_work or not os.getenv("OREAG_API_KEY") or not os.getenv("OREAG_PROJECT_ID")):
        parser.error("This scenario needs --allow-paid-work, OREAG_API_KEY and OREAG_PROJECT_ID")
    levels = [int(x) for x in args.concurrency.split(",")]
    if not levels or any(n < 1 or n > 500 for n in levels) or not 1 <= args.requests <= 10000:
        parser.error("Concurrency must be 1..500 and requests 1..10000 per stage")
    if args.scenario == "evaluation" and not args.suite: parser.error("Evaluation requires --suite")
    suite = json.loads(args.suite.read_text(encoding="utf-8")) if args.suite else None
    headers = {"Authorization":"Bearer "+os.environ["OREAG_API_KEY"]} if args.scenario != "readiness" else {}
    async with httpx.AsyncClient(headers=headers, timeout=120, limits=httpx.Limits(max_connections=max(levels)), follow_redirects=False) as client:
        results = [await stage(client,args.base_url.rstrip("/"),os.getenv("OREAG_PROJECT_ID",""),args.scenario,args.requests,n,args.question,suite) for n in levels]
    passed = all(r["success_percent"] >= args.min_success_percent and r["p95_latency_ms"] <= args.max_p95_ms for r in results)
    report = {"scenario":args.scenario,"scope":"HTTP probe; fixture and readiness results do not establish provider or production capacity", "passed":passed,"stages":results}
    args.output.write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(report,indent=2))
    raise SystemExit(0 if passed else 1)


if __name__ == "__main__": asyncio.run(main())
