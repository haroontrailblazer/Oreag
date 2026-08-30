# Document versioning — design spec

> **Amendment, agreed after synthesis (2026-08-30).** The design below gates
> extraction on a single fleet-wide setting, `version_extraction_enabled`.
> That is not enough: the extractor asks "is this a new edition of something
> already here?", a question that is just as true of `report_v2.pdf` as of an
> amending Act, so a global flag would park uploads in projects that have
> nothing to do with statutes. Version tracking is therefore **per project**:
>
> - `projects.version_tracking boolean not null default false`, added in the
>   same migration 0034.
> - The gate reads it alongside the global switch:
>   `settings.version_extraction_enabled and project.version_tracking and
>   file.document_id is None and file.indexed_at is None`. The global setting
>   stays, as a fleet-wide kill switch for incidents; the two are not
>   redundant.
> - A "Track document versions" switch in the project settings tab, which
>   **must** be added to the render-time three-way merge at
>   `settings-tab.tsx:114-176` — the Frontend section below says that block is
>   untouched, and that sentence is superseded by this amendment.
> - `PATCH /api/projects/{id}` accepts it and, correctly, does **not** bump
>   `content_version`: toggling changes nothing searchable.
> - **The requeue guards stay unconditional.** They key on `in_force_to`,
>   never on the toggle. Switching version tracking off must not resurrect
>   already-retired versions on the next model switch; it only stops new
>   uploads being parked. `POST /files/{id}/version` likewise stays reachable
>   with the toggle off, so a lineage can always be repaired afterwards.

# Five nullable columns on `files` make it its own version table: `in_force_to IS NOT NULL` means "superseded — every blob kept, zero chunks, never queued", so retrieval, explore and the byte-pinned SQL are not edited at all; a fifth `files.status` value `'review'` parks a suspected new version, and a single locked, one-commit `POST /files/{id}/version` is the only way in or out of it.

## Data model
## `C:/Projects/Oreag/supabase/migrations/0034_document_versions.sql` (the only migration)

No `create table` (so `test_migration_rls.py:47-64` is never engaged — `files` already has RLS from 0002 and new columns inherit it). No `%` character anywhere, comments included. No index. Every statement independently idempotent, because `backend/tests/apply_migrations.py:48-55` runs each file whole under autocommit and swallows only `DuplicateTable`/`DuplicateObject` **at file granularity** — one unguarded failure abandons everything after it in the same file.

```sql
-- Document versions: keep the history, index only what is in force.
--
-- WHY FIVE COLUMNS ON files AND NOT A documents TABLE
--
-- A "document" owns no data of its own. Its display name is the filename of
-- its current version; its label and dates live on the versions; every
-- consumer already keys on files.id - the ingest queue, the chunk cascade, the
-- Files tab, the storage paths. A table would add an empty row, an RLS policy,
-- a foreign key and a join to every file query in exchange for a name we
-- already have.
--
-- document_id is a plain GROUPING KEY, not a reference, and has no foreign key
-- on purpose: a lineage must outlive the deletion of any member including the
-- first, and either ON DELETE rule is wrong - SET NULL shatters the group into
-- singletons, CASCADE destroys the history this feature exists to keep.
-- Members whose original row was deleted still share the same (now dangling)
-- uuid, which is exactly the behaviour wanted. NULL document_id means "this
-- file is its own document", so nothing is backfilled and no existing row is
-- touched. The lineage key is coalesce(document_id, id), in SQL and in Python.
--
-- in_force_to IS THE INDEXABILITY SWITCH
--
-- A version with in_force_to set is superseded: it keeps its files row, its
-- source blob, its converted markdown blob, its conversion_version and all its
-- legal metadata, and it holds ZERO chunks. Nothing else decides this - in
-- particular legal_status does NOT, so there is exactly one authority and a
-- descriptive status edit can never silently drop a document out of the index.
--
-- THE INTERVAL IS HALF-OPEN: a version governs [in_force_from, in_force_to).
-- in_force_to is set only when a successor exists, and always to that
-- successor's in_force_from, so the two rows cannot disagree and chaining
-- needs no date arithmetic - which matters because this backend has no date
-- library at all. The API never accepts in_force_to as an input.
--
-- ROLLBACK REMEDY. This migration is never rolled back. If the BACKEND is
-- rolled back while superseded versions exist, the old requeue paths do not
-- know about them and the next model switch re-indexes retired law. Repair:
--   delete from public.chunks c using public.files f
--    where c.file_id = f.id and f.in_force_to is not null;
--   update public.files set chunk_count = 0 where in_force_to is not null;
--
-- SAFETY: additive and nullable. Every existing row reads NULL on all five,
-- which is precisely today's behaviour - one file, its own document, in force.

alter table public.files
  add column if not exists document_id uuid,
  add column if not exists version_label text,
  add column if not exists in_force_from date,
  add column if not exists in_force_to date,
  add column if not exists legal_status text;

-- Guarded CHECKs, copying 0032_answer_policy.sql. Both are trivially satisfied
-- today: every existing row is NULL on every new column, so neither can fail
-- the validating scan. Enforced in the database and not only in FastAPI for
-- the reason 0032 gives - a bad write from psql is still a bad write.
do $$
begin
  if not exists (
    select 1 from pg_constraint where conname = 'files_legal_status_known'
  ) then
    alter table public.files
      add constraint files_legal_status_known
      check (
        legal_status is null
        or legal_status in ('in_force', 'amended', 'repealed', 'draft', 'unknown')
      );
  end if;
  if not exists (
    select 1 from pg_constraint where conname = 'files_in_force_range'
  ) then
    alter table public.files
      add constraint files_in_force_range
      check (
        in_force_to is null
        or in_force_from is null
        or in_force_to >= in_force_from
      );
  end if;
end $$;

-- The invariant, written down and self-healing on every deploy. Matches zero
-- rows on first apply. It exists for the rollback window above: retrieval sums
-- files.chunk_count to size the ANN gate, and a superseded row still claiming
-- its old count inflates the project's apparent size.
update public.files set chunk_count = 0
 where in_force_to is not null and chunk_count <> 0;

comment on column public.files.document_id is
  'Grouping key for the editions of one document. NULL means this file is its own document; the lineage key is coalesce(document_id, id). Deliberately not a foreign key - a lineage must outlive the deletion of any member.';
comment on column public.files.version_label is
  'How this edition names itself, e.g. "Act 18 of 2013" or "Second Amendment 2019". Display only; it never reaches retrieval or the answer prompt.';
comment on column public.files.in_force_from is
  'Start of the half-open interval this edition governs. Required when superseding a predecessor, because the same value is written to that predecessor in_force_to.';
comment on column public.files.in_force_to is
  'End of the half-open interval, EXCLUSIVE. NOT NULL means superseded: the row keeps every blob and all metadata, holds zero chunks, and is never queued for indexing. The only authority on indexability.';
comment on column public.files.legal_status is
  'Descriptive only: in_force, amended, repealed, draft, unknown. Does NOT gate indexing - see in_force_to.';
```

**No index.** `files` is capped at 1000 rows per project (`config.py:148`, and `retrieval.py:232` relies on that as a fact); every version query is scoped by `project_id` and covered by `files_project_idx`. The lineage/review indexes are the reflexive addition, not an earned one.

**No CHECK on `files.status`.** There is none today, and `mark_file_failed` (ingestion.py:206-236) is the one function in the product designed never to raise — a constraint violation inside it aborts every queued ingest behind it.

## ORM: `C:/Projects/Oreag/backend/app/models.py`

`from datetime import date, datetime`; add `Date` to the sqlalchemy import block. Appended to `class File` after `indexed_at` (models.py:124), and the `status` inline comment at :102 becomes `# pending|processing|review|indexed|failed`:

```python
    # -- document versions (migration 0034) -------------------------------
    # Grouping key for the editions of one document. NULL = this file is its
    # own document, so nothing needed backfilling; the lineage key is
    # (document_id or id). NOT a ForeignKey on purpose - see the migration.
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    version_label: Mapped[str | None] = mapped_column(Text)
    in_force_from: Mapped[date | None] = mapped_column(Date)
    # NOT NULL means superseded: blobs, markdown and conversion_version all
    # kept, chunks dropped, chunk_count zeroed, never queued again. The single
    # authority on whether this file may be indexed - legal_status is not.
    in_force_to: Mapped[date | None] = mapped_column(Date)
    legal_status: Mapped[str | None] = mapped_column(Text)
```

Mapped **non-deferred**, like every other scalar on `File`. `deferred()` is reserved in this repo for the `Vector` archive columns (models.py:171, 241, 269); borrowing it to buy a deploy-ahead window would break the one convention and add a second SELECT to every File load. The consequence is the hard contract in the deploy order.

## Schemas: `C:/Projects/Oreag/backend/app/schemas.py`

`from datetime import date, datetime`. `FileOut` (schemas.py:118-135) gains five defaulted fields and still exposes no `storage_path`, `conversion_version` or `chunk_size`:

```python
    document_id: uuid.UUID | None = None
    version_label: str | None = None
    in_force_from: date | None = None
    in_force_to: date | None = None
    legal_status: str | None = None
```

```python
LEGAL_STATUSES = ("in_force", "amended", "repealed", "draft", "unknown")


class FileVersionRequest(BaseModel):
    """Publish this file as the current version of a document.

    One verb covers four operations: confirming a suspected new version,
    rejecting the suspicion, retiring an older upload by hand, and bringing a
    historical version back into force.

    Every field is REQUIRED and nullable. A partial-update shape would make
    `document_id: null` ambiguous between "make this standalone" and "do not
    change the lineage", and those are opposite operations.
    """

    document_id: uuid.UUID | None
    version_label: str | None = Field(max_length=200)
    in_force_from: date | None
    legal_status: str | None
    # The version this one replaces. Null = nothing is superseded.
    supersede_file_id: uuid.UUID | None

    @field_validator("legal_status")
    @classmethod
    def _known_status(cls, v):
        if v is not None and v not in LEGAL_STATUSES:
            raise ValueError(f"legal_status must be one of {LEGAL_STATUSES}")
        return v
```

There is deliberately **no `in_force_to` in the request**: it is derived, always, from the successor's `in_force_from`. That omission removes every way the two rows can disagree, and it is what makes the later as-of interval predicate valid on data captured today with no correction pass.

## Config: `C:/Projects/Oreag/backend/app/config.py`, near the ingest block (~line 184)

```python
    # Kill switch for the ingest-time version extractor (migration 0034).
    # DEFAULT FALSE. The backend deploy must be able to land before the
    # frontend that can render and confirm a review, so the switch is flipped
    # to True only after that frontend ships. False means every upload indexes
    # immediately, exactly as before 0034.
    #
    # Fleet-wide and not per-project on purpose: a per-project toggle needs a
    # projects column, a ProjectOut field and a fourth branch in the
    # settings-tab three-way merge that runs DURING RENDER (settings-tab.tsx
    # :114-176), and nobody has asked for one.
    version_extraction_enabled: bool = False
    # Head of the markdown sent to the extractor. Version and citation metadata
    # for a legal instrument lives in the title block; sending a whole statute
    # to a chat model on the user's own key is the invisible spend this repo
    # has already stamped out twice.
    version_extract_chars: int = 6000
```

`check_tuning_constants` (check_docs_sync.py:219) works from a hardcoded label list, so new settings fields are invisible to it. Zero CI cost.

### Decisions
- Five nullable columns on `files`, no `documents` table — a lineage owns no data of its own, and `document_id = file.id` on every standalone file gives the same 'file 2 has something to match against' property the table was wanted for, for free.
- No successor pointer and no FK of any kind on `document_id` — a FK forces a choice between SET NULL (shatters the lineage) and CASCADE (deletes the live successor when a 2019 version is deleted), and nothing in scope needs a chain that `document_id` plus the dates cannot answer.
- No index on `files` — capped at 1000 rows per project and every version query is already scoped by `project_id` under `files_project_idx`.
- Half-open `[in_force_from, in_force_to)` documented in the column comment — the parent's end date is set literally equal to the child's start date, so chaining needs no date arithmetic in a backend with no date library.
- The repair UPDATE ships in the migration — it matches zero rows on first apply but writes the ANN-gate invariant into schema history and re-heals it after a backend rollback, the one window nothing else covers.
- No CHECK on `files.status` — `mark_file_failed` is the one function designed never to raise, and a constraint violation inside it aborts every queued ingest behind it.

### Risks
- The five columns are mapped non-deferred, so every ORM load of a File names them: shipping the backend before the SQL breaks the Files tab, both upload routes, `claim_next`, reindex and delete. This is the incident at 0024_matryoshka_archive.sql:40-48 and the deploy order is the only defence.
- `document_id` having no FK means a lineage can outlive every member; a dangling uuid is invisible in the UI (the group simply has one row). Accepted deliberately — the alternative destroys history.

## State machine
## Two orthogonal axes, and neither is folded into the other

1. **`files.status`** — the indexing lifecycle. Gains exactly one value.
2. **`files.in_force_to`** — currency. A nullable date, not a status.

