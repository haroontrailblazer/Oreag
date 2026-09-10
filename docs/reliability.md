# Reliability and release operations

Apply `supabase/migrations/0047_operational_reliability.sql` before deploying this version. `scripts/verify_reliability_migration.py` checks its PostgreSQL behavior in a transaction that is always rolled back. The migration is additive and can be rerun.

## Evaluation retention

Creating the next run archives the oldest eligible finished run when 20 unarchived runs exist. Running/leased jobs and runs referenced by any run or schedule are protected. If every slot is active or protected, creation returns 409. Remove an unused reference or finish a job to make room. Archival and creation share the project lock.

Archived answers, configurations, feedback and metrics remain readable/exportable as compressed JSON. Frozen corpus and prepared vectors are released. Archived runs are read-only and cannot become references or resume. Choose **Archived** in Saved runs, or use `GET /v1/projects/{project_id}/evaluations/runs?archived=true&offset=0` (20 items per page). Explicit deletion still removes a run. Archives have no automatic expiry; review their growth under your data retention policy.

## Operations

Usage contains a collapsible Operations panel. Health shows a compact notice when operations need attention. `GET /api/account/operations` requires the owner's dashboard session and never accepts another owner ID.

Authenticated `/v1/` and `/api/projects/` requests enqueue timing/status metadata in memory, without writing to the database on the request path. No questions, answers, raw URLs or credentials enter this telemetry. The bounded queue holds 10,000 events per process and flushes in batches of 200. Process termination can lose buffered measurements; saturation drops new measurements and displays a warning. This is diagnostic telemetry, not a billing ledger.

Snapshots use at most the latest 5,000 requests in 24 hours. p95 is calculated over those samples; first-token p95 includes only observed nonempty SSE token events. Unknown values remain unmeasured. HTTP 4xx rejections are reported separately from HTTP 5xx, stream errors and detected disconnects. Normal disconnects that the ASGI server consumes without raising cannot be identified reliably. Failed unauthenticated requests cannot be attributed to an account.

Warnings inspect the latest 15 minutes (within that sample): at least 20 requests with >=5% failures/disconnects or p95 >10 seconds. Queue warnings use oldest creation time >5 minutes, including active processing time. Counts use database aggregates, scoped to owned projects. Shared worker or >=90% database pool pressure warnings expose availability only. They do not expose other accounts' data. Snapshots update in the background and dashboard reads refresh stale data.

`GET`/`HEAD /healthz` stays the cheap liveness endpoint. `GET`/`HEAD /readyz` returns 200 only while managed worker threads are alive and the last successful telemetry database write is less than 20 seconds old; otherwise 503. It does not probe external models or storage. Wire `/readyz` to readiness monitoring and keep `/healthz` for process liveness. Do not mistake a long provider call for a dead process.

Metrics and finished webhook delivery history use the configured log retention period (90 days by default). Worker heartbeats expire after one day. Idempotency records expire after 24 hours.

## Safe public retries

Optional `Idempotency-Key` supports only buffered query creation, multipart uploads and evaluation creation. Use 1–128 ASCII letters, numbers, `.`, `_`, `:`, or `-`. The server scopes hashed keys by API key and operation and hashes canonical request content; uploads include bytes, names, content types and order.

The first request claims a durable unique record before side effects. Completed responses are encrypted using the application encryption key and retained for 24 hours. An identical retry returns the original response with `Idempotency-Replayed: true`, without running the operation again. Authentication, revocation and suspension checks still apply. Different content returns 409. Pending or uncertain work returns 409 with `Retry-After: 5`; it is never automatically executed again during retention. After a lost/uncertain response, inspect the resource before using a new key. This is bounded replay protection, not a guarantee that an interrupted operation completed. A key can be reused after expiry, so never treat it as a permanent transaction ID.

Requests without the header keep their existing behavior. Streaming rejects the header with 422: restarting an interrupted stream may spend again. SDKs expose `idempotencyKey` (JavaScript) / `idempotency_key` (Python) for supported methods and never retry automatically. Rotate the application encryption key only with the existing encrypted-data migration procedure.

## Capacity and failure checks

`python scripts/load_fixture.py` runs synthetic local HTTP/SSE traffic at 10, 50 and 100 concurrent requests. It validates the harness and transport only. It does **not** establish application/database/provider throughput.

For a dedicated staging project, configure `OREAG_API_KEY` and `OREAG_PROJECT_ID`, then run:

```sh
python scripts/load_test.py --base-url https://your-staging-api.example --allow-remote --allow-paid-work --scenario query --concurrency 10,50,100 --requests 100 --output staging-query.json
```

Available scenarios: readiness, query, stream, upload and evaluation (`--suite suite.json`). Each stage has the requested number of requests, at most 500 concurrent and 10,000 per stage. The default repeated question measures a warm-cache workload; vary questions in separate runs to measure cold work. Upload and evaluation scenarios persist test records and may incur provider charges; use isolated test projects and remove test data after review. Evaluate accepted/failed/429 rates alongside p95 rather than treating throttling as throughput. Evaluation creation measures enqueue performance; use Operations and completed run timestamps to assess execution capacity. Default thresholds are >=99% success and p95 <=10 seconds; override explicitly for the staging service's SLO.

`test_reliability_postgres.py` uses an explicit disposable `RELIABILITY_DATABASE_URL` and a generated temporary schema to verify 12 simultaneous request claims have one winner, crash/reconnect replay, and expiry. Existing worker tests cover expired leases, ingestion retries and signed webhook failure/retry handling. `reliability.yml` runs these with pgvector PostgreSQL on PRs and each Monday. Fixtures never use backend credentials. Provider outage and real production capacity remain staging exercises; do not infer them from fixture measurements.

## Recovery verification