### `files.status`: `{pending, processing, indexed, failed, review}`

`'review'` means: *converted, markdown stored and stamped, extraction done, matched to an existing document, awaiting a human. Zero chunks. Not in any queue.*

A fifth value rather than reusing an existing one, because every reuse is a lie or a hazard: `'pending'` is claimable by `claim_next` (ingest_queue.py:114-121 matches `status == 'pending'` unconditionally, verified); `'indexed'` tells `/v1` and MCP pollers the upload succeeded while `chunk_count` is 0 and `indexed_at` is NULL, and `docs/content.json:40,45` documents `indexed` as "chunked, embedded, and searchable"; `'failed'` drags the project to `'error'`; `'processing'` is re-claimed on lease expiry. A new value is the only honest, inert option — and it is inert *by construction*: `claim_next` selects only `pending`, or `processing` with a lapsed lease, and `files_queue_idx` is `WHERE status IN ('pending','processing')` so a review row is not even in the index. **Neither needs an edit.**

The cost of a fifth value is exactly one thing — `FILE_STATUS[status]` at files-tab.tsx:168 is an unguarded object lookup immediately dereferenced (`config.icon`), over a four-key map, with **no error boundary anywhere in the frontend** (`find frontend/src -name error.tsx` and a grep for `ErrorBoundary` both return nothing), so an unknown key unmounts the whole project page. That is fixed at source (see Frontend) and belt-and-braced by the kill switch defaulting False. It is not a reason to corrupt `status`.

| Transition | Trigger | Where |
|---|---|---|
| (none) → `pending` | upload | files.py:~617 `File(...)`, rag_v1.py:370 |
| `pending` → `processing` | queue claim | ingest_queue.py, unchanged |
| `processing` → **`review`** | **NEW** — extraction matched an existing document | ingestion.py, new block after the conversion stamp |
| `processing` → `indexed` | no match, or a decision already recorded | ingestion.py:517 (guarded, see below) |
| `processing` → `failed` | any exception | mark_file_failed, unchanged |
| **`review`** → `pending` | human confirms or rejects | `POST /files/{id}/version` |
| `indexed` → `pending` | reindex / reembed / retry | files.py — **all three now skip `in_force_to IS NOT NULL`** |

The lease unwinds itself: parking sets `status='review'`, so `renew_lease` (scoped to `status='processing'`, ingest_queue.py:189) returns `False` on its next beat and the heartbeat thread returns. The park also sets `lease_expires_at = None` so an operator reading the row is not told a dead lease is live.

### `files.in_force_to`: currency

- `NULL` = in force. May hold chunks, may be queued. **At most one per lineage**, enforced by the endpoint (there are no unique constraints on `files` and this design adds none).
- `NOT NULL` = superseded. Keeps `storage_path`, `markdown_storage_path`, `conversion_version`, `page_count`, `size_bytes`, `embedding_tokens`, `indexed_at`, `version_label`, `in_force_from`, `legal_status`. Holds zero chunks, `chunk_count = 0`. Its `status` stays whatever it was, normally `'indexed'`.

No `'superseded'` status value: every operational exclusion must key on `in_force_to` anyway, because a superseded file can also be `'failed'`.

### A superseded predecessor is never left claimable — three layers

This is the one hole a `status`-agnostic currency column leaves, and it is closed three ways:

1. **The confirm 409s when the predecessor is `pending` or `processing`.** A pending row is claimable and the row lock only protects this transaction's window.
   ```python
   if predecessor.status in ("pending", "processing"):
       raise HTTPException(
           409,
           "The version being replaced is queued for indexing - wait for it to "
           "finish, then supersede it.",
       )
   ```
2. **`FOR UPDATE` on both rows** for the length of the transaction, so `claim_next`'s `with_for_update(skip_locked=True)` skips the predecessor while the confirm runs.
3. **`_file_still_current`** in the worker, for the case where a worker claimed the predecessor *before* the confirm took its lock (a claim commits immediately, so it holds no row lock during ingest). New helper in ingestion.py beside `_file_still_exists` (:199-203), which cannot see this because a superseded row is very much still there:
   ```python
   def _file_still_current(db: Session, file_id: uuid.UUID) -> bool:
       row = db.execute(select(File.in_force_to).where(File.id == file_id)).first()
       return row is not None and row[0] is None
   ```
   used immediately before ingestion.py:517:
   ```python
           if not _file_still_current(db, file.id):
               # Superseded mid-ingest. Leave the shape a superseded row must
               # have - zero chunks, chunk_count 0 - instead of writing
               # 'indexed' and putting a retired version back in the index.
               db.execute(sql_delete(Chunk).where(Chunk.file_id == file.id))
               file.chunk_count = 0
               recompute_project_status(db, project)
               bump_content_version(db, project.id)
               db.commit()
               logger.info("File %s superseded mid-ingest - chunks dropped", file_id)
               return
           file.status = "indexed"
   ```
   The bump is required because the batches this worker already committed (ingestion.py:514-515 commits per batch) became visible after the confirm's own bump.

Plus a belt-and-braces early return at the top of `_ingest_file_inner`, right after `db.get(File, file_id)` and **before** `file.status = "processing"`, so a stale claim writes nothing:
```python
        if file.in_force_to is not None:
            logger.info("File %s is a superseded version - not indexing", file_id)
            return
```

### `retry_file` (files.py:697-712) gains two 409s, making the version endpoint the only path out of `'review'`

```python
    if file.status == "review":
        raise HTTPException(
            409,
            "This file is waiting for a version decision - confirm or reject it "
            "in the Files tab before re-indexing.",
        )
    if file.in_force_to is not None:
        raise HTTPException(
            409,
            "This is a superseded version. Re-indexing it would put two versions "
            "of the same document in the index; make it current instead.",
        )
```

### `recompute_project_status` (ingestion.py:183-197) — one new arm

Today `'ready'` provably implies at least one indexed chunk: ingestion.py:447-448 raises `Document produced no chunks` *before* :517 ever runs, and the failure path yields `'error'`. Zeroing a superseded file's chunks creates a state that invariant has never permitted, and every representation of it (a new status value, or `indexed` plus a flag) falls into the final `else` and reports `'ready'` with nothing to answer from. Rewrite the read to carry the two extra columns in the same query — same round trip:

```python
def recompute_project_status(db: Session, project: Project) -> None:
    # the session runs with autoflush=False, so flush pending file status
    # changes/deletes first - otherwise this SELECT reads stale rows.
    db.flush()
    rows = db.execute(
        select(File.status, File.chunk_count, File.in_force_to).where(
            File.project_id == project.id
        )
    ).all()
    statuses = {r.status for r in rows}
    if not statuses:
        project.status = "empty"
    elif statuses & {"pending", "processing"}:
        project.status = "indexing"
    elif "failed" in statuses:
        project.status = "error"
    elif not any(r.in_force_to is None and r.chunk_count > 0 for r in rows):
        # Files exist but NOTHING is searchable - every one is parked in review
        # or superseded. "ready" has always implied at least one indexed chunk
        # (ingestion raises before reaching 'indexed' when a document produces
        # none), so reporting it here would tell /v1 and the dashboard that the
        # project can answer when it provably cannot. "empty" is the existing
        # value that already means "nothing to answer from", so this needs no
        # new project status, no ProjectOut field and no docs change.
        project.status = "empty"
    else:
        project.status = "ready"
```

A project with *some* indexed files and one review file still reports `'ready'`, which is true — the outstanding item is a human decision, not a machine one. The park path **must** call `recompute_project_status` before returning, or a project whose last file parks stays `'indexing'` forever (ingestion.py:354 set it and the normal exit at :520 is never reached).

### The exactly-once extraction gate

```
extraction runs  <=>  file.document_id IS NULL  AND  file.indexed_at IS NULL
```

Both conjuncts are load-bearing and neither is a new column:

- `indexed_at IS NULL` = "never successfully indexed". Verified: no requeue path clears it — files.py:641-658 (upload reembed), :866-872 (reindex), :706-711 (retry) and `mark_file_failed` (ingestion.py:206-236) all leave it alone. This is what stops a `CONVERSION_VERSION` bump — which re-converts the entire corpus — from re-opening a review on every already-confirmed file and taking a production index offline in one deploy.
- `document_id IS NULL` = "no version decision has ever been recorded". `_propose_version` **always** returns a non-null `document_id` (the file's own id when nothing matched) and the endpoint **always** writes one (the file's own id on reject), so the gate closes permanently on the first pass. Without it, confirm → `pending` → worker → extraction → `review` loops forever.

### Decisions
- A fifth `files.status` value `'review'` rather than reusing `'indexed'` — reusing it corrupts a documented public lifecycle field that /v1 and MCP consumers poll, while the crash risk a new value carries is a real frontend fragility that is worth fixing at source anyway.
- Currency lives on `in_force_to`, not on `status` — a superseded file can also be `'failed'`, so every operational exclusion has to key on the date column regardless.
- The confirm 409s on a `pending` predecessor rather than forcing its status — a queued predecessor is claimable and there is no honest status to move it to; refusing is one line and the case is rare.
- `recompute_project_status` reuses `'empty'` for 'files exist, nothing searchable' — it needs no fifth project status, no ProjectOut field, no docs/content.json edit and no C4 change, and it preserves the invariant that 'ready' means the project can answer.
- `_ingest_file_inner`'s early return sits before `file.status = 'processing'` so a stale claim writes nothing at all.

### Risks
- A project whose files are all in review now reports `'empty'` where it previously would have reported `'ready'`. That is the honest answer, but it is a visible change on the projects list and the sidebar for anyone who parks their whole corpus at once.
- `_file_still_current` costs one extra SELECT per successful ingest. Negligible against an embedding pass, but it is on the hot path.

## Extraction + matching
All of it lives in `C:/Projects/Oreag/backend/app/services/ingestion.py`. **No new `backend/app/services/*.py`** — a new service module fails `check_docs_sync.py:342-369 check_c4_covers_services` until `frontend/public/architecture.c4` grows a matching component (`versioning` is not in the hardcoded folded set), and extraction *is* a step of ingestion: it needs `File`, `Project`, `resolver`, `get_llm`, `embedding_usage` and `settings`, every one of which ingestion.py already imports. Bonus: `app.services.ingestion` is already in `TestNoUndefinedHelpers.MODULES` (test_units.py:2683), so every new `_helper` gets undefined-name coverage for free.

New imports: `json`, `re`, `from datetime import date`, `from typing import NamedTuple`, `from ..providers.base import call_llm`, `from ..providers.registry import get_llm`.

## Where it runs

Inserted into `_ingest_file_inner` **after** `file.conversion_version = CONVERSION_VERSION` (ingestion.py:~432) and **before** `chunk_size = file.chunk_size or project.chunk_size` (:434):

```python
        # -- document version gate (migration 0034) ----------------------
        #
        # Runs at most ONCE per file: only before its first successful index
        # (indexed_at is null) and only while it carries no version decision
        # (document_id is null). Both matter. Without the first, bumping
        # CONVERSION_VERSION re-converts the whole corpus and would re-examine
        # every indexed file; without the second, a file the user just
        # confirmed comes back through the queue and is parked again, forever.
        #
        # Placed AFTER the markdown upload and the conversion stamp so a park
        # commits a file whose blob is on disk and whose version is recorded -
        # the confirm then re-queues it and _reuse_converted_markdown serves
        # that blob, so conversion (which for images and audio is real money on
        # the user's own key) is never paid for twice.
        if file.document_id is None and file.indexed_at is None:
            proposal = _propose_version(db, file, project, converted.markdown)
            file.document_id = proposal.document_id  # never None - closes the gate
            file.version_label = proposal.version_label
            file.in_force_from = proposal.in_force_from
            file.legal_status = proposal.legal_status
            if proposal.document_id != file.id:
                # Suspected new version of something already held. Stop before
                # chunking: the predecessor keeps its chunks and stays
                # searchable until a human confirms, so the corpus is never
                # briefly empty on a guess.
                file.status = "review"
                file.lease_expires_at = None
                recompute_project_status(db, project)
                db.commit()
                logger.info("File %s parked for version review", file_id)
                return
```

This block touches no chunks, no `chunk_count` and no `bump_content_version` — parking changes nothing searchable, so there is nothing to invalidate. The early `return` is inside `_ingest_file_inner`, so `ingest_file`'s `finally` (ingestion.py:287-295) still runs `_record_ingest_usage`: a parked file still bills its conversion and its extraction, which is right, because both really happened.

## Shortlisting — a pure function, no database, no embedding call

```python
_VERSION_CANDIDATE_LIMIT = 12
_WORD_RE = re.compile(r"[a-z0-9]+")
_HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.M)
# Legal boilerplate. Without it every filename containing "Act" and "Rules"
# scores identically, which is most of a statutory corpus.
_VERSION_STOPWORDS = frozenset({
    "the", "of", "act", "and", "in", "to", "for", "a", "an", "no", "rules",
    "regulations", "amendment", "amended", "final", "copy", "draft", "version",
    "pdf", "docx", "doc", "scan", "scanned", "gazette", "notification",
    "order", "part", "chapter", "schedule",
})


def _tokens(text: str) -> set[str]:
    return {
        w for w in _WORD_RE.findall(text.lower())
        if len(w) > 1 and w not in _VERSION_STOPWORDS
    }


def _probe_text(filename: str, markdown: str) -> str:
    """What identifies an instrument: its filename plus its first heading.

    Scanned filings arrive as scan_0001.pdf and carry their identity only in
    the text, so the heading is pulled out EXPLICITLY rather than taking a raw
    prefix of the markdown, which is mostly gazette boilerplate.
    """
    heading = _HEADING_RE.search(markdown[:4000])
    return f"{filename} {heading.group(1) if heading else markdown[:200]}"


def _shortlist(candidates, probe: str, limit: int = _VERSION_CANDIDATE_LIMIT):
    """The `limit` candidates most likely to be the same instrument.

    Takes anything with .filename and .version_label, so it is unit-testable
    against a NamedTuple with no database - which is the only kind of test this
    CI can run. A project holding fewer than `limit` current documents sends
    all of them regardless of score.

    OVERLAP COEFFICIENT, not Jaccard. After stopwords, "Companies Act 2013" vs
    "Companies Amendment Act 2019" is {companies, 2013} vs {companies, 2019}:
    Jaccard scores that 0.33 and ranks it below noise; overlap scores it 0.5.
    Recall-oriented on purpose - the LLM is the precision filter and the human
    is the gate. No embedding search: that would spend the user's money on
    every upload, and chunk CONTENT is not what identifies an instrument.
    """
    if len(candidates) <= limit:
        return list(candidates)
    probe_tokens = _tokens(probe)
    if not probe_tokens:
        return sorted(candidates, key=lambda r: r.filename)[:limit]

    def score(row) -> float:
        cand = _tokens(f"{row.filename} {row.version_label or ''}")
        if not cand:
            return 0.0
        return len(probe_tokens & cand) / min(len(probe_tokens), len(cand))

    return sorted(candidates, key=lambda r: (-score(r), r.filename))[:limit]
```

No cycle guard: the lineage is a flat grouping key (`coalesce(document_id, id)`) with no successor pointer, so there is no chain to walk and no ring to build.

## The prompt

```python
_VERSION_SYSTEM_PROMPT = (
    "You identify legal and regulatory documents. You are given the opening of "
    "a new document and a numbered list of documents already held. Reply with "
    "ONE JSON object and nothing else:\n"
    '{"match": <list number, or null>, "version_label": <string or null>, '
    '"in_force_from": <"YYYY-MM-DD" or null>, '
    '"legal_status": "in_force"|"amended"|"repealed"|"draft"|"unknown"}\n'
    "Set match ONLY when the new document is a later version, amendment, "
    "reprint or consolidation of that same instrument - same jurisdiction, "
    "same title, same subject. A different instrument that merely cites it is "
    "NOT a match, and neither is a different chapter, schedule or part of it. "
    "When you are not sure, use null.\n"
    "version_label is how this edition names itself, for example 'Act 18 of "
    "2013', 'Second Amendment 2019', 'Reprint No. 4'. in_force_from is the "
    "date this edition takes effect, not the date it was printed, gazetted or "
    "assented to. Use null for anything the document does not state."
)
```

## The pass — never raises

```python
class VersionProposal(NamedTuple):
    document_id: uuid.UUID       # NEVER None - the file's own id when standalone
    version_label: str | None
    in_force_from: date | None
    legal_status: str | None


def _propose_version(db, file, project, markdown: str) -> VersionProposal:
    """What this file is a version of, if anything. NEVER raises.

    document_id is ALWAYS set on the way out - the file's own id when nothing
    matched. That is what makes extraction exactly-once: the caller writes it,
    and the gate (`document_id is None`) closes permanently.
    """
    standalone = VersionProposal(file.id, None, None, None)
    if not settings.version_extraction_enabled:
        return standalone
    try:
        candidates = db.execute(
            select(
                File.id, File.document_id, File.filename,
                File.version_label, File.in_force_from,
            ).where(
                File.project_id == file.project_id,
                File.id != file.id,
                # One row per lineage: the endpoint keeps at most one file per
                # lineage with a null in_force_to.
                File.in_force_to.is_(None),
                # An unconfirmed proposal is not something to be a version of.
                File.status != "review",
            )
        ).all()
        if not candidates:
            return standalone          # nothing to match against - NO LLM call
        shortlist = _shortlist(
            candidates, _probe_text(file.filename, markdown)
        )
        llm = get_llm(
            project.llm_provider,
            project.llm_model,
            resolver.resolve_llm_key(db, project),
        )
        listing = "\n".join(
            f"[{i + 1}] {r.filename} | {r.version_label or '-'} | "
            f"{r.in_force_from.isoformat() if r.in_force_from else '-'}"
            for i, r in enumerate(shortlist)
        )
        reply, usage = call_llm(
            llm,
            _VERSION_SYSTEM_PROMPT,
            f"Existing documents:\n{listing}\n\n"
            f"New document (opening):\n{markdown[:settings.version_extract_chars]}",
        )
        # Metered by the ingest scope this already runs inside - the same
        # accumulator image captioning and audio transcription write into.
        # Zero new metering code, no new usage endpoint label, and the tokens
        # land on the existing file_ingest usage row priced by the chat table.
        embedding_usage.record_llm(usage)
        matched, label, from_date, status = _parse_version_json(reply, shortlist)
    except Exception:
        # No LLM key, provider down, timeout, anything. Fail OPEN: index as a
        # standalone document, which is exactly what happens today.
        logger.info(
            "Version extraction unavailable for file %s", file.id, exc_info=True
        )
        return standalone
    if matched is None:
        return VersionProposal(file.id, label, from_date, status)
    row = next(r for r in shortlist if r.id == matched)
    return VersionProposal(row.document_id or row.id, label, from_date, status)
```

## Parsing — the only date parsing in the backend, and it is three lines

```python
def _parse_version_json(reply: str, shortlist):
    """(matched file id, label, date, status) from the model's reply.

    Every branch degrades to None. An unusable reply must mean "no match",
    which is today's behaviour, never a failed ingest.
    """
    try:
        parsed = json.loads(reply.strip())
    except Exception:
        found = re.search(r"\{.*\}", reply, re.S)   # fenced or prefaced JSON
        try:
            parsed = json.loads(found.group(0)) if found else None
        except Exception:
            parsed = None
    if not isinstance(parsed, dict):
        return None, None, None, None

    matched = None
    index = parsed.get("match")
    # `not isinstance(index, bool)` matters: True is an int and would select [1].
    if isinstance(index, int) and not isinstance(index, bool):
        if 1 <= index <= len(shortlist):
            matched = shortlist[index - 1].id

    label = parsed.get("version_label")
    label = label.strip()[:200] if isinstance(label, str) and label.strip() else None

    from_date = None
    raw = parsed.get("in_force_from")
    if isinstance(raw, str) and len(raw.strip()) == 10:
        try:
            # date.fromisoformat is a REAL calendar check - it rejects
            # 2019-02-30 - and it is stdlib, so nothing is added to
            # backend/requirements.txt. The `date` type then flows unconverted
            # the whole way: model -> date column -> Pydantic date -> ISO string
            # in JSON -> ISO string in the text input.
            from_date = date.fromisoformat(raw.strip())
        except ValueError:
            from_date = None

    status = parsed.get("legal_status")
    status = status if status in LEGAL_STATUSES else None
    return matched, label, from_date, status
```

## When it is unsure or returns nothing