`scripts/recovery_drill.py` takes a consistent PostgreSQL snapshot of **auth and public data**, downloads original and converted Markdown objects, and checks known hashes. It creates a streaming authenticated encrypted backup with the separately stored `RECOVERY_BACKUP_KEY`. It decrypts the backup, restores to an empty matching target in one transaction, compares canonical fingerprints for every row, checks every file checksum and executes up to five vector retrieval probes. It refuses populated or mismatched targets and never deletes source data.

This is an application-data drill. Provision the target's matching schema, extensions, functions, roles and application migrations beforehand. Platform configuration, bucket configuration/policies, SMTP/OAuth secrets, encryption keys, logs and other database schemas need their own backup procedures. The drill verifies object bytes locally; it does not write them into a remote bucket or switch production traffic. Keep application workers and outgoing integrations disabled in the target. The database source and object storage are not one atomic snapshot: concurrent object deletion or an upload whose blob has not arrived causes a failed drill; retry in a quiet window.

Prerequisites: PostgreSQL clients at least as new as the source server, `psycopg[binary]`, SQLAlchemy, cryptography, httpx, and a dedicated target restore administrator able to disable triggers. Store these values in your secret manager:

- `SOURCE_DATABASE_URL`: read access to all auth/public tables and a direct/session connection that supports exported snapshots.
- `RECOVERY_TARGET_DATABASE_URL`: an **empty** compatible target, separate from production.
- `RECOVERY_TARGET_ACK=EMPTY_ISOLATED_TARGET`.
- `RECOVERY_BACKUP_KEY`: a generated Fernet key, stored separately from backup artifacts.
- `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `STORAGE_BUCKET` (defaults to `project-files`).

```sh
python scripts/recovery_drill.py --backup snapshot.oreag-backup --report recovery-report.json
python scripts/recovery_drill.py --backup snapshot.oreag-backup --restore-existing --report recovery-report.json
```

Both commands require a new empty target. For recurring runs, `--disposable-target` clones the empty template named by `RECOVERY_TARGET_DATABASE_URL`, verifies into a generated database, then removes only that generated database. This requires `CREATEDB`, connection to the target cluster's `postgres` database, and no other sessions on the empty template. It never modifies the template's rows. If verification fails, the encrypted backup remains for investigation and no successful report is generated. Plaintext staging files live in a temporary directory and are removed after the process exits normally; use an encrypted ephemeral runner disk.

The Monday workflow always performs a **synthetic** restore of metadata, multilingual file bytes and pgvector retrieval, including populated-target refusal. Actual-source drills are opt-in: configure the `recovery` GitHub environment secrets named in the workflow, provision the empty template, and set repository variable `ENABLE_RECOVERY_DRILL=true`. The target must support template database creation; a dedicated recovery PostgreSQL cluster is appropriate. Encrypted backups are kept for seven days in restricted GitHub artifacts; keep the key in a different secret store. A synthetic success is not evidence of a successful production restore. Define recovery-point/time objectives and measure an actual-source drill before relying on them.

## SDK releases

GitHub repository: `haroontrailblazer/Oreag`. The authenticated npm account is `haroontrailblazer`; JavaScript releases use its personal namespace. The PyPI account `haroontrailblazer` has verified email and two-factor authentication; the first Python release was published using a manually supplied token. Package names remain `@haroontrailblazer/oreag-sdk` and `oreag-sdk`. The `@oreag` organization was unavailable, so the JavaScript package uses the account-owned `@haroontrailblazer` scope. Both packages retain the repository's proprietary viewing-only license, as requested; publishing does not grant customers application-use rights.

JavaScript version 0.2.0 is published on [npm](https://www.npmjs.com/package/@haroontrailblazer/oreag-sdk): `npm install @haroontrailblazer/oreag-sdk`. Python version 0.2.0 is published on [PyPI](https://pypi.org/project/oreag-sdk/0.2.0/): `pip install oreag-sdk`. Both uploaded distribution hashes match the validated local artifacts. Version 0.2.0 adds idempotency options. `sdk-release.yml` verifies matching package versions/tag/changelogs, runs transport tests, builds and installs the actual wheel/tarball, checks metadata, and uploads reviewable artifacts. Manual dispatch defaults to build-only. Version 0.2.0 is already published on both registries; do not try to publish it again. For the next release, bump both package versions and changelogs, then tag `sdk-v<version>` or dispatch with publishing enabled after trusted-publisher setup. A successful npm job creates the GitHub release while automated PyPI publishing is disabled. Python distributions also remain attached downloads. Enable automated PyPI publishing with repository variable `ENABLE_PYPI_PUBLISHING=true` after configuring its trusted publisher; when enabled, both registry jobs must succeed. No registry success is claimed merely because a package builds.

Configure each registry's trusted publisher for owner `haroontrailblazer`, repository `Oreag`, workflow **sdk-release.yml**, environment **sdk-publishing**. npm requires ownership of the existing package/scope and a first-package setup if needed; PyPI supports a pending publisher for a new project. Keep publishing environment access restricted to release maintainers. The workflow uses short-lived OIDC credentials and does not contain registry tokens. See [npm's trusted publishing setup](https://docs.npmjs.com/trusted-publishers/) and [PyPI's publisher guide](https://docs.pypi.org/trusted-publishers/adding-a-publisher/).

The first JavaScript release was published using the authenticated npm account; the first Python release used a manually supplied PyPI token. Automated future releases still require each package's trusted-publisher configuration. The workflow's PyPI job remains disabled until explicitly configured. A GitHub username or account email alone does not grant registry access. If one registry succeeds and the other fails, rerun only the failed job after fixing access; do not overwrite a published version. Both registries' installation instructions were updated after successful publication. Revoke the temporary first-release PyPI token after verification; do not commit credentials.