| Case | Behaviour |
|---|---|
| `version_extraction_enabled = False` | standalone, no LLM call |
| project has no other current file | standalone, **no LLM call** (a project's first upload, and every test run) |
| no LLM key / provider raises / timeout | standalone, `logger.info` |
| reply is not JSON | standalone |
| `match: null` | standalone, but any extracted label/date/status is still kept |
| `match` out of range, `"1"`, or `true` | treated as null |
| `in_force_from` unparseable | `None` — the reviewer supplies it, and the endpoint refuses a supersession without one |
| `legal_status` outside the five | `None` — the CHECK constraint must never see an unknown value |
| matched | park to `'review'` with the proposal on the row |

Fail-open is the whole posture: the worst extraction failure produces exactly the behaviour that exists today. The gate is a positive assertion ("this replaces THAT file"), never an absence, so a provider outage cannot park a corpus.

### Decisions
- Extraction lives in `services/ingestion.py`, not a new module — a new `services/*.py` fails `check_c4_covers_services` until architecture.c4 grows a component, and every dependency is already imported there.
- Overlap coefficient with a legal-boilerplate stopword set, not raw intersection count — the worked case (Companies Act 2013 vs Companies Amendment Act 2019) is exactly what a raw count buries under every filename containing 'Act'.
- The probe pulls the first markdown heading explicitly rather than a raw prefix — scanned filings are named scan_0001.pdf and gazette boilerplate dominates the first few hundred characters.
- Reuse the project's answer model via `resolver.resolve_llm_key` — a dedicated extraction model means a second key-resolution path, a second capability check and a settings field threaded through the render-time three-way merge.
- `embedding_usage.record_llm` inside the existing ingest scope — no new usage endpoint label, and the tokens land on the `file_ingest` row that already carries captioning and transcription spend.
- No cycle guard — the lineage is a flat grouping key with no successor pointer, so there is no chain to walk.

### Risks
- One extra LLM call per first-time upload in any project that already holds a current file. Bounded by `version_extract_chars` (6000) and skipped entirely for a project's first document, but it is real spend on the user's own key and it is billed under `file_ingest`, not a distinguishable label.
- A false negative — a real new version the shortlist or the model misses — indexes alongside the old one, which is today's behaviour. Recoverable from the same endpoint at zero embedding cost (the manual supersede path), but it is silent until someone notices.
- `record_llm` sits inside a broad `except Exception`, so a missing call produces silently unbilled spend with no observable symptom. Covered by a source-scan test rather than an execution test for exactly that reason.

## The confirm transaction
## `POST /api/projects/{project_id}/files/{file_id}/version` → `list[FileOut]`

In `C:/Projects/Oreag/backend/app/routers/files.py` (the router already carries the `/api/projects/{project_id}` prefix and `get_owned_project`). One verb, four operations:

| Operation | Body |
|---|---|
| Confirm a review | `document_id` = matched lineage, `supersede_file_id` = its current file, metadata |
| Reject a review | `document_id: null`, `supersede_file_id: null`, metadata |
| Retire an older upload by hand | `document_id` = the old file's lineage, `supersede_file_id` = the old file |
| Bring a historical version back into force | called on the *historical* file, `supersede_file_id` = the currently-in-force one |

## The reconciliation is a pure function

Module scope in `routers/files.py` (already in `TestNoUndefinedHelpers.MODULES`), so the whole confirm semantic is unit-testable in a CI that has **no database service** (`.github/workflows/verify.yml:57`):

```python
def _lineage(file) -> uuid.UUID:
    """The document a file belongs to. NULL document_id means it is its own."""
    return file.document_id or file.id


class VersionOp(NamedTuple):
    file_id: uuid.UUID
    fields: dict          # attribute -> value to assign on the File row
    delete_chunks: bool


class SupersessionPlan(NamedTuple):
    ops: list[VersionOp]
    requeued: bool


def plan_supersession(target, predecessor, lineage, body) -> SupersessionPlan:
    """Every row write for one version decision, as data.

    PURE: takes anything with .id / .status / .chunk_count, so the semantics
    that actually matter - the predecessor loses its chunks AND its count in
    the same op, the successor is queued only when it needs to be - are
    asserted by unit tests rather than by an AST scan. CI cannot execute a
    query, so this is the only shape that gets them under real test.
    """
    fields: dict = {
        "document_id": lineage,
        "version_label": body.version_label,
        "in_force_from": body.in_force_from,
        "legal_status": body.legal_status,
        "in_force_to": None,          # this row is the current one
    }
    # Queue it: a confirmed review file, or a historical version being brought
    # back. An already-indexed, already-current file having only its metadata
    # corrected is left alone - re-embedding it would be a bill for nothing.
    requeued = target.chunk_count == 0 or target.status != "indexed"
    if requeued:
        fields.update(
            status="pending", error=None, conversion_error=None,
            attempts=0,        # claim_next burned one parking it; refund it
            chunk_count=0,
        )
        # conversion_note is NOT cleared: it describes how the MARKDOWN was
        # produced and the re-index REUSES that markdown, so the caveat is
        # still true. Same reasoning as files.py:648-654.
    ops = [VersionOp(target.id, fields, delete_chunks=False)]
    if predecessor is not None:
        ops.append(VersionOp(
            predecessor.id,
            {
                # Half-open: the successor's start date IS the predecessor's
                # end date, so one date serves both rows and they cannot
                # disagree. No date arithmetic anywhere.
                "in_force_to": body.in_force_from,
                # MUST be zeroed in the same transaction as the delete.
                # retrieval._PROJECT_CHUNKS_SQL sums files.chunk_count to feed
                # the ANN gate; a superseded row keeping its old count inflates
                # both the absolute vector_ann_min_chunks check and the
                # owned/total share, opening the HNSW path for a project whose
                # real chunk count is below both.
                "chunk_count": 0,
                "lease_expires_at": None,
            },
            delete_chunks=True,
        ))
    return SupersessionPlan(ops, requeued)
```

## Exact statement order

```python
@router.post("/files/{file_id}/version", response_model=list[FileOut])
def set_file_version(
    file_id: uuid.UUID,
    body: FileVersionRequest,
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    # -- 0. LOCK BOTH ROWS IN ONE ID-ORDERED STATEMENT --------------------
    # Ordering by File.id IN SQL is what makes deadlock impossible however
    # many confirms run concurrently, and the lock is what makes the checks
    # below true at COMMIT time rather than at read time. claim_next uses
    # with_for_update(skip_locked=True), so a worker also skips these rows
    # for the length of this transaction.
    ids = {file_id}
    if body.supersede_file_id is not None:
        ids.add(body.supersede_file_id)
    locked = db.scalars(
        select(File)
        .where(File.id.in_(ids), File.project_id == project.id)
        .order_by(File.id)
        .with_for_update()
    ).all()
    by_id = {f.id: f for f in locked}
    target = by_id.get(file_id)
    if target is None:
        raise HTTPException(404, "File not found")
    predecessor = (
        by_id.get(body.supersede_file_id)
        if body.supersede_file_id is not None else None
    )
    if body.supersede_file_id is not None:
        if predecessor is None:
            raise HTTPException(404, "Superseded file not found")
        if predecessor.id == target.id:
            raise HTTPException(422, "A file cannot supersede itself")

    # -- 1. IDEMPOTENCY, BEFORE ANY WRITE ---------------------------------
    # The retry-after-timeout case is the common one. A 409 here would show a
    # user an error for an operation that already succeeded.
    if (
        target.status != "review"
        and target.in_force_to is None
        and target.document_id == _lineage(predecessor or target)
        and target.version_label == body.version_label
        and target.in_force_from == body.in_force_from
        and target.legal_status == body.legal_status
        and (predecessor is None
             or predecessor.in_force_to == body.in_force_from)
    ):
        return _project_files(db, project)          # 200, no-op

    # -- 2. VALIDATE, all against the LOCKED rows -------------------------
    if target.status == "processing":
        # Its ingest is mid-flight and would overwrite status and chunk_count
        # from under this transaction.
        raise HTTPException(409, "File is being processed - try again shortly")

    if predecessor is not None:
        if predecessor.status in ("pending", "processing"):
            # A pending row is claimable by claim_next and the row lock only
            # holds for this transaction, so superseding it would leave a
            # retired version queued for indexing.
            raise HTTPException(
                409,
                "The version being replaced is queued for indexing - wait for "
                "it to finish, then supersede it.",
            )
        if predecessor.in_force_to is not None:
            raise HTTPException(
                422,
                "That version is already superseded - replace the one in force",
            )
        if body.in_force_from is None:
            # in_force_to is the ONLY thing keeping a superseded version out of
            # the index, so it must never be null on a supersession - and it is
            # DERIVED, never fabricated, so a missing date is a 422 rather than
            # date.today(). A single invented end date would corrupt the whole
            # future as-of timeline.
            raise HTTPException(
                422, "in_force_from is required when superseding a version"
            )
        if (predecessor.in_force_from is not None
                and body.in_force_from < predecessor.in_force_from):
            # Turns a CHECK violation (a 500) into a 422.
            raise HTTPException(
                422,
                "in_force_from is earlier than the version it replaces "
                f"({predecessor.in_force_from.isoformat()})",
            )
        lineage = _lineage(predecessor)
        if body.document_id is not None and body.document_id != lineage:
            raise HTTPException(422, "document_id does not match the superseded file")
    else:
        lineage = body.document_id or target.id

    # At most one current version per lineage. There is no unique constraint on
    # `files` (there is none of any kind) and the key is a coalesce, so this is
    # the invariant's only keeper. Scanned over the project's file list - it is
    # capped at 1000 rows.
    siblings = db.scalars(
        select(File).where(File.project_id == project.id)
    ).all()
    if body.document_id is not None and predecessor is None and not any(
        _lineage(f) == body.document_id for f in siblings
    ):
        raise HTTPException(422, "document_id names no document in this project")
    clash = next(
        (
            f for f in siblings
            if f.id != target.id
            and (predecessor is None or f.id != predecessor.id)
            and f.in_force_to is None
            and f.status != "review"
            and _lineage(f) == lineage
        ),
        None,
    )
    if clash is not None:
        raise HTTPException(
            422,
            f"{clash.filename} is already the current version of this document - "
            "name it as the version being superseded",
        )

    # -- 3. WRITES. One transaction, one commit, ZERO storage calls -------
    plan = plan_supersession(target, predecessor, lineage, body)
    for op in plan.ops:
        row = by_id[op.file_id]
        if op.delete_chunks:
            db.execute(sql_delete(Chunk).where(Chunk.file_id == op.file_id))
        for name, value in op.fields.items():
            setattr(row, name, value)
        # Blobs are NOT touched: storage_path, markdown_storage_path,
        # conversion_version, page_count, size_bytes, embedding_tokens and
        # indexed_at all survive, which is what makes history downloadable and
        # re-indexable later without re-upload, at embedding cost only.

    # -- 4. INVALIDATE AND SETTLE, in delete_file's proven order ----------
    bump_content_version(db, project.id)
    recompute_project_status(db, project)
    db.commit()
    return _project_files(db, project)


def _project_files(db: Session, project: Project) -> list[File]:
    return db.scalars(
        select(File).where(File.project_id == project.id).order_by(File.created_at)
    ).all()
```

### What commits when

**One commit, at the very end.** The successor's metadata, the predecessor's `in_force_to`, the chunk DELETE, `chunk_count = 0`, the requeue, the `content_version` bump and `project.status` land atomically or not at all. This deliberately diverges from ingestion.py:482-483 (which deletes chunks and commits): there, an interrupted re-ingest leaving zero chunks is acceptable; here, a commit at that point would create a window where the predecessor is unindexed and the successor is not yet queued, recoverable only by hand.

This endpoint calls neither `_shrink_vectors_in_place` nor `_restore_vectors_from_archive`, so the "vector migrations must be the request's first write because they call `db.rollback()` on failure" rule (files.py:295-310, 415-427) does not apply and there is no ordering hazard.

`bump_content_version` before `recompute_project_status` is copied verbatim from `delete_file` (files.py:687-690). The bump is a raw `UPDATE projects SET content_version = content_version + 1`; `recompute_project_status` then `db.flush()`es and assigns `project.status`. `content_version` is never assigned on the ORM object, so it is not dirty and the flush cannot clobber the raw UPDATE. `project.status` is set only by the helper here, never assigned directly, because the requeue is conditional — hand-assigning `"indexing"` would be wrong on the metadata-only path.

### Cache invalidation

`bump_content_version` is called **unconditionally** on every successful confirm, in the same transaction as the chunk write. Not the `routers/memory.py:138-144` pin/unpin non-bump reasoning: pin/unpin reorders content that still exists; a supersession removes text from the corpus, and re-serving a cached answer built on repealed law is the exact harm this feature exists to prevent. `_answer_signature` (query.py:241-270) is **not** extended — it is for things that change the ANSWER but not the CONTENT, and version metadata provably never reaches generation. L2 invalidation orphans rows rather than deleting them and there is no per-project purge anywhere (`RedisBackend.clear()` is an intentional no-op), so stale L2 rows age out over the 24h TTL, identical to every other content write in the product.

### Failure, rollback, idempotency

Any exception before the commit rolls the whole transaction back: the predecessor keeps its chunks and stays searchable, the successor stays in `'review'`, nothing was written to storage. There is no non-transactional side effect at all, so "the commit succeeded" and "the operation succeeded" are the same statement — the property `delete_file` lacks. A replay of the identical body short-circuits at step 1 and returns 200 with the same body. Two concurrent confirms against the same predecessor serialise on the row lock; the second re-reads the locked row, sees `in_force_to` set, and gets a clean 422.

### The retrieval gap, accepted

Between the commit and the requeued file's first embedding batch, the lineage has zero searchable chunks. **Prefer a gap over a double**: keeping the old chunks until the new ones land puts two versions of the same legal text in the index at once, which is precisely what this feature prevents — and if the successor's ingest then fails permanently, a superseded predecessor would go on serving repealed law indefinitely with nothing on screen to say so. It is also not new: `ingest_file` already deletes a file's chunks and commits at ingestion.py:482-483 before embedding anything. The window is bounded by a markdown-reuse re-ingest — `_reuse_converted_markdown` serves the stored blob, so there is no source download and no re-conversion, only chunk+embed.

### Delete

`delete_file` is unchanged except one line: wrap the post-commit `storage.delete(paths)` (files.py:691) in `try/except` + `logger.exception`. It is bare today, so a storage blip returns 500 for a delete that already committed and the client's retry 404s — and this feature multiplies the number of two-blob files. Deleting the current version of a multi-version lineage deliberately does **not** auto-promote a sibling: an implicit index write hidden inside a delete is exactly the surprise this feature exists to remove. The lineage is left headless and the user picks.

### Decisions
- `plan_supersession` as a pure function returning typed ops — CI has no database, so this is the only shape that puts 'the predecessor loses chunks AND count together' under a real test rather than an AST scan.
- One id-ordered `FOR UPDATE` statement covering both rows, with every check re-read from the locked rows — makes two concurrent confirms safe rather than merely unlikely, and makes `claim_next` skip both rows for the transaction's duration.
- Idempotency short-circuit before any write, returning 200 — the retry-after-timeout case is common and a 409 there is an error for an operation that already succeeded.
- 409 rather than a forced status change when the predecessor is pending — there is no honest status to move a queued file to, and refusing is one line.
- 422 rather than an invented `date.today()` when `in_force_from` is missing on a supersession — one fabricated end date corrupts the whole future as-of timeline.
- One commit at the end, diverging from ingestion.py's delete-then-commit — a mid-transaction commit here creates a hand-recoverable-only window.
- `storage.delete` in `delete_file` gets a try/except — it is bare today and this feature multiplies two-blob files.

### Risks
- The lineage has zero searchable chunks between the commit and the successor's last embedding batch. Accepted over the alternative (two versions live at once), bounded by markdown reuse, and disclosed in the confirm dialog.
- The clash check loads the project's file list unlocked. A concurrent confirm creating a second current version in the same lineage would slip past it — the row-locked predecessor check catches the supersession case, but a pure `document_id` re-parent racing another has a theoretical window. Bounded by the fact that both are human-initiated on the same screen.
- `bump_content_version` on a metadata-only edit (label or legal_status) invalidates caches for a change that alters nothing servable. Deliberate: unconditional invalidation cannot rot the way a conditional one can, and the operation is a handful of times per project, ever.

## What retrieval does and does not change
## `services/retrieval.py` and `services/explore.py`: ZERO LINES

Not restraint — the design. A superseded file has **zero rows in `chunks`**, and every chunk-search surface in the product starts `FROM chunks c JOIN files f ON f.id = c.file_id`, so there is nothing to exclude and no predicate to add.

| Surface | Why it needs no change |
|---|---|
| `SEMANTIC_SQL` (retrieval.py:48-58) | **Byte-pinned** by `test_vector_index.py:681-689` (whitespace-normalised string equality) and `:327-337` (columns exactly `[id, content, page_number, chunk_index, filename, similarity]`, binds exactly `{qvec, project_id, limit}`). Any predicate fails both. It needs none. |
| `LEXICAL_SQL` (retrieval.py:88-100) | Pinned identically. And its global `try/except` rolls the session back on any failure (:676-684), degrading to semantic-only — a predicate referencing a column missing on a partly-migrated database would fail *silently*, indistinguishable from "no keyword matches". The worst possible place for a correctness rule. |
| `_ANN_SEMANTIC_TEMPLATE` (:251-265) | `LIMIT :limit` sits inside a `MATERIALIZED` CTE that selects `c.file_id`; `files` is joined **outside** it. `AND f.in_force_to IS NULL` on the outer join would post-filter **after** the LIMIT and silently return fewer than `top_k` rows with no error. A predicate on `chunks` would go inside the CTE and be covered by `hnsw.iterative_scan` — but there is no version column on `chunks` and this design refuses to add one. Neither is needed: the rows are not there. |
| `_CAPABILITY_SQL` (:197-231) | Validates on name prefix, `indisvalid`, `indrelid`, `amname` and `opcname` — it **never** reads `pg_get_expr(i.indpred)`, so a narrowed index predicate would go undetected. This design creates no index, drops none, and narrows none of the six partial HNSW predicates, so the blind spot is never engaged. |
| `_PROJECT_CHUNKS_SQL` (:234-236) | The one place a superseded row could lie, neutralised by `chunk_count = 0` inside the confirm transaction. Left un-zeroed it inflates `owned`, which inflates **both** gates — `vector_ann_min_chunks = 20000` and the `owned/total` share against `vector_ann_min_project_share = 0.02` — opening the ANN path for a project genuinely below both and invalidating the recall margin documented at config.py:222-226, which is computed assuming `project_id` is the only post-filter. `_project_chunk_count` memoises on `content_version`, which the confirm bumps, so the gate recomputes on the very next request. |
| `rrf_merge` (:626-628) | `row.pop("id", None)` — no file identity survives retrieval; the only downstream handle is the `filename` string. This is *why* version metadata cannot reach generation, and it needs no change. |

`explore.py`'s `_SEED_CHUNK_SQL`, `_CHUNK_REL_CHUNK_SQL`, `_MEMORY_REL_CHUNK_SQL` and the three ANN templates all read `chunks`. Zero chunks, invisible. `files.py:139-140 _UNRESTORABLE_CHUNK_FILES_SQL` selects `DISTINCT c.file_id FROM chunks c JOIN files f`, so a superseded file can never appear in `restore_gap` and the Matryoshka partial-restore path cannot resurrect one — the non-obvious safe case, worth stating.

## `services/memory_graph.py`: ONE CHANGE, and it is mandatory

`RELATED_SQL` (:47-67) and `MEMORY_CHUNK_SQL` (:206-221) are chunk- and memory-driven and need nothing. But `_build_memory_graph` (:324-326) selects **every** File row for the project and calls `_load_markdown(file)` (:78-84 — a real, uncached `storage.download` per file), emitting a `type="file"` node plus a `type="section"` node per markdown heading whose `text` is the raw markdown slice (:389-403). Superseded versions keep their markdown blob by design, so without this fix retired statute text stays fully readable in the Visualize tab (`visualize-tab.tsx:1223-1226` renders `selected.text` untruncated, with a "View file" shortcut at :1243-1268) and every cache miss issues one storage download per superseded file. It is also served publicly: `routers/memory_graph.py:31-49` calls the identical builder under `require_api_key` on `/v1`.

```python
    files = db.scalars(
        select(File)
        .where(File.project_id == project.id, File.in_force_to.is_(None))
        .order_by(File.created_at)
    ).all()
```

The graph is a picture of what the brain can answer from; a node whose text is unreachable by every retrieval path is a lie, and `file_count` on the project node then means "documents in force", which is what a user reads it as. The response is cached on `content_version` (:304-306), which every confirm bumps, so it self-heals.

## `services/query.py`, `agentic.py`, `generation.py`: ZERO LINES

`SourceChunk` (schemas.py:218-228) is **not** widened and `generation._label` (:104-112) is **not** rewritten. Three reasons, in order:

1. **It is unnecessary.** Under a current-only index every chunk in the corpus is, by construction, from the in-force version. A version label in a citation disambiguates nothing, and the SHORT/LONG system prompts (generation.py:18-47) explicitly forbid the model mentioning the context, the sources or the documents at all.
2. **It is structurally blocked.** `SEMANTIC_SQL`/`LEXICAL_SQL` are byte-pinned, `rrf_merge` pops `id`, and `SourceChunk.filename` doubles as a type discriminator (memories are injected with `filename="memory"`, `chunk_index=-1` at query.py:418/738; `playground-tab.tsx:110` tests it).
3. **It would break streaming.** `/query/stream` passes `[dict(s) for s in ...]` raw (query.py:1005) into `sse.py:56`'s bare `json.dumps` — no `default=`, no encoder anywhere in `backend/app` — so a `datetime.date` on a source dict raises `TypeError: Object of type date is not JSON serializable` in the producer thread, which `sse.py:69-71` swallows: a truncated stream with no `done` frame. `/query` survives because Pydantic serialises it. A field that works on one transport and kills the other is not a contract.

**Explicit prohibition for the implementer:** do not add an `in_force_to` predicate to any statement in `retrieval.py` or `explore.py`, and do not append a version string to `filename` (it is a dedup key in `merge_sources`, agentic.py:295-314, and the memory type discriminator). A static test enforces the first.

## Memories, disclosed rather than engineered around

`memories` carries **no file provenance anywhere in the schema** (models.py:225-245 has `project_id`, `content`, `tags`, `pinned`, `source`, `embedding`, `embedding_full`, timestamps — no `file_id`, and migration 0007 adds none), so there is no query that can even identify "memories derived from the superseded version". Deleting them on a file event would also be wrong on its own terms — they are user- and agent-authored notes, not derived data. What is done: the confirm bumps `content_version`, invalidating every cached answer built on the old chunk-plus-memory mix; and the confirm dialog carries a standing line at the exact moment the human acts.

### Decisions
- Zero edits to retrieval.py and explore.py — the current-only index makes every predicate unnecessary, and the pinned tests make them impossible.
- `chunk_count = 0` inside the confirm transaction is the only retrieval-protecting write in the feature — it is what keeps `_PROJECT_CHUNKS_SQL`'s sum equal to the rows actually in the index.
- `_build_memory_graph` gets the `in_force_to IS NULL` filter — it is the one surface that reads a file's markdown directly rather than through chunks, and it is exposed on public `/v1`.
- `SourceChunk` and `generation._label` untouched — a version label disambiguates nothing under a current-only index, and a `date` field would kill every streaming query through `sse.py`'s bare `json.dumps`.
- Memories are handled by disclosure, not deletion — the schema cannot identify which ones came from a superseded version, and they are authored content, not derived data.

### Risks
- An answer cites `Companies Act.pdf` with no version label. Correctness holds — superseded text has no chunks — but attribution is not enriched, and a user reading a citation cannot tell which edition it came from without opening the Files tab.
- Memories quoting the replaced version stay citable forever. Surfaced in the confirm dialog; the structural fix (`memories.source_file_id`) is a separate, additive feature.
- The `_build_memory_graph` filter changes what the Visualize tab and public `/v1/memory-graph` return for any project with superseded files — fewer nodes than before. Intended, but it is a visible behaviour change on an existing public endpoint.

## API + MCP contract
## `FileOut` — five additive fields, and that is the whole read surface

`FileOut` (schemas.py:118-135) is the only file-shaped response in the repo, so the five defaulted fields flow to `GET /api/…/files`, `POST /api/…/files`, `POST /api/…/files/{id}/retry`, `POST /api/…/reindex` and `POST /v1/…/files` with no per-route work. **No lineage-listing endpoint**: `GET /files` already returns every file with its `document_id`, and the client groups by `document_id ?? id`.

## Two new dashboard endpoints

**1. `POST /api/projects/{project_id}/files/{file_id}/version` → `list[FileOut]`** — specified above. Returns the **full project file list** so the caller does `mutate(list, { revalidate: false })` exactly as `handleReindexAll` does at files-tab.tsx:305-311.

**2. `GET /api/projects/{project_id}/files/{file_id}/content?format=source|markdown` → raw bytes**

```python
@router.get("/files/{file_id}/content")
async def download_file_content(
    file_id: uuid.UUID,
    format: str = "source",
    project: Project = Depends(get_owned_project),
    db: Session = Depends(get_db),
):
    """Download a file's original bytes or its converted markdown.

    The only way to read a superseded version. Without it the locked decision
    to KEEP those blobs forever buys nothing - they would be unreachable and
    unbilled-for storage.

    Streams through the API rather than handing out a Supabase signed URL:
    storage.download already exists and is used verbatim, whereas a signed URL
    adds a storage helper, an expiry policy and a second auth model for
    bandwidth on an operation measured in dozens per project per year. The
    threadpool hop is REQUIRED - storage.download is blocking, and this route
    shares its worker with every streaming query.
    """
    file = db.get(File, file_id)
    if file is None or file.project_id != project.id:
        raise HTTPException(404, "File not found")
    if format not in ("source", "markdown"):
        raise HTTPException(422, "format must be 'source' or 'markdown'")
    if format == "markdown":
        path = file.markdown_storage_path
        if not path:
            raise HTTPException(404, "This file has no converted markdown")
        media, name = "text/markdown; charset=utf-8", f"{file.filename}.md"
    else:
        path = file.storage_path
        media = file.content_type or "application/octet-stream"
        name = file.filename
    try:
        data = await run_in_threadpool(storage.download, path)
    except Exception:
        logger.warning("Storage read failed for file %s", file_id, exc_info=True)
        raise HTTPException(502, "The stored file could not be read")
    # Quotes and newlines stripped: filename is user-supplied and goes into a
    # response header.
    safe = re.sub(r'[\r\n"]', "", name)[:200]
    return Response(
        content=data,
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{safe}"'},
    )
```

Needs `import re`, `from fastapi import Response`, `from fastapi.concurrency import run_in_threadpool` in files.py.

## The three requeue guards — the load-bearing edits

Both wipe-and-requeue sites become **set-based UPDATEs**, not comprehensions over a pre-loaded ORM list. Under READ COMMITTED the existing `files = db.scalars(select(File)...)` can read a row as current, block on a confirm's row lock, and then write `status='pending'` onto a row superseded in between; an UPDATE re-evaluates its predicate against the row it actually locks. **Leave `synchronize_session` at its default (`"auto"`)** — that is what refreshes the pre-loaded `File` objects that `reindex_project` returns as its `response_model`; passing `synchronize_session=False` is what would make the response stale and stop the Files-tab poll re-arming.

**(a) Upload / model-switch requeue**, files.py:634-658. `existing` is used for nothing but the loop, so the variable goes:

```python
    if reindex_existing:
        new_ids = {record.id for record in created}
        db.execute(sql_delete(Chunk).where(Chunk.project_id == project.id))
        clear_memory_vectors(db, project.id)
        bump_content_version(db, project.id)
        db.execute(
            update(File)
            .where(
                File.project_id == project.id,
                File.id.notin_(new_ids),
                # Superseded versions must never come back into the index, and
                # an unconfirmed review must never be chunked ahead of the
                # human. Keyed on in_force_to, NEVER on status - a superseded
                # file can also be 'failed'.
                File.in_force_to.is_(None),
                File.status != "review",
            )
            .values(
                status="pending", chunk_count=0, error=None,
                conversion_error=None, attempts=0,
            )
        )
        # conversion_note is NOT cleared - see the note this replaces.
```
This sits after the vector migrations (files.py:516-518), so their `db.rollback()`-on-failure contract is untouched.

**(b) Reindex**, files.py:866-873:
```python
    requeue_ids = [f.id for f in _files_to_requeue(files, restore_gap)]
    requeued = 0
    if requeue_ids:
        requeued = db.execute(
            update(File)
            .where(
                File.id.in_(requeue_ids),
                File.in_force_to.is_(None),
                File.status != "review",
            )
            .values(
                status="pending", chunk_count=0, error=None,
                conversion_error=None, attempts=0,
            )
        ).rowcount
    recompute_project_status(db, project)   # was: "indexing" if requeue else "ready"
```
`recompute_project_status` replaces the direct assignment because a requeue that is empty *because everything is superseded* must not report `'ready'`.

**(c) `_files_to_requeue`** (files.py:391) gets the filter as its first statement, so both branches inherit it and the helper stays the single choke point the static test asserts on:
```python
def _files_to_requeue(files: list[File], restore_gap: list[uuid.UUID]) -> list[File]:
    # Superseded versions are excluded before either branch. The docstring
    # below says an empty gap must re-ingest EVERY file and must not narrow -
    # this is the one exception, and it is not a narrowing of intent: a
    # superseded version is REQUIRED to hold zero chunks, so re-embedding it
    # would put a retired version of a document back into the live index.
    files = [f for f in files if f.in_force_to is None]
    ...
```

**(d) `_record_restore_savings`** (files.py:356-388) gets the same filter on `restored`:
```python
    # A superseded file keeps its embedding_tokens from its original ingest but
    # has no chunks to restore, and can never be in restore_gap (the gap is
    # computed from chunks). Leaving it in reports a Matryoshka saving for
    # embedding work that was never avoided.
    restored = [f for f in files if f.id not in gap and f.in_force_to is None]
```

**(e) `retry_file`** gets the two 409s from the state machine.

The project-wide `sql_delete(Chunk).where(Chunk.project_id == project.id)` on both routes needs no change — a superseded file has no chunks, so it is a no-op for those rows.

## `/v1` impact

**No new `/v1` route, no change to `rag_v1.py`.** The gate lives in `ingest_file`, not in a route, so a `/v1` upload of a suspected new version parks in `'review'` exactly like a dashboard upload and the `FileOut` it returns carries `status: "review"` plus the five new fields, automatically. That is a real contract change for consumers polling for `status == "indexed"`, and it is the right one: locked decision 2 says a human confirms, and an API key is not a human. Gating only dashboard uploads would mean a `/v1` upload of the 2024 Act indexes alongside the 2019 Act, invisibly. The escape hatch for an unattended integration is `version_extraction_enabled = False`.

A confirm endpoint on `/v1` is refused outright: `check_docs_sync.py:196` forces every `/v1` path into `docs/content.json` and `/openapi.json`, `/docs`, `/redoc` are served unauthenticated (main.py:71) — a publicly documented way to retire live law.

Required honesty edit in `frontend/src/app/docs/content.json`, upload section: *"A document that looks like a new version of one already in the project is returned with `status: \"review\"` and is not indexed until someone confirms the version in the dashboard."* No path changed, so `check_public_endpoints_documented` is not engaged; this is honesty, not CI. `GET /v1/projects/{id}` counts stay honest for free: `file_count` counts a review file, `chunk_count` sums `files.chunk_count` and a review file has 0 — and its `status` is now `'empty'` rather than `'ready'` when nothing is searchable.

## MCP: one docstring, zero schema change

`mcp-server/oreag_mcp/server.py:80-85`. Tool input schemas are derived from Python type hints, `add_document(filename, content)` is unchanged, and every body is `return _client().<m>(...)` returning `r.json()` verbatim, so the new fields pass through untouched. `check_mcp_tools` compares tool **names** and a claimed count, both unchanged — the README's "9 agent memory + docs tools" line stays correct. Append one sentence so an agent does not busy-wait:

> A document that looks like a new version of one already in the project comes back with `status` `"review"` and is not indexed until a person confirms the version in the dashboard.

### Decisions
- Set-based UPDATEs at both requeue sites with `synchronize_session` left at its default — the pre-loaded-list filter cannot survive a READ COMMITTED interleave, and the default is what keeps `reindex_project`'s response body fresh.
- Reindex calls `recompute_project_status` instead of assigning `'indexing' if requeue else 'ready'` — an empty requeue because everything is superseded must not report ready.
- Download streams through `run_in_threadpool(storage.download, ...)` rather than a signed URL — `storage.download` already exists and is used verbatim, and a signed URL needs a new helper, an expiry policy and a second auth model.
- `/v1` uploads are gated too — carving an exception means the same corpus behaves differently depending on which door a file came through.
- No `/v1` or MCP confirm surface — `/openapi.json` and `/docs` are unauthenticated, so it would be a publicly documented way to retire live law, and an API key is not the human locked decision 2 requires.

### Risks
- `/v1` and MCP uploaders now see a `status` value they have never seen. Documented in content.json and the MCP docstring, but any consumer with a hardcoded four-value check will treat `'review'` as unknown.
- The download route buffers a whole file in memory before responding. Bounded by `max_upload_bytes` (50 MB) and moved off the event loop, but a burst of concurrent downloads of large PDFs is memory pressure the API has not carried before.
- `_files_to_requeue`'s docstring explicitly says the empty-gap branch 'must not narrow'. This adds the one exception; the comment records it, but it is a documented invariant being edited.

## Frontend
## `frontend/src/lib/types.ts` — `FileRecord` (:80-96)

```ts
  status: "pending" | "processing" | "indexed" | "failed" | "review"
  document_id: string | null
  version_label: string | null
  in_force_from: string | null   // "YYYY-MM-DD"
  in_force_to: string | null     // non-null = superseded
  legal_status: "in_force" | "amended" | "repealed" | "draft" | "unknown" | null
```

## `files-tab.tsx` — the crash fix comes FIRST and ships alone

`FILE_STATUS[status]` at :168 is an unguarded object lookup over a closed four-key map, immediately dereferenced at :169 (`config.icon`) and three more times (:174, :175, :176, :183). It is rendered per row at :549 with no filtering, `satisfies` is compile-time only, `schemas.py:129` types `status` as a bare `str` so any value reaches the browser, and **there is no error boundary anywhere in the app** (`find frontend/src -name error.tsx -o -name global-error.tsx` returns nothing; a grep for `ErrorBoundary|componentDidCatch|getDerivedStateFromError` returns zero hits), so a throw here unmounts the whole project page, not just the badge. Fix it at source — this is a permanent fix for a latent fragility, not a workaround for this feature:

```tsx
type StatusConfig = {
  label: string
  icon: React.ComponentType<{ className?: string }>
  className: string
}

// A backend that learns a new status before this bundle does must degrade to a
// neutral badge, not throw during render. There is no error boundary anywhere
// in the app, so a throw here unmounts the whole project page.
const FILE_STATUS_UNKNOWN: StatusConfig = {
  label: "Unknown",
  icon: HelpCircle,
  className: "border-border/70 bg-muted/50 text-muted-foreground",
}

function FileStatus({ status }: { status: FileRecord["status"] }) {
  const config: StatusConfig =
    (FILE_STATUS as Record<string, StatusConfig>)[status] ?? FILE_STATUS_UNKNOWN
  const Icon = config.icon
  ...
}
```

Then the new entry — note the label collision: `failed` is already `"Needs review"` (:75), so use an action label:

```ts
  review: {
    label: "Confirm version",
    icon: GitBranch,                 // lucide-react, already the import source
    className:
      "border-violet-500/20 bg-violet-500/10 text-violet-700 dark:text-violet-400",
  },
```

## The SWR polling problem — resolved by construction; **do not edit :210-213**

The predicate is `latest?.some(f => f.status === "pending" || f.status === "processing") ? 3000 : 0`. Walk both edges:

1. *A file parks.* It is `'processing'` at that instant, so the poll is **already running**. The next tick fetches `'review'`, the predicate goes false, the poll stops. The review row is on screen. Correct, and correctly stops — a review file is terminal until a human acts, so polling it forever is a permanent 3 s request loop.
2. *A user confirms.* The endpoint returns the full list with that file now `'pending'`; the dialog calls `mutate(list, { revalidate: false })`. `refreshInterval` is a **function** of `latest`, so SWR re-evaluates it against the seeded data, sees a pending row and **restarts the poll on its own** — the mechanism files-tab.tsx:301-304 already documents for `handleReindexAll`.

**Adding `"review"` to the predicate would be the bug, not the fix.** Put that sentence in the PR description, because "the new state doesn't poll" is exactly the trap that invites the wrong edit. The confirm handler calls `mutate()` and never `onChanged()` directly — :214 already wires `onSuccess -> onChanged()`, and settings-tab.tsx:452-454 warns that invalidating the files key from `onChanged` is an infinite refetch loop.

## The review banner — above the list, not just on the row

With the 1000-file cap and a back-catalogue import, a review card twelve rows down is a card nobody sees. A banner above the `<ul>`, rendered when any file is `'review'`:

> **N documents need confirming** — they are stored but not searchable until you confirm what they replace. **[Review]**

Pure frontend, no new primitive. This is the difference between the gate working and the gate being a silent hold queue.

## Superseded rows follow the API-keys precedent verbatim

Keyed on `in_force_to !== null`: sort to the bottom (api-tab.tsx:221-224), a secondary muted "Superseded" badge beside the primary state (:576-582's grey-vs-emerald pattern), `opacity-60` on the card (:552-560), "Re-index file" hidden (:596 — the backend 409s it anyway). "Delete file" stays visible: deleting history must remain possible.

## The meta line (:483-495, dot-joined then `.split(" · ")` back apart at :514)

```ts
const superseded = file.in_force_to !== null
const meta = [
  (file.source_extension ?? "").replace(".", "").toUpperCase() || null,
  formatSize(file.size_bytes),
  file.version_label,
  superseded
    ? `${file.in_force_from ?? "?"} – ${file.in_force_to}`
    : `${file.chunk_count} chunk${file.chunk_count === 1 ? "" : "s"}`,
].filter(Boolean).join(" · ")
```

**Dates render as the raw ISO string, never through `new Date()`.** `new Date("2019-04-01")` parses as UTC midnight and `toLocaleDateString()` renders the *previous day* in any negative-offset timezone. The value is `YYYY-MM-DD` end to end — extractor → JSON → `date` column → input. No formatter, no helper, no timezone bug.

While in this block, fix the latent duplicate-key bug at :517: `key={item}` → ``key={`${index}-${item}`}``. These new segments raise its odds (a `version_label` of `"2019"` beside an `in_force_from` of `"2019"`).

## Delete dialog (:589-626) + `docs/content.json`, which repeats the copy verbatim

One conditional sentence when the target has siblings in its lineage:

> This is the current version of a document with N earlier version(s). They will remain in the project, but none of them will be searchable until you make one of them current.

And for a superseded target: *"This permanently deletes this version, its stored file and its converted text. Later versions are not affected."*

## `frontend/src/components/project/file-version-dialog.tsx` (new)

A new frontend component costs nothing in CI (`check_c4_covers_services` scans `backend/app/services/` only). It earns its file: files-tab.tsx is already ~640 lines and the dialog opens from two places (the "Confirm version" badge and a "Version history" menu item). Props `{ project, file, files, open, onOpenChange, onDone }`; everything derived client-side from the already-fetched list:

```ts
const lineage  = file.document_id ?? file.id
const siblings = files.filter(f => (f.document_id ?? f.id) === lineage && f.id !== file.id)
const current  = siblings.find(f => f.in_force_to === null && f.status !== "review")
```

**Review mode** (`file.status === "review"`): two radios — *"A new version of `{current.filename}`"* (default) and *"A separate document"* — plus three inputs prefilled from `version_label / in_force_from / legal_status`. Submits `{document_id: lineage, …, supersede_file_id: current.id}` or `{document_id: null, …, supersede_file_id: null}`. Two standing lines of copy, because this is the only moment a human sees the whole picture:

> While the new version is indexing, this document is briefly not searchable.
>
> Saved memories are not versioned. Any memory quoting the previous version stays in this project and can still be cited in answers.

**History mode**: the lineage sorted by `in_force_from` descending, nulls last. Each row shows filename, `version_label`, `in_force_from – (in_force_to ?? "current")`, two download buttons, and — on a superseded row — *"Make this the current version"*, plus *"Not a version of this document"*, which submits `{document_id: null, supersede_file_id: null}` and splits the file out of the lineage rather than re-superseding it into the same one. That second action is what makes "the extraction was wrong and I already confirmed it" recoverable.

**The missing date primitive.** Zero hits for `type="date" | DatePicker | Calendar | react-day-picker` across `frontend/src`; `components/ui/` has no calendar. Use the existing `Input` as `type="text"`, `placeholder="YYYY-MM-DD"`, `inputMode="numeric"`, submit gated on `/^\d{4}-\d{2}-\d{2}$/` when a supersession is selected, with Pydantic's `date` as the server-side check (strict ISO-8601, 422 on `2019-02-30`). `Input` carries the design system's styling and the value is an ISO string at every hop, so there is nothing to convert. Native `type="date"` is zero code but renders a browser-controlled widget the design system does not own. Promote to a `ui/` primitive when a second date field appears — not for one field that the extractor prefills in the common case.

## `frontend/src/lib/api.ts` — one new export

`api()` cannot be reused: it unconditionally `res.json()`s at :174, and `authedFetch` does not exist anywhere in the repo. The three sites that attach the bearer are all inside api.ts (:146, :199, :279), so the helper goes beside them:

```ts
export async function downloadFile(path: string, filename: string): Promise<void> {
  const supabase = createClient()
  const { data: { session } } = await supabase.auth.getSession()
  const headers = new Headers()
  if (session) headers.set("Authorization", `Bearer ${session.access_token}`)
  const res = await fetch(`${getApiBase()}${path}`, { headers })
  if (!res.ok) throw new ApiError(res.status, res.statusText)
  const url = URL.createObjectURL(await res.blob())
  const a = document.createElement("a")
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  URL.revokeObjectURL(url)
}
```

## `playground-tab.tsx` — stop lying about the upload

:379-383 toasts `"Upload complete. Indexing started."` unconditionally, never inspecting `created`. Two of the three upload paths live outside the Files tab, and this one now has a real chance of being wrong:

```tsx
      const created = await api<FileRecord[]>(`/api/projects/${project.id}/files`, {
        method: "POST",
        body: form,
      })
      const parked = created.filter((f) => f.status === "review").length
      toast.success(
        parked
          ? `${parked} file${parked === 1 ? "" : "s"} need a version confirmed`
          : "Upload complete. Indexing started.",
        parked ? { description: "Confirm what they replace in the Files tab." } : undefined
      )
```
`projects/new/page.tsx:160` gets the same treatment.

## Deliberately untouched

`add-files-dialog.tsx`, `projects/new/page.tsx`'s upload options and `playground-tab.tsx`'s upload body — the gate is server-side and needs no upload flag, which matters because two of the three send no options at all. `settings-tab.tsx` — no new project setting, so the render-time three-way merge (:114-176) is untouched.

### Decisions
- The `FILE_STATUS` lookup is made tolerant at source and ships FIRST, alone — it is a real latent fragility with no error boundary behind it, and fixing it is cheaper than avoiding a fifth status value forever.
- Do NOT add `'review'` to the SWR poll predicate — a review file is terminal until a human acts, so it would be a permanent 3 s request loop, and the poll already catches both edges.
- A banner above the list, not just a row badge — with a 1000-file cap and a back-catalogue import, a card twelve rows down is a silent hold queue.
- Version metadata renders in the meta line but never a user-supplied string that could contain ' · ' beyond `version_label`, which is length-capped at 200 and rendered as its own segment; the split at :514 is fixed with an index-qualified key rather than reworked.
- Raw ISO date strings, never `new Date()` — UTC-midnight parsing renders the previous day in any negative-offset timezone.
- A text `Input` with an ISO pattern, not a date primitive — one field the extractor prefills, versus a new dependency and a new `components/ui/` primitive.
- `downloadFile` is a new export beside `api()` — `api()` unconditionally JSON-parses and `authedFetch` does not exist.

### Risks
- The 'Unknown' fallback badge means a future status typo renders as a neutral pill instead of failing loudly. Accepted: a silent neutral badge is strictly better than unmounting the project page.
- A review file gives no signal outside the Files tab except the corrected upload toast and (in the all-review case) the project reporting 'empty'. A `ProjectOut.review_count` for the sidebar is a deliberate deferral, not an oversight.
- `file-version-dialog.tsx` derives everything from the already-fetched file list, so a lineage spanning more files than the list holds is impossible — but the list is unpaginated and a 1000-file project renders every row. Existing behaviour, unchanged, and now with grouping pressure it did not have.

## Deploy order + tests
## Deploy order — five steps, and none is optional

There is no migrations ledger and no Alembic; `backend/tests/apply_migrations.py:48-55` sorts `supabase/migrations/*.sql` by filename and runs each file whole under autocommit, swallowing `DuplicateTable`/`DuplicateObject` **at file granularity**. 0034 is independently idempotent (`add column if not exists` x5, two `pg_constraint`-guarded CHECKs, one re-runnable UPDATE, five `comment on column`), contains no `create policy`, and re-running it is a no-op.

**Step 1 — Commit A: frontend tolerance, ships alone.**
`files-tab.tsx`'s `FILE_STATUS_UNKNOWN` fallback, the widened `FileRecord["status"]` union in `types.ts`, and the `key={index}-{item}` fix. Reads only fields that already exist; nothing new is called. This exists so the bundle in users' browsers can survive a status value it has never seen — `tsc --noEmit` in CI guards the source tree, not a deployed bundle.

**Step 2 — Commit B: migration + README + tests.** One commit, or CI is red on main:
- `supabase/migrations/0034_document_versions.sql`
- `Readme.md:374`: `0001…0033` → `0001…0034`, and append `, document versions` to the parenthetical list. `check_docs_sync.py:365 check_readme_freshness` regexes that range and compares it to `len(glob('supabase/migrations/*.sql'))`; adding 0034 without this fails CI immediately.
- The new tests below.
- **No** `architecture.c4` edit and no `Readme.md:369` edit — this design adds no `services/*.py`.

**Step 3 — apply 0034 to production, backend NOT yet deployed.** Additive and nullable, so it is invisible to the running fleet: no existing code names the five columns, no row is rewritten, both CHECKs are trivially satisfied, and no index is built — so 0018/0026's "silently creates nothing above 5000 estimated rows" behaviour is not in play. Verify:
```sql
select count(*) from information_schema.columns
 where table_name = 'files'
   and column_name in ('document_id','version_label','in_force_from',
                       'in_force_to','legal_status');   -- expect 5
```

**Step 4 — Commit C: backend, with `version_extraction_enabled = False`.**
`models.py`, `schemas.py`, `config.py`, `services/ingestion.py`, `services/memory_graph.py`, `routers/files.py`, and the MCP docstring. **This deploy must not precede step 3**: the five columns are mapped non-deferred, so every File load names them and every upload names them in the INSERT — shipping against an un-migrated database breaks the Files tab, both upload routes, `claim_next`, reindex and delete. That is the incident at `0024_matryoshka_archive.sql:40-48`, and this feature reproduces its exact preconditions. With the flag False, extraction never runs and nothing can park.

**Step 5 — Commit D: the feature frontend**, then flip the flag.
`file-version-dialog.tsx`, the review badge and banner, the superseded row treatment, `lib/api.ts`'s `downloadFile`, the playground/new-project toast fixes, `docs/content.json`. Only after this is live does `version_extraction_enabled` become True. That removes the only window in which a file can be gated with no way to ungate it from the product.

Running workers pick the gate up on their next claim. Files mid-ingest under the old code finish and set `indexed_at`, which permanently closes the gate for them. No backfill, no in-flight migration, no half-deployed disagreement.

**Rollback.** Step 4 is revertible on its own: the columns stay, unread, with whatever values were written. Superseded files stay superseded but the old requeue paths no longer skip them, so a reindex during the rollback window re-indexes history. Repair is in the migration header. The migration itself is never reverted — the repo has been additive-only across 33 migrations except 0031.

## Tests — shaped for the CI that exists

CI runs pytest with **no database service** (verify.yml:57); `requirements-dev.txt` is literally `pytest>=8.0` — no linter, no type checker. So the two pieces of real logic (shortlisting, reply parsing) and the whole confirm semantic (`plan_supersession`) are pure functions over plain data, deliberately split out of the DB-touching callers.

### Free coverage, no test edit
`TestNoUndefinedHelpers` (test_units.py:2666) already lists `app.routers.files` and `app.services.ingestion`, so `_lineage`, `plan_supersession`, `_tokens`, `_probe_text`, `_shortlist`, `_parse_version_json`, `_propose_version`, `_file_still_current` and `_project_files` are all covered against the exact class of bug that test exists for.

### New `backend/tests/test_document_versions.py` — executable, no database

**`TestSupersessionPlan`** — the highest-value tests in the file, over `NamedTuple` stand-ins with `.id/.status/.chunk_count`:
- a review target + a predecessor → two ops; the predecessor's op has `delete_chunks=True` **and** `fields["chunk_count"] == 0` (the ANN-gate invariant, asserted directly, not scanned);
- the predecessor's `fields["in_force_to"] == body.in_force_from` exactly (the half-open chain, no arithmetic);
- the target's `fields["in_force_to"] is None` on every path;
- a review target with no predecessor (reject) → one op, `requeued is True`, `fields["document_id"] == target.id`;
- an already-`indexed` target with `chunk_count > 0` → `requeued is False` and `"status"` absent from `fields` (no gratuitous re-embed);
- `"conversion_note"` never appears in any op's `fields`.

**`TestVersionShortlist`** — `_shortlist` and `_tokens`:
- `"Companies Act 2013.pdf"` vs `"Companies-Amendment-Act-2019.pdf"` scores 0.5 by overlap and outranks an unrelated filename (the case Jaccard buries at 0.33);
- 8 candidates with limit 12 → all 8 (small projects must not lose recall to scoring);
- 30 candidates → exactly 12, best-overlap first, ties broken by filename so the result is deterministic;
- stopword-only overlap ("Act", "of", "the", "Rules") produces no score;
- an empty `version_label`, and a probe sharing no tokens, neither raises.

**`TestProbeText`** — `_probe_text("scan_0001.pdf", "# The Companies Act, 2013\n…")` contains `"Companies"`; markdown with no heading falls back to the prefix.

**`TestVersionProposalParsing`** — `_parse_version_json`, one assertion per degradation path: clean JSON; JSON in a ```` ```json ```` fence or after prose; `match: 0 / 99 / "1" / true` → `None` (bounds and the `isinstance(bool)` exclusion); `in_force_from: "2019-13-45" / "2019-02-30" / "tomorrow" / "2019" / 19700101` → `None`, never a raise; `legal_status: "REPEALED" / "pending"` → `None` (the CHECK must never see an unknown value); `"" / "sorry, I can't" / "[]" / "null"` → `(None, None, None, None)`.

**`TestLineageKey`** — `_lineage` returns `document_id` when set, `id` when None.

**`TestSchemaShape`** — `FileOut.model_fields` contains the five names and still none of `storage_path`, `conversion_version`, `chunk_size`; `FileVersionRequest.model_fields` shows all five as **required** (`is_required()` true), which is what makes `document_id: null` unambiguous. And **`SourceChunk.model_fields` contains no date-typed field** — the guard against the `sse.py` `json.dumps` break.

**`TestApiSurface`** (extend test_units.py:1677's sibling) — `POST /api/projects/{pid}/files/{fid}/version` and `GET …/content` both 401 unauthenticated.

### Static scans, extending the existing patterns

**`TestSupersededFilesAreNeverRequeued`**, modelled on `TestTruncationBumpsContentVersion` (test_units.py:1912) **including its guard-the-guard test**:
- `_requeue_sites()` AST-walks `app.routers.files` for every `update(File)` call and every `ast.Assign` whose target ends `.status` with the constant `"pending"`;
- `test_the_scan_finds_the_requeue_sites` asserts ≥ 3 (upload, reindex, retry) — a vacuous scan would make the next test pass for free;
- `test_every_requeue_is_guarded_on_currency` asserts each site's enclosing `FunctionDef` source contains `in_force_to`. Failure message: *"a requeue path can put a superseded version back into the index."*
- plus `assert "in_force_to" in inspect.getsource(files_router._files_to_requeue)` and `… _record_restore_savings`.

**`TestSupersedeIsAtomic`** — AST over `set_file_version`: exactly **one** `db.commit()`; contains `bump_content_version` and `recompute_project_status`; contains `with_for_update`; contains **no** `storage.` call at all — the property that makes confirm retry-safe, asserted rather than remembered.

**`TestVersionGateRunsExactlyOnce`** — over `inspect.getsource(app.services.ingestion)`, comments stripped the way `TestArchiveColumnIsOmittedNotNulled` does it (test_units.py:2404-2410):
- the gate line contains both `document_id is None` and `indexed_at is None`;
- `_propose_version`'s source contains `VersionProposal(file.id` (the standalone fallback that closes the gate) and `settings.version_extraction_enabled`;
- the review branch contains `file.status = "review"`, `recompute_project_status`, `db.commit()` and a bare `return`, and — walking the function body — that `return` precedes every `insert(Chunk)`. That last one is the locked decision expressed as an assertion: **a parked file is never chunked.**

**`TestVersionExtractionIsMetered`** — `"embedding_usage.record_llm"` appears in `_propose_version`'s source. A source scan rather than an execution test because the accumulator is a ContextVar and the call sits inside a broad `except Exception`: a missing `record_llm` produces silently unbilled spend with no observable symptom.

**`TestChunkInsertKeysAreUnchanged`** — the `rows = [{…}]` literal in `_ingest_file_inner` has exactly `{project_id, file_id, chunk_index, page_number, content, embedding}`, with `embedding_full` added only inside the `if archiving:` branch. This feature adds zero columns to `chunks`; the test pins the omit rule (ingestion.py:506-511) so the as-of migration cannot break it by accident.

**`TestVersioningNeverLeaksIntoThePinnedSql`** — `inspect.getsource` on `app.services.retrieval` and `app.services.explore`, assert none of `"in_force_to"`, `"in_force_from"`, `"document_id"`, `"version_label"` appears. This blocks the post-LIMIT `AND f.in_force_to IS NULL` on the outer join of `_ANN_SEMANTIC_TEMPLATE` — the failure that silently returns fewer than `top_k` rows with no error anywhere. `TestExactStatementsAreUntouched::test_semantic_sql` needs no change and must keep passing untouched; that is the proof.

**`TestNewestMigrationIsRunnable`** — **required, and the reason matters.** `test_text_search_config.py`'s `TestMigrationIsRunnableByOurOwnTooling::test_no_percent_sign_anywhere` reads only `_latest_tsv_migration()` (:22-37), which keeps only migrations that *redefine* `content_tsv` — 0034 does not, so nothing in CI would scan it. New class over `max(MIGRATIONS.glob("*.sql"))`: no `%` anywhere. Its docstring names `0018_hnsw_vector_indexes.sql` and `0026_memory_chunk_hnsw.sql` as the two grandfathered files (both carry `%` in their NOTICE runbooks), which is why the scan is newest-only.

**`TestMigration0034Shape`** — text scan: five `add column if not exists` naming exactly the five columns; no `create table`, `drop`, `truncate`, `create policy`; both `add constraint` statements inside a `select 1 from pg_constraint where conname =` guard (the 0032 pattern, asserted rather than assumed).

### Honestly untestable in this CI

The transaction's atomicity, the FK cascade on chunk delete, both CHECKs rejecting bad input, `claim_next` never claiming a `'review'` row, and the `FOR UPDATE` interleave. All need Postgres. They go in `backend/tests/verify_db.py` alongside the repo's existing live harnesses, as a pre-release checklist item: upload A, upload A-prime, confirm, assert `select count(*) from chunks where file_id = A` is 0, `A.chunk_count` is 0, `A.in_force_to = A_prime.in_force_from`, `A.markdown_storage_path` unchanged, `A_prime` reaches `indexed`. **Then run `POST /reindex` and assert A still has zero chunks** — the single highest-value manual check, because it is the trap most likely to survive every static scan. Also: `POST /files/{A}/retry` returns 409, and a confirm while a worker holds a lease on A leaves A with zero chunks.

Run `python scripts/check_docs_sync.py` locally before pushing; it fails on the README range until Commit B is complete. That is the harness working. Note `check_docs_sync.py:42` sets `FLOW = ROOT/"flow.md"` while the tracked file is `FLOW.md`, so that half is dead on ubuntu-latest CI — update FLOW.md anyway, do not rely on it failing.

### Decisions
- Frontend tolerance ships FIRST and alone, before the migration — the deployed bundle is what must survive an unknown status, and `tsc` cannot guard it.
- `version_extraction_enabled` defaults False and is flipped only after the feature frontend lands — it costs one env var and removes the only window where a file can park with no UI to confirm it.
- A new newest-migration percent-sign test is mandatory, not optional — the existing test is scoped to migrations that redefine `content_tsv` and would never read 0034.
- `plan_supersession` gets real unit tests rather than an AST scan, because it is a pure function and CI has no database.
- Every static scan ships with its guard-the-guard assertion, copying `TestTruncationBumpsContentVersion` — a scan that matches nothing passes silently.

### Risks
- Five deploy steps with a manual SQL apply between two of them. Steps 3 and 4 cannot be reordered without breaking most of the application, and nothing mechanical enforces the order — CI has no database and cannot execute a migration at all.
- The most important semantics (atomicity, the queue never claiming a review row, the reindex-after-supersede case) are verified by hand against staging, not by CI. Stated plainly rather than papered over with scans that only look like coverage.
- A backend rollback while superseded files exist re-opens the requeue hole. The repair SQL is in the migration header, but nothing runs it automatically.

## Deliberately out of scope
- **Point-in-time / as-of retrieval.** Locked out, and deliberately not half-built: no `as_of` parameter, no validity columns on `chunks`, no historical chunks. The upgrade path below is what keeps it one additive migration away.
- **Version metadata in citations or the answer prompt.** Unnecessary (under a current-only index every chunk is from the in-force version), structurally blocked (pinned SQL, `rrf_merge` pops `id`, `filename` is a type discriminator), and actively harmful on `/query/stream` (a `date` on a source dict hits `sse.py:56`'s bare `json.dumps` and truncates the stream with no `done` frame).
- **A `documents` table.** A lineage owns no data of its own — its display name is its current version's filename, its label and dates live on the versions. Writing `document_id = file.id` on every standalone file gives the "file 2 has something to match against" property for free, with no table, no RLS policy and no join.
- **A `superseded` value on `files.status`.** Every operational exclusion must key on `in_force_to` anyway (a superseded file can also be `failed`), so it would buy only a badge — and api-tab.tsx:576-582 already sets the precedent for a secondary badge derived from a timestamp column.
- **A fifth `projects.status`.** The all-superseded / all-review case reuses `'empty'`, which already means "nothing to answer from". A new value ripples into ProjectOut, the projects list, dashboard-sidebar, docs/content.json and the C4 model.
- **`ProjectOut.review_count` and a sidebar badge.** Deferred: the Files-tab banner plus the corrected upload toasts cover the discovery problem, and a counts field means editing `projects.py:52-79`'s grouped query (where a `CASE` must go in the SELECT list only — SQLite tolerates it in a GROUP BY and Postgres does not).
- **A per-project versioning toggle.** It needs a projects column, a ProjectOut field, and a fourth branch in the hand-written three-way merge that runs **during render** at settings-tab.tsx:114-176. The fleet-wide kill switch covers the operational need for one line and no migration.
- **`/v1` and MCP endpoints for confirming a version.** Locked decision 2 says a human confirms; an API key is not a human, and `/openapi.json`, `/docs`, `/redoc` are unauthenticated (main.py:71), so a `/v1` confirm is a publicly documented way to retire live law.
- **Version-aware memories (`memories.source_file_id`).** `memories` carries no file provenance anywhere in the schema, so no query can identify which memories came from a superseded version. Disclosed in the confirm dialog; the structural fix is additive and no locked decision implies it.
- **Auto-promoting a sibling when the current version is deleted.** An implicit index write hidden inside a delete is exactly the surprise this feature exists to remove. The lineage is left headless and the user picks.
- **A retire-without-successor verb.** Supersession happens because a successor arrived; a document with no replacement can be deleted. Adding it means `in_force_to` could be set with no `in_force_from` to derive it from, reintroducing the ambiguity the one-date rule removes.
- **Content hashing or upload dedupe.** Nothing in the repo hashes file content (`hashlib` appears at exactly four sites, none in ingestion). The extractor matches document IDENTITY, not bytes — a reprint of the same Act is a different file with the same identity, and a hash would call it new. Re-uploading the identical PDF costs one Reject click.
- **New indexes on `files`.** Capped at 1000 rows per project, every version query scoped by `project_id`, `files_project_idx` covers it. What breaks without one: nothing measurable.
- **A date-picker primitive in `components/ui/`.** One text input with an ISO placeholder, for one field the extractor prefills in the common case.
- **Storage GC for superseded blobs.** `maintenance.py:25-53` prunes only query_logs, usage_events and expired semantic_query_cache; nothing has ever pruned files, chunks or storage objects. Keeping history forever is the locked decision, not a leak.
- **Diffing two versions, and any redlining UI.** Both markdown blobs are kept and downloadable, so a diff is possible in any tool the user already has. Section-level alignment for legal text is the actual hard part and is a chunker project, not a versioning one.
- **A CHECK tying `in_force_to IS NOT NULL` to `chunk_count = 0`.** Tempting, and deliberately omitted: as-of retrieval needs superseded versions to be indexed. "Superseded implies zero chunks" is a policy of the current-only phase, enforced by the confirm transaction and re-healed by the migration's repair UPDATE — not a schema invariant a later migration would have to drop.
- **Any background job reacting to a future-dated `in_force_to`.** Indexability is event-driven and static — it changes when a human acts, never with the passage of time. `legal_status` is where that nuance is recorded, descriptively.

### Decisions
- Each exclusion is refused for a mechanism in this codebase, not a schedule — most would have to be un-done by the as-of upgrade rather than extended by it.
- `ProjectOut.review_count` is the one item deferred purely on cost; it is the first thing to add if reviews turn out to be missed in practice.

### Risks
- The two biggest deferrals — version-aware memories and no citation labels — are both cases where a user could reasonably believe an answer is version-scoped when only the chunks are. Mitigated by disclosure at the confirm moment, not by structure.
- Deferring `review_count` means the only cross-tab signal for a parked file is the upload toast at the moment of upload. A user who uploads and navigates away learns nothing until they return.

## Upgrade path to as-of retrieval
## The later change is additive because the interval is already real, dated and per-file

Everything as-of retrieval needs is being written **now**, correctly, as `date` values on rows that are never deleted:

- `in_force_from` and `in_force_to` are true `date` columns — not text, not a boolean — so `WHERE in_force_from <= :asof AND (in_force_to IS NULL OR in_force_to > :asof)` is a valid **half-open** interval predicate on day one, with no backfill, no type migration and no off-by-one to argue about in a backend that has no date library.
- The two rows in a supersession can never disagree, because `in_force_to` is *derived* from the successor's `in_force_from` and the API refuses it as an input.
- Every superseded row keeps `storage_path`, `markdown_storage_path`, **`conversion_version`**, `page_count` and `size_bytes`. That third one is load-bearing: when history is re-indexed, `_reuse_converted_markdown` (ingestion.py:255-260) finds a matching `CONVERSION_VERSION` and serves the stored `.md` blob without downloading the source — so backfilling history costs **embeddings only**, never a second image-captioning or speech-to-text bill on the user's own key.
- `document_id` groups the interval into a timeline; `indexed_at` survives on every retired row as the record that it was once indexed (`chunk_count` is zeroed, which is exactly why nothing relies on it for that).
- `POST /files/{id}/version` already brings a historical version back into force and re-indexes it from the stored markdown, so the markdown-reuse round trip is exercised in production before the upgrade depends on it.

## What migration 0035+ does

1. **Denormalise the interval onto `chunks`**: `alter table public.chunks add column if not exists valid_from date, add column if not exists valid_to date`, copied from the file at insert time. Forced by `_ANN_SEMANTIC_TEMPLATE` (retrieval.py:251-265): `LIMIT :limit` sits inside a `MATERIALIZED` CTE that joins `files` **outside** it, so a predicate on `files` post-filters after the LIMIT and silently shrinks result sets. A predicate on `chunks` goes inside the CTE, pre-LIMIT, and is covered by `hnsw.iterative_scan` (`relaxed_order`, `ef_search` 100, `max_scan_tuples` 40000). **This is the single most important forward-compatibility fact in this document.**
2. **Add those keys to the chunk INSERT dict under a guarded branch**, never as explicit `None` — the rule spelled out at ingestion.py:506-511 and now pinned by `TestChunkInsertKeysAreUnchanged`. A key present in the dict makes SQLAlchemy name the column, breaking every upload on a database missing the migration.
3. **Add sibling statements, never edit the pinned ones.** `SEMANTIC_SQL` and `LEXICAL_SQL` are pinned by whitespace-normalised string equality and by exact column and bind lists. As-of retrieval is an `AS_OF_SEMANTIC_SQL` / `AS_OF_LEXICAL_SQL` pair selected by an `asof` parameter, in the shape the ANN siblings already use (`ann_semantic_sql(...) or SEMANTIC_SQL`). Today's design edits neither, so this stays available.
4. **Do not narrow the six partial HNSW index predicates.** `_CAPABILITY_SQL` never reads `pg_get_expr(i.indpred)`, so a currency filter baked into an index predicate is invisible to the gate, which would keep routing queries onto an index that no longer covers the rows. Currency belongs in the SQL.
5. **Re-index history** through a new opt-in route that ingests a superseded file *without* superseding anything. This is the only genuinely new machinery — and it works with the existing worker untouched, because the currency filter lives at the **requeue sites**, never in `claim_next`. That placement is deliberate today for exactly this reason: "superseded implies never pending" must not become a global invariant.
6. **Recalibrate the ANN gate.** Once history carries chunks, retired rows' `chunk_count` becomes non-zero again and `_PROJECT_CHUNKS_SQL` counts them correctly, because they are now real searchable rows. But the as-of predicate becomes a *second* post-filter, and config.py:222-226 documents its recall margin as computed assuming `project_id` is the only one. That margin has to be re-derived — a tuning change, not a redesign, and putting the predicate on `chunks` (step 1) is what keeps it inside `iterative_scan`'s reach.

## What this design must therefore avoid doing now — and does

- **Never repurpose `in_force_to` as anything but the legal end date.** It is set only to the successor's `in_force_from`, never to `date.today()` and never to a sentinel — which is why the endpoint returns 422 rather than inventing a date. One fabricated end date corrupts the whole future timeline.
- **Never delete a row, a blob or a `conversion_version` on supersession.** The confirm transaction touches storage zero times, asserted by a static test.
- **Never let `legal_status` gate indexing.** As-of retrieval filters on dates; a status-based gate would be a second, contradictory authority to unpick.
- **Never make `in_force_to IS NOT NULL` mean "has no chunks" in code.** It is zeroed to keep the ANN gate honest, not as a correctness signal, and no code reads `chunk_count == 0` to mean "this file is retired."
- **Never add a unique constraint tying a lineage to a single current version.** One-current-per-lineage lives in the endpoint's validation, not the schema — as-of retrieval keeps the rule for *writes* while allowing many versions to hold chunks at once, which a database constraint would forbid.
- **Never add a column to `chunks` now**, and never poison `SourceChunk.filename` with a version string — 0035 needs a real field, a filename hack would have to be un-done, and in the meantime it breaks `merge_sources`' dedup key and risks colliding with the `filename == "memory"` discriminator.

Point-in-time is already half-answerable on data captured today: `where coalesce(document_id, id) = :d and in_force_from <= :t and (in_force_to is null or in_force_to > :t)` names which version of a document was in force on date T, against the `files` table alone, with no further schema change. 0035 only makes its TEXT searchable. The one cost the locked decision knowingly buys is re-embedding all history at that point — bounded, and kept embedding-cost-only precisely by keeping the markdown blobs.

### Decisions
- The as-of predicate must land on `chunks`, not `files` — a `files` predicate post-filters after the ANN CTE's LIMIT and shrinks recall silently.
- No columns on `chunks` today — the omit rule (ingestion.py:506-511) makes a deploy-window `"valid_from": None` break every upload, and nothing in scope needs them.
- The requeue currency filter lives at the requeue sites, never in `claim_next` — 0035's 'index this document's history' must be able to set a superseded file to pending and have the existing worker take it.
- `legal_status` is descriptive and never gates indexing — a second authority would have to be unpicked when dates become the filter.

### Risks
- Re-indexing history at 0035 means re-embedding every superseded version. Bounded and embedding-only (markdown blobs and `conversion_version` are kept), but it is a real bill deferred, not avoided.
- 0035 must edit `SEMANTIC_SQL` and `LEXICAL_SQL`'s pinned literals in `test_vector_index.py`. That is a deliberate reviewed edit of a pinned surface; this design touches none of it, but it is the one place the upgrade is not purely additive.
- The documented ANN recall margin stops holding the moment a second post-filter exists. It has to be re-derived at 0035, and nothing in CI can measure it.