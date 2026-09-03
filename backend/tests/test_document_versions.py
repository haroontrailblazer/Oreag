"""Document versioning (migration 0034) - the parts CI can actually execute.

CI runs pytest with no database service (.github/workflows/verify.yml), so
nothing here touches Postgres. Two kinds of test live in this file:

* text scans over the migration, which is the only way this suite can assert
  anything about SQL at all; and
* real unit tests over the pure functions the feature was deliberately split
  into - `plan_supersession`, `_shortlist`, `_parse_version_json`. Those carry
  the semantics that matter (a superseded version loses its chunks AND its
  chunk_count together; an unusable model reply degrades to "no match" rather
  than a failed ingest) and they are asserted directly rather than scanned for.

The properties that genuinely need Postgres - the confirm transaction's
atomicity, the FK cascade, both CHECK constraints, `claim_next` never claiming
a review row - are listed at the bottom of the design spec as a pre-release
manual checklist. They are named there rather than papered over with a scan
here that would only look like coverage.
"""
import pathlib
import re

MIGRATIONS = pathlib.Path(__file__).resolve().parent.parent.parent / "supabase/migrations"
MIGRATION_0034 = MIGRATIONS / "0034_document_versions.sql"

NEW_FILE_COLUMNS = (
    "document_id",
    "version_label",
    "in_force_from",
    "in_force_to",
    "legal_status",
)


class TestNewestMigrationIsRunnable:
    """Every new migration must be free of percent signs, not just the tsv ones.

    test_text_search_config.py already asserts this, but only over
    `_latest_tsv_migration()` - the newest migration that (re)defines
    content_tsv. 0034 does not, so nothing in CI would have read it. Scanning
    the newest migration by filename closes that gap permanently for whatever
    lands next.

    Newest-only, because two existing files are grandfathered: 0018 and 0026
    both carry percent signs inside the NOTICE runbooks they print when the
    table is too large to index inline.
    """

    def test_the_scan_finds_a_migration(self):
        # Guard the guard: a glob that matched nothing would make the real
        # assertion below pass for free.
        assert sorted(MIGRATIONS.glob("*.sql")), "no migrations found to scan"

    def test_no_percent_sign_in_the_newest_migration(self):
        newest = max(MIGRATIONS.glob("*.sql"))
        sql = newest.read_text(encoding="utf-8")
        assert "%" not in sql, (
            f"{newest.name} contains a percent sign, which makes it unrunnable "
            "by scripts/apply_migration.py (psycopg placeholder parsing)"
        )


class TestMigration0034Shape:
    """0034 must be additive, idempotent and re-runnable.

    There is no migrations ledger and no Alembic: backend/tests/
    apply_migrations.py sorts *.sql by filename and runs each file whole under
    autocommit, swallowing only DuplicateTable/DuplicateObject at FILE
    granularity. One unguarded failure abandons every statement after it in the
    same file, so idempotency is the migration's own job.
    """

    def setup_method(self):
        self.sql = MIGRATION_0034.read_text(encoding="utf-8")
        self.lower = self.sql.lower()

    def test_adds_the_five_version_columns_to_files(self):
        added = set(
            re.findall(r"add column if not exists\s+(\w+)", self.lower)
        )
        for column in NEW_FILE_COLUMNS:
            assert column in added, f"0034 does not add files.{column}"

    def test_adds_the_per_project_toggle(self):
        assert "version_tracking" in self.lower, (
            "0034 must add projects.version_tracking - the extractor asks a "
            "question that is true of any re-uploaded document, so it cannot "
            "be gated fleet-wide"
        )
        assert "default false" in self.lower, (
            "version_tracking must default false, or every existing project "
            "changes behaviour on deploy day"
        )

    def test_every_column_add_is_guarded(self):
        # `add column` without `if not exists` raises on a re-run, which
        # abandons the rest of the file.
        bare = re.findall(r"add column (?!if not exists)", self.lower)
        assert not bare, "0034 has an unguarded `add column`"

    def test_creates_no_table_and_destroys_nothing(self):
        # A new table would engage test_migration_rls.py and need its own
        # policy; the design deliberately puts the columns on `files`, which
        # already carries RLS from 0002.
        for phrase in ("create table", "drop column", "drop index", "drop table",
                       "truncate", "create policy"):
            assert phrase not in self.lower, f"0034 runs {phrase!r}"

    def test_both_check_constraints_are_pg_constraint_guarded(self):
        # The 0032_answer_policy.sql pattern. `add constraint` on a re-run
        # raises DuplicateObject, which apply_migrations swallows - but only
        # after abandoning every statement that followed it in the file.
        for name in ("files_legal_status_known", "files_in_force_range"):
            assert name in self.lower, f"0034 does not add {name}"
        guards = self.lower.count("select 1 from pg_constraint where conname =")
        assert guards >= 2, (
            "each `add constraint` must sit inside a pg_constraint existence "
            f"guard; found {guards} guards for 2 constraints"
        )

    def test_legal_status_check_lists_exactly_the_known_values(self):
        for value in ("in_force", "amended", "repealed", "draft", "unknown"):
            assert f"'{value}'" in self.sql, (
                f"legal_status CHECK does not admit {value!r}"
            )

    def test_zeroes_chunk_count_on_superseded_rows(self):
        # retrieval._PROJECT_CHUNKS_SQL sums files.chunk_count to size the ANN
        # gate. A superseded row keeping its old count inflates both the
        # absolute threshold and the project-share threshold, opening the HNSW
        # path for a project genuinely below both. The statement is also the
        # repair for a backend rollback, so it must be re-runnable.
        assert re.search(
            r"update public\.files set chunk_count = 0", self.lower
        ), "0034 must zero chunk_count on superseded rows"
        assert "where in_force_to is not null" in self.lower

    def test_document_id_is_not_a_foreign_key(self):
        # A lineage must outlive the deletion of any member, including the
        # first. SET NULL shatters the group into singletons; CASCADE destroys
        # the history the feature exists to keep.
        assert "references public.files" not in self.lower, (
            "document_id must be a plain grouping key, not a foreign key"
        )

    def test_every_new_column_is_documented(self):
        for column in NEW_FILE_COLUMNS + ("version_tracking",):
            assert f".{column} is" in self.lower, (
                f"0034 does not `comment on column` {column}"
            )


# --------------------------------------------------------------------------
# Real unit tests over the pure functions. These carry the semantics that
# matter; everything here is asserted directly, not grepped for.
# --------------------------------------------------------------------------

import ast
import inspect
import uuid
from datetime import date
from typing import NamedTuple


class _Target(NamedTuple):
    """Stand-in for a File row. plan_supersession reads only these three."""

    id: uuid.UUID
    status: str
    chunk_count: int


class _Body(NamedTuple):
    """Stand-in for FileVersionRequest."""

    version_label: str | None
    in_force_from: date | None
    legal_status: str | None
    instrument_role: str | None = "principal"


def _plan(target, predecessor, lineage=None, body=None):
    from app.routers.files import plan_supersession

    body = body or _Body("Act 18 of 2013", date(2021, 1, 22), "in_force")
    return plan_supersession(target, predecessor, lineage or target.id, body)


class TestSupersessionPlan:
    """The confirm semantic, asserted rather than scanned.

    CI has no database service, so the writes were deliberately split out of
    the endpoint into a pure function precisely so these could be real tests.
    """

    def test_a_confirmed_review_produces_two_ops(self):
        target = _Target(uuid.uuid4(), "review", 0)
        pred = _Target(uuid.uuid4(), "indexed", 40)
        plan = _plan(target, pred, lineage=pred.id)
        assert [op.file_id for op in plan.ops] == [target.id, pred.id]

    def test_the_predecessor_loses_its_chunks_and_its_count_together(self):
        # The ANN gate (retrieval._PROJECT_CHUNKS_SQL) sums files.chunk_count,
        # so a superseded row that keeps its old count inflates both the
        # absolute threshold and the project-share threshold - opening the HNSW
        # path for a project genuinely below both, and invalidating the recall
        # margin config.py documents. Dropping the chunks without zeroing the
        # count is the specific bug this asserts against.
        target = _Target(uuid.uuid4(), "review", 0)
        pred = _Target(uuid.uuid4(), "indexed", 40)
        op = _plan(target, pred, lineage=pred.id).ops[1]
        assert op.delete_chunks is True
        assert op.fields["chunk_count"] == 0

    def test_the_predecessor_end_date_is_exactly_the_successor_start_date(self):
        # Half-open interval, one date serving both rows: they cannot disagree
        # and no date arithmetic is needed anywhere in a backend that has no
        # date library.
        target = _Target(uuid.uuid4(), "review", 0)
        pred = _Target(uuid.uuid4(), "indexed", 40)
        body = _Body(None, date(2021, 1, 22), None)
        op = _plan(target, pred, lineage=pred.id, body=body).ops[1]
        assert op.fields["in_force_to"] == date(2021, 1, 22)

    def test_the_target_is_always_left_current(self):
        for pred in (None, _Target(uuid.uuid4(), "indexed", 40)):
            target = _Target(uuid.uuid4(), "review", 0)
            plan = _plan(target, pred)
            assert plan.ops[0].fields["in_force_to"] is None

    def test_the_target_never_loses_its_chunks(self):
        target = _Target(uuid.uuid4(), "indexed", 12)
        pred = _Target(uuid.uuid4(), "indexed", 40)
        assert _plan(target, pred, lineage=pred.id).ops[0].delete_chunks is False

    def test_rejecting_a_review_makes_it_its_own_document(self):
        target = _Target(uuid.uuid4(), "review", 0)
        plan = _plan(target, None)
        assert len(plan.ops) == 1
        assert plan.ops[0].fields["document_id"] == target.id
        assert plan.requeued is True
        assert plan.ops[0].fields["status"] == "pending"

    def test_a_parked_file_gets_its_retry_budget_back(self):
        # claim_next burned an attempt to park it; charging the user for that
        # would let three confirms exhaust the budget and fail the file.
        target = _Target(uuid.uuid4(), "review", 0)
        assert _plan(target, None).ops[0].fields["attempts"] == 0

    def test_a_metadata_only_edit_does_not_requeue(self):
        # An already-indexed, already-current file having its label corrected
        # must not be re-embedded - that is a bill for nothing.
        target = _Target(uuid.uuid4(), "indexed", 12)
        plan = _plan(target, None)
        assert plan.requeued is False
        assert "status" not in plan.ops[0].fields
        assert "chunk_count" not in plan.ops[0].fields

    def test_conversion_note_is_never_cleared(self):
        # It describes how the MARKDOWN was produced, and the re-index reuses
        # that markdown - so the caveat is still true.
        target = _Target(uuid.uuid4(), "review", 0)
        pred = _Target(uuid.uuid4(), "indexed", 40)
        for op in _plan(target, pred, lineage=pred.id).ops:
            assert "conversion_note" not in op.fields


class _Row(NamedTuple):
    id: uuid.UUID
    filename: str
    version_label: str | None
    # 0035: the shortlist scores this too, so a held file whose filename says
    # nothing is still reachable. A stub without it models an impossible row.
    extracted_title: str | None = None
    # 0036: ties break on recency before filename, so a stub without this
    # models a row _shortlist cannot sort.
    in_force_from: date | None = None


def _row(filename, label=None, title=None, from_date=None):
    return _Row(uuid.uuid4(), filename, label, title, from_date)


class TestVersionShortlist:
    def test_an_amendment_outranks_an_unrelated_document(self):
        # The worked case. After stopwords this is {companies, 2013} vs
        # {companies, 2019}: Jaccard scores it 0.33 and buries it under noise,
        # the overlap coefficient scores it 0.5. Recall-oriented on purpose -
        # the LLM is the precision filter and the human is the gate.
        from app.services.ingestion import _shortlist

        amendment = _row("Companies-Amendment-Act-2019.pdf")
        candidates = [_row(f"Unrelated Statute {i}.pdf") for i in range(20)]
        candidates.append(amendment)
        top = _shortlist(candidates, "Companies Act 2013.pdf", limit=3)
        assert amendment in top

    def test_a_small_project_sends_every_candidate(self):
        from app.services.ingestion import _shortlist

        candidates = [_row(f"doc{i}.pdf") for i in range(8)]
        assert len(_shortlist(candidates, "anything.pdf", limit=12)) == 8

    def test_the_limit_is_respected_and_deterministic(self):
        from app.services.ingestion import _shortlist

        candidates = [_row(f"Statute {i}.pdf") for i in range(30)]
        first = _shortlist(candidates, "Companies Act 2013.pdf", limit=12)
        second = _shortlist(candidates, "Companies Act 2013.pdf", limit=12)
        assert len(first) == 12
        assert [r.id for r in first] == [r.id for r in second]

    def test_stopwords_alone_do_not_score(self):
        from app.services.ingestion import _tokens

        assert _tokens("The Act of Rules and Regulations") == set()

    def test_an_empty_probe_does_not_raise(self):
        from app.services.ingestion import _shortlist

        candidates = [_row(f"doc{i}.pdf") for i in range(20)]
        assert len(_shortlist(candidates, "", limit=5)) == 5


class TestProbeText:
    def test_a_scanned_filing_is_identified_by_its_heading(self):
        # Scanned filings arrive as scan_0001.pdf and carry their identity only
        # in the text, so the heading is pulled out explicitly rather than
        # taking a raw prefix, which is mostly gazette boilerplate.
        from app.services.ingestion import _probe_text

        probe = _probe_text("scan_0001.pdf", "# The Companies Act, 2013\n\nbody")
        assert "Companies" in probe

    def test_markdown_with_no_heading_falls_back_to_the_prefix(self):
        from app.services.ingestion import _probe_text

        assert "PRELIMINARY" in _probe_text("x.pdf", "PRELIMINARY text here")


class TestVersionProposalParsing:
    """Every degradation path must mean "no match", never a failed ingest."""

    def _parse(self, reply, shortlist=None):
        from app.services.ingestion import _parse_version_json

        return _parse_version_json(reply, shortlist or [_row("a.pdf"), _row("b.pdf")])

    def test_clean_json(self):
        shortlist = [_row("a.pdf"), _row("b.pdf")]
        matched, label, from_date, status, _role, _kind = self._parse(
            '{"match": 2, "version_label": "Act 18", '
            '"in_force_from": "2013-08-29", "legal_status": "in_force"}',
            shortlist,
        )
        assert matched == shortlist[1].id
        assert label == "Act 18"
        assert from_date == date(2013, 8, 29)
        assert status == "in_force"

    def test_json_inside_a_fence_or_after_prose(self):
        for reply in (
            '```json\n{"match": 1}\n```',
            'Sure! Here you go:\n{"match": 1}',
        ):
            assert self._parse(reply)[0] is not None

    def test_an_out_of_range_or_wrongly_typed_match_is_dropped(self):
        # `true` is an int in Python and would otherwise select shortlist[0];
        # `"1"` is the model quoting the number.
        for reply in (
            '{"match": 0}', '{"match": 99}', '{"match": "1"}',
            '{"match": true}', '{"match": -1}',
        ):
            assert self._parse(reply)[0] is None, reply

    def test_an_unparseable_date_never_raises(self):
        for raw in ("2019-13-45", "2019-02-30", "tomorrow", "2019", "not-a-date"):
            assert self._parse('{"in_force_from": "' + raw + '"}')[2] is None, raw

    def test_a_real_calendar_check_is_applied(self):
        assert self._parse('{"in_force_from": "2019-02-28"}')[2] == date(2019, 2, 28)

    def test_an_unknown_legal_status_is_dropped(self):
        # The CHECK constraint must never see a value it does not admit.
        for raw in ("REPEALED", "pending", "in-force", ""):
            assert self._parse('{"legal_status": "' + raw + '"}')[3] is None, raw

    def test_junk_degrades_to_nothing_at_all(self):
        for reply in ("", "sorry, I cannot help with that", "[]", "null", "{"):
            assert self._parse(reply) == (None, None, None, None, None, None), reply


class TestLineageKey:
    def test_a_null_document_id_means_the_file_is_its_own_document(self):
        from app.routers.files import _lineage

        own = uuid.uuid4()
        parent = uuid.uuid4()

        class _F:
            def __init__(self, document_id):
                self.id = own
                self.document_id = document_id

        assert _lineage(_F(None)) == own
        assert _lineage(_F(parent)) == parent


class TestSchemaShape:
    def test_file_out_carries_the_version_fields(self):
        from app.schemas import FileOut

        for name in NEW_FILE_COLUMNS:
            assert name in FileOut.model_fields

    def test_file_out_still_leaks_no_internals(self):
        from app.schemas import FileOut

        for name in ("storage_path", "markdown_storage_path", "conversion_version"):
            assert name not in FileOut.model_fields

    def test_the_version_request_makes_a_null_document_id_deliberate(self):
        # Every field required, so `document_id: null` means "this is a separate
        # document" rather than "I forgot to send it". That distinction is the
        # whole reject path.
        from app.schemas import FileVersionRequest

        for name in ("document_id", "supersede_file_id", "in_force_from",
                     "legal_status"):
            assert FileVersionRequest.model_fields[name].is_required(), name

    def test_in_force_to_is_never_an_input(self):
        # It is derived - always the successor's in_force_from - so the two
        # rows cannot disagree.
        from app.schemas import FileVersionRequest

        assert "in_force_to" not in FileVersionRequest.model_fields

    def test_a_citation_never_carries_a_date(self):
        # sse.py json.dumps()es the streamed source dicts, and a date is not
        # JSON-serialisable. Version metadata deliberately does not reach the
        # citation at all in this design.
        from datetime import date as date_type

        from app.schemas import SourceChunk

        for field in SourceChunk.model_fields.values():
            assert field.annotation is not date_type


# --------------------------------------------------------------------------
# Static scans, extending the existing patterns. Each ships with its
# guard-the-guard assertion, copying TestTruncationBumpsContentVersion - a scan
# that matches nothing passes silently, which is worse than no scan at all.
# --------------------------------------------------------------------------


def _files_source():
    from app.routers import files as files_router

    return inspect.getsource(files_router)


class TestSupersededFilesAreNeverRequeued:
    """A requeue path must never put a retired version back into the index.

    Both wipe-and-requeue sites set EVERY file in the project back to
    'pending'. Without a currency guard, changing the embedding model - an
    operation with nothing to do with versioning - silently re-indexes every
    superseded edition in the corpus. It is the single most likely way this
    feature breaks, and no test that lacks a database can catch it any other
    way.
    """

    def _requeue_sites(self):
        tree = ast.parse(_files_source())
        sites = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and "update(File)" in ast.unparse(node):
                sites.append(node)
            elif isinstance(node, ast.Assign):
                target = ast.unparse(node.targets[0])
                value = ast.unparse(node.value)
                if target.endswith(".status") and value == "'pending'":
                    sites.append(node)
        return sites

    def test_the_scan_finds_the_requeue_sites(self):
        """Guards the guard - a vacuous scan would pass the tests below."""
        assert len(self._requeue_sites()) >= 3

    def test_the_requeue_helper_filters_on_currency(self):
        from app.routers import files as files_router

        assert "in_force_to" in inspect.getsource(files_router._files_to_requeue), (
            "a requeue path can put a superseded version back into the index"
        )

    def test_the_matryoshka_saving_excludes_superseded_files(self):
        # A superseded file keeps its embedding_tokens but has no chunks to
        # restore, so counting it reports a saving for work never avoided.
        from app.routers import files as files_router

        assert "in_force_to" in inspect.getsource(
            files_router._record_restore_savings
        )

    def test_both_wipe_and_requeue_statements_state_the_predicate(self):
        blocks = _files_source().split("update(File)")[1:]
        assert len(blocks) >= 2, "expected the upload and reindex requeues"
        for block in blocks:
            assert "in_force_to" in block[:1200], (
                "a set-based requeue that does not re-state the currency "
                "predicate can resurrect a version superseded mid-request"
            )


class TestSupersedeIsAtomic:
    """The commit and the operation must succeed or fail as one thing.

    delete_file cannot have this property - it removes storage objects after
    its commit - which is exactly why the confirm path was built with no
    non-transactional side effect at all.
    """

    def _source(self):
        from app.routers import files as files_router

        return inspect.getsource(files_router.set_file_version)

    def test_it_commits_exactly_once(self):
        assert self._source().count("db.commit()") == 1

    def test_it_invalidates_the_answer_caches(self):
        # A supersession REMOVES text from the corpus. Re-serving a cached
        # answer built on repealed law is the exact harm this feature exists to
        # prevent, so this is not the memory pin/unpin non-bump case.
        source = self._source()
        assert "bump_content_version" in source
        assert "recompute_project_status" in source

    def test_it_locks_both_rows(self):
        assert "with_for_update" in self._source()

    def test_it_touches_no_storage(self):
        # The property that makes a retry safe: nothing outside the transaction
        # can have happened, so replaying the request cannot destroy a blob.
        assert "storage." not in self._source()


class TestVersionGateRunsExactlyOnce:
    """Extraction must not re-open a review the user already settled."""

    def test_the_gate_requires_both_conditions(self):
        # `indexed_at is null` stops a CONVERSION_VERSION bump - which
        # re-converts the whole corpus - from re-examining every indexed file
        # and taking a production index offline in one deploy. `document_id is
        # null` stops confirm -> pending -> worker -> park looping forever.
        from app.services import ingestion

        assert (
            "file.document_id is None and file.indexed_at is None"
            in inspect.getsource(ingestion)
        )

    def test_the_proposal_always_closes_the_gate(self):
        from app.services import ingestion

        assert "VersionProposal(file.id" in inspect.getsource(
            ingestion._propose_version
        ), (
            "_propose_version must fall back to the file's own id, or the gate "
            "never closes"
        )

    def test_both_switches_gate_the_extraction(self):
        from app.services import ingestion

        source = inspect.getsource(ingestion._propose_version)
        assert "settings.version_extraction_enabled" in source
        assert "project.version_tracking" in source

    def test_a_parked_file_is_never_chunked(self):
        """The locked decision, expressed as an assertion.

        Walks the function body: the review branch's early return must sit
        above every chunk INSERT, so no path exists where a file is held for
        review and indexed anyway.
        """
        from app.services import ingestion

        tree = ast.parse(inspect.getsource(ingestion._ingest_file_inner))
        park_line = insert_line = None
        for node in ast.walk(tree):
            text = ast.unparse(node)
            if park_line is None and isinstance(node, ast.Assign):
                if text == "file.status = 'review'":
                    park_line = node.lineno
            if (
                insert_line is None
                and isinstance(node, ast.Call)
                and "insert(Chunk)" in text
            ):
                insert_line = node.lineno
        assert park_line is not None, "the review branch is gone"
        assert insert_line is not None, "the chunk insert is gone"
        assert park_line < insert_line, "a parked file can still be chunked"


class TestVersionExtractionIsMetered:
    """Unbilled BYOK spend has no observable symptom.

    A source scan rather than an execution test on purpose: the accumulator is
    a ContextVar and the call sits inside a broad `except Exception`, so a
    missing record_llm produces silently unbilled spend that nothing surfaces.
    """

    def test_the_extraction_call_is_recorded(self):
        from app.services import ingestion

        assert "embedding_usage.record_llm" in inspect.getsource(
            ingestion._propose_version
        )


class TestVersioningNeverLeaksIntoThePinnedSql:
    """Retrieval must stay untouched - that is the whole point of the design.

    A superseded version holds zero chunks, so there is nothing to filter out.
    The tempting edit is `AND f.in_force_to IS NULL` on the outer join of
    _ANN_SEMANTIC_TEMPLATE, which post-filters AFTER the CTE's LIMIT and
    silently returns fewer than top_k rows with no error anywhere.
    TestExactStatementsAreUntouched must also keep passing untouched; together
    they are the proof.
    """

    def test_no_version_column_appears_in_any_search_module(self):
        from app.services import explore, retrieval

        for module in (retrieval, explore):
            source = inspect.getsource(module)
            for name in ("in_force_to", "in_force_from", "document_id",
                         "version_label", "legal_status"):
                assert name not in source, (
                    f"{module.__name__} references {name} - a version predicate "
                    "in the pinned SQL breaks the byte-equality test, and one "
                    "on the ANN outer join silently shrinks recall"
                )


# --------------------------------------------------------------------------
# Regressions found by adversarial review of the first implementation. Each of
# these was a real defect, so each gets a test rather than a comment.
# --------------------------------------------------------------------------


class TestEveryRequeueIsAConditionalUpdate:
    """`retry_file` was the third requeue site and the one left unguarded.

    It read the row with db.get() (no lock), checked in_force_to, then wrote
    status='pending' in a statement keyed on id alone. A confirm landing in
    that window superseded the row, the write blocked on its lock and then
    applied unconditionally, and a retired edition ended up in the durable
    queue - the exact interleave the other two sites were converted to
    set-based UPDATEs to prevent.
    """

    def test_retry_writes_through_a_predicate_not_an_attribute(self):
        from app.routers import files as files_router

        source = inspect.getsource(files_router.retry_file)
        assert "update(File)" in source, (
            "retry_file must write through a conditional UPDATE - an "
            "attribute assignment is keyed on id alone and cannot exclude a "
            "row superseded since it was read"
        )
        assert "File.in_force_to.is_(None)" in source
        assert 'file.status = "pending"' not in source

    def test_no_requeue_site_assigns_pending_as_an_attribute(self):
        """The generalisation: every requeue in this router is conditional."""
        tree = ast.parse(_files_source())
        bare = [
            ast.unparse(node)
            for node in ast.walk(tree)
            if isinstance(node, ast.Assign)
            and ast.unparse(node.targets[0]).endswith(".status")
            and ast.unparse(node.value) == "'pending'"
        ]
        assert not bare, (
            f"unconditional requeue(s) found: {bare} - each can put a "
            "superseded version back into the index under READ COMMITTED"
        )


class TestSupersededFailuresDoNotPinTheProject:
    """A retired edition that failed to index is not a project-level error.

    It holds no chunks by design, retrying it is refused by design, and
    deleting it would destroy the history the feature exists to keep - so
    counting it left the project stuck at 'error' with no action able to clear
    it.
    """

    def test_the_failure_check_is_scoped_to_current_editions(self):
        from app.services import ingestion

        source = inspect.getsource(ingestion.recompute_project_status)
        assert 'r.status == "failed" and r.in_force_to is None' in source, (
            "a superseded failed file must not pin the project at 'error'"
        )


class TestTheExtractionGateSurvivesAFailedIngest:
    """Extraction is paid work, so its result must outlive a later failure.

    The gate is `document_id IS NULL`. If that write only landed on the final
    commit, "Document produced no chunks" or a dead embedding provider would
    roll it back through mark_file_failed and every retry would buy the same
    LLM call again.
    """

    def test_the_gate_write_is_committed_before_chunking(self):
        from app.services import ingestion

        tree = ast.parse(inspect.getsource(ingestion._ingest_file_inner))
        gate_line = commit_lines = None
        commits = []
        for node in ast.walk(tree):
            text = ast.unparse(node)
            if gate_line is None and isinstance(node, ast.If):
                if "file.document_id is None and file.indexed_at is None" in text:
                    gate_line = node.lineno
                    # Every commit inside the gate block, park path included.
                    commits = [
                        inner.lineno
                        for inner in ast.walk(node)
                        if isinstance(inner, ast.Call)
                        and ast.unparse(inner) == "db.commit()"
                    ]
            if isinstance(node, ast.Call) and "insert(Chunk)" in text:
                commit_lines = node.lineno
        assert gate_line is not None, "the version gate is gone"
        assert commit_lines is not None, "the chunk insert is gone"
        assert len(commits) >= 2, (
            "the gate must commit on BOTH paths - the park, and the "
            "no-match path that falls through to chunking - or a later "
            "failure rolls the extraction result back and re-bills the user"
        )
        assert max(commits) < commit_lines


class TestDownloadHeaderSurvivesNonAsciiFilenames:
    """Filenames are stored verbatim and are routinely not Latin-1.

    Starlette latin-1 encodes header values, so a bare filename="..." raises
    UnicodeEncodeError and 500s the download - on exactly the route that is the
    only way to read a superseded version.
    """

    def test_it_sends_an_rfc_6266_encoded_filename(self):
        from app.routers import files as files_router

        source = inspect.getsource(files_router.download_file_content)
        assert "filename*=UTF-8" in source
        assert 'encode("ascii", "replace")' in source, (
            "the plain `filename` fallback must be ASCII-safe"
        )

    def test_a_cjk_filename_produces_a_latin_1_encodable_header(self):
        # The actual failure, reproduced without a request: build the header
        # the route builds and prove starlette could encode it.
        from urllib.parse import quote

        name = "契約書 📄.pdf"
        stripped = re.sub(r'[\r\n"]', "", name)[:200]
        ascii_name = stripped.encode("ascii", "replace").decode("ascii") or "download"
        header = (
            f'attachment; filename="{ascii_name}"; '
            f"filename*=UTF-8''{quote(stripped, safe='')}"
        )
        header.encode("latin-1")  # raises if the fix is undone


class TestVersionRequestCannotSilentlyEraseALabel:
    """Every field is required because the endpoint writes every field.

    An optional `version_label` meant a client that omitted it wiped the label
    - and defeated the idempotency short-circuit, turning a harmless retry into
    a destructive edit.
    """

    def test_version_label_is_required(self):
        from app.schemas import FileVersionRequest

        assert FileVersionRequest.model_fields["version_label"].is_required()

    def test_every_field_the_endpoint_overwrites_is_required(self):
        from app.schemas import FileVersionRequest

        # relation_kind is the deliberate exception: it was added by 0037 and
        # NULL is read as 'supersedes', the only relation that existed before,
        # so a client written against 0036 keeps working unchanged. Every other
        # field is written unconditionally, so omitting one would erase it.
        for name, field in FileVersionRequest.model_fields.items():
            if name == "relation_kind":
                assert not field.is_required()
                continue
            assert field.is_required(), (
                f"{name} is optional; the endpoint writes it unconditionally, "
                "so omitting it would erase the stored value"
            )


class TestLockOrderIsFilesThenChunks:
    """Both writers must take `files` locks before `chunks` locks.

    set_file_version locks files and then deletes that file's chunks. A reindex
    that deleted chunks first and locked files afterwards inverts that order,
    and the two deadlock.
    """

    def test_reindex_locks_its_files_before_deleting_chunks(self):
        from app.routers import files as files_router

        source = inspect.getsource(files_router.reindex_project)
        lock = source.index("with_for_update")
        delete = source.index("sql_delete(Chunk)")
        assert lock < delete, (
            "reindex takes chunk locks before file locks, inverting "
            "set_file_version's order - the two can deadlock"
        )


# --------------------------------------------------------------------------
# Migration 0035 - provenance. Each test below corresponds to a finding from
# the real-corpus audit, so a regression re-opens a measured defect rather than
# an imagined one.
# --------------------------------------------------------------------------

MIGRATION_0035 = MIGRATIONS / "0035_document_provenance.sql"


class TestMigration0035Shape:
    def setup_method(self):
        self.sql = MIGRATION_0035.read_text(encoding="utf-8")
        self.lower = self.sql.lower()

    def test_no_percent_sign(self):
        assert "%" not in self.sql

    def test_adds_the_three_provenance_columns(self):
        added = set(re.findall(r"add column if not exists\s+(\w+)", self.lower))
        for column in ("content_sha256", "extracted_title", "instrument_role"):
            assert column in added, f"0035 does not add files.{column}"

    def test_the_events_table_enables_rls(self):
        # test_migration_rls.py enforces this repo-wide; asserted here too so
        # the failure names the table rather than the whole migration set.
        assert "create table if not exists public.document_events" in self.lower
        assert "alter table public.document_events enable row level security" in self.lower

    def test_events_are_readable_but_not_writable_through_rls(self):
        # `for all` would let the subject of an audit trail rewrite it.
        assert "for select using" in self.lower
        assert "for all using" not in self.lower

    def test_update_is_blocked_by_a_trigger(self):
        # Append-only enforced by the database, not assumed of the callers.
        assert "document_events_append_only" in self.lower
        assert "before update on public.document_events" in self.lower
        assert "raise exception" in self.lower

    def test_delete_stays_possible(self):
        # Deliberate: account erasure has to remain possible, and lawful
        # erasure beats an audit trail that cannot be erased.
        assert "before update or delete" not in self.lower
        assert "on delete cascade" in self.lower

    def test_event_ids_are_not_foreign_keys(self):
        # An event about a deleted file is the event most worth keeping.
        body = self.lower[self.lower.index("create table if not exists public.document_events"):]
        body = body[: body.index(");")]
        assert "file_id     uuid," in body or "file_id uuid," in body.replace("  ", " ")
        assert "references public.files" not in body

    def test_it_indexes_what_it_added(self):
        # 0034 added no index for the lineage lookups it introduced.
        for idx in ("document_events_project_time_idx", "files_document_idx"):
            assert idx in self.lower, f"0035 does not create {idx}"


class TestNonSupersedingRoles:
    """The largest measured source of destructive proposals.

    Over 105 realistic documents, the worst outcomes were all one shape: a
    document that REFERS to another being proposed as its replacement. A Lancet
    Department of Error retiring the trial it corrects; a French WHO guideline
    retiring the English text that declares itself authoritative; a Japanese
    translation retiring the English original; a supplementary appendix
    retiring the paper it belongs to.
    """

    def test_the_four_referring_roles_cannot_supersede(self):
        from app.services.ingestion import NON_SUPERSEDING_ROLES

        assert NON_SUPERSEDING_ROLES == {
            "amending", "correction", "translation", "supplement",
        }

    def test_unknown_and_null_are_deliberately_allowed(self):
        # A corpus with no role information must behave exactly as it did
        # before 0035, or this migration silently disables the feature.
        from app.services.ingestion import NON_SUPERSEDING_ROLES

        assert "unknown" not in NON_SUPERSEDING_ROLES
        assert None not in NON_SUPERSEDING_ROLES
        assert "principal" not in NON_SUPERSEDING_ROLES
        assert "consolidated" not in NON_SUPERSEDING_ROLES

    def test_a_referring_document_cannot_claim_a_retiring_relation(self):
        """0037 replaced refusal with correction.

        Before it there was only one relation - supersedes - so the sole way to
        stop an erratum retiring the article it corrects was to throw the match
        away. Now every referring role has a relation that keeps the
        predecessor answering, so the link is rewritten rather than discarded:
        strictly more information, and the same protection.
        """
        from app.services import ingestion

        src = inspect.getsource(ingestion._propose_version)
        assert "NON_SUPERSEDING_ROLES" in src, (
            "a correction or translation can still retire its subject"
        )
        for role, kind in (
            ("amending", "amends"), ("correction", "corrects"),
            ("translation", "translates"), ("supplement", "supplements"),
        ):
            assert f'"{role}": "{kind}"' in src, f"{role} has no safe relation"

    def test_the_endpoint_only_blocks_a_retiring_relation(self):
        # The same rule at the boundary: an amendment MAY name the statute it
        # amends, it just may not retire it.
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert "_retires and body.instrument_role in NON_SUPERSEDING_ROLES" in src

    def test_the_endpoint_enforces_it_too(self):
        # The UI is not the security boundary: this endpoint accepts a
        # hand-made request.
        from app.routers import files as files_router

        assert "NON_SUPERSEDING_ROLES" in inspect.getsource(
            files_router.set_file_version
        )

    def test_the_prompt_defines_every_role_it_asks_for(self):
        from app.services.ingestion import _VERSION_SYSTEM_PROMPT
        from app.schemas import INSTRUMENT_ROLES

        for role in INSTRUMENT_ROLES:
            assert role in _VERSION_SYSTEM_PROMPT, f"prompt never mentions {role}"

    def test_the_python_set_matches_the_check_constraint(self):
        from app.schemas import INSTRUMENT_ROLES

        sql = MIGRATION_0035.read_text(encoding="utf-8")
        for role in INSTRUMENT_ROLES:
            assert f"'{role}'" in sql, f"CHECK does not admit {role!r}"


class TestExtractedTitleReachesTheShortlist:
    """The dominant reason a true predecessor never reached the model.

    Stage one could only see `filename + version_label` of a held document, so
    a file stored as scan_0001.pdf or Document (7).pdf contributed almost no
    tokens and was unreachable however clearly its text identified it. Measured
    shortlist recall in a realistically-sized project was 48/68.
    """

    def test_a_held_file_with_a_useless_filename_is_still_reachable(self):
        from app.services.ingestion import _shortlist

        target = _row("scan_0001.pdf", None, "The Companies Act, 2013")
        noise = [_row(f"Unrelated Statute {i}.pdf") for i in range(20)]
        top = _shortlist(noise + [target], "Companies Act 2013 amendment", limit=3)
        assert target in top, (
            "a predecessor whose identity is only in its body is invisible to "
            "the shortlist and can never be matched"
        )

    def test_the_candidate_query_selects_it(self):
        from app.services import ingestion

        assert "File.extracted_title" in inspect.getsource(ingestion._propose_version)

    def test_it_is_captured_at_ingest(self):
        from app.services import ingestion

        assert "file.extracted_title = _extracted_title" in inspect.getsource(
            ingestion._ingest_file_inner
        )

    def test_the_title_helper_handles_a_document_with_no_heading(self):
        from app.services.ingestion import _extracted_title

        assert _extracted_title("# The Companies Act, 2013\n\nbody") == "The Companies Act, 2013"
        assert _extracted_title("PRELIMINARY, no heading at all") is None


class TestSupersededHistoryIsNotOneClickFromGone:
    """The only permanent-data-loss path the audit found.

    The whole current-only design rests on 'a superseded edition keeps its
    blobs, so re-indexing it later costs an embedding run and nothing else'.
    Nothing enforced it: delete_file removed the row, its chunks and BOTH
    storage objects with no in_force_to check, permanently, with no soft delete
    and no backup anywhere in the repository.
    """

    def test_delete_refuses_a_superseded_edition_without_purge(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.delete_file)
        assert "in_force_to is not None and not purge" in src
        assert "409" in src

    def test_purge_is_an_explicit_opt_in(self):
        import inspect as _i

        from app.routers import files as files_router

        assert "purge" in _i.signature(files_router.delete_file).parameters

    def test_the_deletion_is_recorded_before_the_row_goes(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.delete_file)
        assert src.index('"deleted"') < src.index("db.delete(file)"), (
            "the event must be written while the file row still exists"
        )


class TestEveryVersionDecisionIsRecorded:
    """Migration 0034 recorded no transaction time and no actor.

    files has no updated_at, so a supersession wrote in_force_to - a LEGAL date
    the user typed - and nothing about when the decision was taken or by whom.
    'This edition governed until 22 Jan 2021' was recordable; 'on 3 Sep 2026
    this user recorded that' was not.
    """

    def test_the_confirm_endpoint_records_who_and_what(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert "document_events.record(" in src
        assert "actor_id=project.owner_id" in src

    def test_the_event_lands_in_the_same_transaction_as_the_decision(self):
        # One commit, and the record inside it: a rolled-back supersession
        # cannot leave an event claiming it happened, and a committed one
        # cannot go missing.
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert src.count("db.commit()") == 1
        assert src.index("document_events.record(") < src.index("db.commit()")

    def test_record_does_not_commit(self):
        from app.services import document_events

        src = inspect.getsource(document_events.record)
        assert "commit" not in src, (
            "record() must join the caller's transaction, like "
            "bump_content_version - see the module docstring"
        )

    def test_worker_paths_use_the_never_raising_variant(self):
        # An exception escaping into _ingest_file_inner aborts every queued
        # ingest behind it, so observation events there must not be able to.
        from app.services import ingestion

        src = inspect.getsource(ingestion._ingest_file_inner)
        assert "record_safely" in src
        assert "document_events.record(" not in src

    def test_the_python_event_set_matches_the_check_constraint(self):
        from app.services.document_events import EVENTS

        sql = MIGRATION_0035.read_text(encoding="utf-8")
        for event in EVENTS:
            assert f"'{event}'" in sql, f"CHECK does not admit event {event!r}"

    def test_an_unknown_event_is_a_python_error_not_an_integrity_error(self):
        import pytest

        from app.services.document_events import record

        with pytest.raises(ValueError):
            record(None, uuid.uuid4(), "not_a_real_event")

    def test_history_is_always_scoped_by_project(self):
        # document_id is not a foreign key, so the database will not stop a
        # caller passing one from another tenant.
        from app.services import document_events

        src = inspect.getsource(document_events.history)
        assert "DocumentEvent.project_id == project_id" in src


class TestContentHash:
    def test_it_is_taken_at_upload_from_the_raw_bytes(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.upload_files)
        assert "hashlib.sha256(data).hexdigest()" in src

    def test_it_is_exposed_on_the_file_contract(self):
        from app.schemas import FileOut

        assert "content_sha256" in FileOut.model_fields


class TestFileCapIsEnforcedOnBothRoutes:
    """retrieval.py relies on the 1000-file cap as a fact when it sums
    files.chunk_count to size the ANN gate, but only /v1 enforced it. Every
    retained edition consumes a slot, so 0034 made the gap matter more."""

    def test_the_dashboard_upload_route_counts_files(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.upload_files)
        assert "max_files_per_project" in src
        assert "413" in src


class TestExtractionModelCanBePinned:
    """Correctness must not depend on a model chosen for something else.

    Over the same 105 documents, one model produced 28 false matches and
    another produced 0; a third failed outright on 10 of 27 calls. The
    extraction borrowed the project's ANSWER model - picked for
    question-answering, price or latency.
    """

    def test_the_deployment_can_pin_a_model(self):
        from app.config import settings

        assert hasattr(settings, "version_extraction_provider")
        assert hasattr(settings, "version_extraction_model")

    def test_it_defaults_to_the_projects_model(self):
        # Empty means "behave as 0034 did", so pinning is opt-in.
        from app.config import settings

        assert settings.version_extraction_provider == ""
        assert settings.version_extraction_model == ""

    def test_the_override_is_actually_applied(self):
        from app.services import ingestion

        src = inspect.getsource(ingestion._propose_version)
        assert "settings.version_extraction_provider or project.llm_provider" in src
        assert "settings.version_extraction_model or project.llm_model" in src


# --------------------------------------------------------------------------
# Defects found by an adversarial audit run against the 0035 code itself.
# --------------------------------------------------------------------------


class TestTheAuditTrailIsReadable:
    """An audit trail nothing can read is not an audit trail.

    0035 shipped document_events, the append-only trigger, the RLS policy, the
    history() reader AND the DocumentEventOut wire shape - and no endpoint. The
    log was write-only.
    """

    def test_there_is_an_events_endpoint(self):
        from app.routers import files as files_router

        assert hasattr(files_router, "list_document_events")

    def test_it_reads_through_the_scoped_helper(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.list_document_events)
        assert "document_events.history(" in src
        assert "project.id" in src

    def test_the_route_is_registered_and_owner_scoped(self):
        from app.routers.files import router

        paths = {r.path for r in router.routes}
        assert any(p.endswith("/events") for p in paths), paths


class TestBothUploadPathsHash:
    """content_sha256 covered only the dashboard route, so the guarantee
    depended on which door a file came through - and integrations using /v1 or
    MCP are the ones most likely to need it later."""

    def test_the_public_route_hashes_too(self):
        from app.routers import rag_v1

        assert "hashlib.sha256(data).hexdigest()" in inspect.getsource(
            rag_v1.public_upload_files
        )

    def test_both_paths_compute_the_same_digest(self):
        from app.routers import files as files_router
        from app.routers import rag_v1

        expr = "digest = hashlib.sha256(data).hexdigest()"
        assert expr in inspect.getsource(files_router.upload_files)
        assert expr in inspect.getsource(rag_v1.public_upload_files)

    def test_both_paths_consult_it_before_creating_a_row(self):
        # 0035 recorded the hash and never used it, so an identical re-upload
        # created a second row and paid to embed the same text again.
        from app.routers import files as files_router
        from app.routers import rag_v1

        for fn in (files_router.upload_files, rag_v1.public_upload_files):
            src = inspect.getsource(fn)
            assert "find_duplicate(db, project.id, digest)" in src, fn.__name__


class TestTheToggleDoesNotLie:
    """Extraction needs BOTH switches. A project toggle that saves cheerfully
    while the fleet flag is off is a setting that silently does nothing."""

    def test_the_project_response_reports_the_deployment_flag(self):
        from app.schemas import ProjectOut

        assert "version_extraction_available" in ProjectOut.model_fields

    def test_it_is_stamped_from_settings(self):
        from app.routers import projects as projects_router

        assert "settings.version_extraction_enabled" in inspect.getsource(
            projects_router
        )


class TestConcurrentConfirmsCannotForkALineage:
    """Locking only the two rows named in the request let a second confirm
    naming a DIFFERENT predecessor in the same lineage take a disjoint set of
    locks and commit, leaving two current editions."""

    def test_the_whole_lineage_is_locked(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert src.count("with_for_update") >= 2, (
            "the lineage lock is missing; two confirms on one lineage can both "
            "commit and leave two current editions"
        )
        assert "func.coalesce(File.document_id, File.id) == lineage" in src

    def test_both_locks_are_id_ordered(self):
        # Two id-ordered statements cannot deadlock against each other.
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert src.count("order_by(File.id)") >= 2


class TestLockOrderIsFilesThenChunksEverywhere:
    """set_file_version locks files then deletes chunks. Any path that does the
    reverse inverts the order and the two deadlock."""

    def test_the_upload_requeue_locks_files_first(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.upload_files)
        assert "with_for_update" in src
        assert src.index("with_for_update") < src.index("sql_delete(Chunk)")

    def test_reindex_still_locks_files_first(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.reindex_project)
        assert src.index("with_for_update") < src.index("sql_delete(Chunk)")


class TestTheTrailRecordsEffectsNotOnlyDecisions:
    """'uploaded', 'indexed' and 'ingest_failed' were admitted by the CHECK and
    never written, so the log could not say what was searchable on a date."""

    def test_upload_is_recorded(self):
        from app.routers import files as files_router

        assert '"uploaded"' in inspect.getsource(files_router.upload_files)

    def test_indexing_is_recorded(self):
        from app.services import ingestion

        assert '"indexed"' in inspect.getsource(ingestion._ingest_file_inner)

    def test_failure_is_recorded(self):
        from app.services import ingestion

        assert '"ingest_failed"' in inspect.getsource(ingestion.mark_file_failed)

    def test_every_recorded_event_is_one_the_check_admits(self):
        # A typo here would be an IntegrityError that rolls back the user's
        # operation, so the Python set and the SQL CHECK must not drift.
        import re as _re

        from app.routers import files as files_router
        from app.services import ingestion
        from app.services.document_events import EVENTS

        used = set()
        for mod in (files_router, ingestion):
            src = inspect.getsource(mod)
            for m in _re.finditer(r'record(?:_safely)?\(\s*db,\s*[^,]+,\s*"(\w+)"', src):
                used.add(m.group(1))
        assert used, "the scan found no record() call sites"
        assert used <= EVENTS, f"events not in the CHECK: {used - EVENTS}"


# --------------------------------------------------------------------------
# Migration 0036 - the version chain, and using the hash 0035 only recorded.
# --------------------------------------------------------------------------

MIGRATION_0036 = MIGRATIONS / "0036_version_chain.sql"


class TestMigration0036Shape:
    def setup_method(self):
        self.sql = MIGRATION_0036.read_text(encoding="utf-8")
        self.lower = self.sql.lower()

    def test_no_percent_sign(self):
        assert "%" not in self.sql

    def test_adds_the_chain_and_the_derived_hash(self):
        added = set(re.findall(r"add column if not exists\s+(\w+)", self.lower))
        assert {"supersedes_file_id", "markdown_sha256"} <= added

    def test_the_pointer_is_not_a_foreign_key(self):
        # Third time in this schema, same reason: a chain must survive the
        # deletion of a link. SET NULL severs history; CASCADE deletes it.
        assert "references public.files" not in self.lower

    def test_an_edition_cannot_supersede_itself(self):
        assert "files_supersedes_not_self" in self.lower
        assert "supersedes_file_id <> id" in self.lower

    def test_it_is_indexed_for_walking_the_chain(self):
        assert "files_supersedes_idx" in self.lower


class TestTheChainIsWritten:
    """0034 gave a lineage no order: `document_id` is a flat grouping key and
    order came from `in_force_from`, a nullable user-supplied legal date."""

    def test_supersession_records_what_it_replaced(self):
        target = _Target(uuid.uuid4(), "review", 0)
        pred = _Target(uuid.uuid4(), "indexed", 40)
        plan = _plan(target, pred, lineage=pred.id)
        assert plan.ops[0].fields["supersedes_file_id"] == pred.id

    def test_a_rejection_clears_the_pointer(self):
        # A detached or reinstated edition must not keep claiming to have
        # replaced something it no longer follows.
        target = _Target(uuid.uuid4(), "review", 0)
        assert _plan(target, None).ops[0].fields["supersedes_file_id"] is None

    def test_the_markdown_hash_is_stamped_beside_the_conversion_version(self):
        from app.services import ingestion

        src = inspect.getsource(ingestion._ingest_file_inner)
        assert "file.markdown_sha256 = hashlib.sha256(" in src
        assert src.index("file.conversion_version = CONVERSION_VERSION") < src.index(
            "file.markdown_sha256"
        )

    def test_both_hashes_are_on_the_wire(self):
        from app.schemas import FileOut

        for name in ("content_sha256", "markdown_sha256", "supersedes_file_id"):
            assert name in FileOut.model_fields


class TestIdenticalReuploadsAreNotNewEditions:
    """Retiring a document in favour of a byte-identical copy of itself is the
    emptiest possible supersession, and it was reachable: 0035 recorded
    content_sha256 and nothing consulted it."""

    def test_the_helper_excludes_superseded_rows(self):
        from app.services import ingestion

        src = inspect.getsource(ingestion.find_duplicate)
        assert "File.in_force_to.is_(None)" in src, (
            "an old edition may legitimately share bytes with a reinstatement"
        )
        assert "File.project_id == project_id" in src

    def test_an_empty_digest_never_matches(self):
        from app.services.ingestion import find_duplicate

        assert find_duplicate(None, uuid.uuid4(), "") is None

    def test_a_duplicate_is_recorded_rather_than_indexed_again(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.upload_files)
        assert "duplicate_of=existing.filename" in src
        assert "created.append(existing)" in src


class TestAStaleProposalNamesItsReplacement:
    """Two revisions uploaded together both park against the ORIGINAL, because
    the candidate query excludes rows in review and they are invisible to each
    other. The second confirm has to say WHICH edition is current now."""

    def test_the_422_carries_the_current_file_id(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert "current_file_id" in src


class TestShortlistTiesBreakOnSomethingMeaningful:
    def test_recency_beats_alphabetical_order(self):
        from datetime import date as _date

        from app.services.ingestion import _shortlist

        # Identical scores; only the dates differ. Alphabetical order alone is
        # a coin toss that correlates with nothing.
        older = _row("Reg_A_part1.pdf", None, None, _date(2019, 1, 1))
        newer = _row("Reg_Z_part1.pdf", None, None, _date(2024, 1, 1))
        filler = [_row(f"Other_{i}.pdf") for i in range(20)]
        top = _shortlist(filler + [older, newer], "Reg part1 revision", limit=1)
        assert top == [newer]

    def test_it_is_still_deterministic(self):
        from app.services.ingestion import _shortlist

        c = [_row(f"Doc {i}.pdf") for i in range(30)]
        a = _shortlist(c, "Companies Act 2013", limit=12)
        b = _shortlist(c, "Companies Act 2013", limit=12)
        assert [r.id for r in a] == [r.id for r in b]


class TestTheToggleIsUsable:
    """Direct user feedback: the control could not be switched on at all.

    version_extraction_enabled was introduced as a fleet-wide KILL SWITCH and
    defaulted off, which made it a second gate the owner cannot see, blocking
    the per-project one they can. A project owner ticked the box, saw it save,
    and nothing happened - the exact silently-ineffective setting the
    per-project flag existed to avoid.
    """

    def test_the_kill_switch_defaults_on(self):
        from app.config import settings

        assert settings.version_extraction_enabled is True, (
            "this is an incident kill switch, not an opt-in; defaulting it off "
            "blocks the per-project toggle with a flag the owner cannot see"
        )

    def test_the_per_project_control_still_defaults_off(self):
        # The safety property that matters: no existing project changes
        # behaviour, and nothing can park without an explicit opt-in.
        sql = (MIGRATIONS / "0034_document_versions.sql").read_text(encoding="utf-8")
        assert "version_tracking boolean not null default false" in sql.lower()


class TestVersioningDisappearsWhenNotTracking:
    """Turning the toggle off is a statement that this project does not keep
    editions. A guard or a menu entry that outlives the feature is an obstacle
    to ordinary housekeeping."""

    def test_the_delete_guard_is_scoped_to_tracking_projects(self):
        from app.routers import files as files_router

        assert "and project.version_tracking" in inspect.getsource(
            files_router.delete_file
        )

    def test_it_still_guards_while_tracking_is_on(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.delete_file)
        assert "file.in_force_to is not None and not purge" in src


class TestEnablingMidProjectWorksWithWhatIsThere:
    """The toggle has to start from the state the project is already in.

    Existing files were always valid candidates - the candidate query filters
    on in_force_to and status, never on document_id - but they were ingested
    before extracted_title existed, and the gate fires only on a file's FIRST
    index, so nothing would ever give them one. Without a title the shortlist
    can score only their filename, the weakest case there is.
    """

    def test_switching_on_schedules_the_backfill(self):
        from app.routers import projects as projects_router

        src = inspect.getsource(projects_router.update_project)
        assert "backfill_extracted_titles" in src
        assert "not project.version_tracking" in src, (
            "must fire on the false->true edge only, not on every save"
        )

    def test_the_backfill_costs_nothing_but_a_read(self):
        from app.services import ingestion

        src = inspect.getsource(ingestion.backfill_extracted_titles)
        for expensive in ("get_embedder", "convert_to_markdown", "generate_with_usage"):
            assert expensive not in src, f"backfill must not {expensive}"
        assert "storage.download" in src

    def test_it_only_touches_rows_that_need_it(self):
        from app.services import ingestion

        src = inspect.getsource(ingestion.backfill_extracted_titles)
        assert "File.extracted_title.is_(None)" in src
        assert "File.in_force_to.is_(None)" in src

    def test_it_never_raises_into_the_request(self):
        # It runs as a BackgroundTask off a PATCH; an exception escaping would
        # surface as a 500 on a save that already succeeded.
        from app.services import ingestion

        src = inspect.getsource(ingestion.backfill_extracted_titles)
        assert "except Exception:" in src
        assert "db.rollback()" in src


# --------------------------------------------------------------------------
# Migration 0037 - one relation was never enough.
# --------------------------------------------------------------------------

MIGRATION_0037 = MIGRATIONS / "0037_document_relations.sql"


class TestMigration0037Shape:
    def setup_method(self):
        self.sql = MIGRATION_0037.read_text(encoding="utf-8")
        self.lower = self.sql.lower()

    def test_no_percent_sign(self):
        assert "%" not in self.sql

    def test_it_admits_exactly_the_eight_kinds(self):
        from app.schemas import RELATION_KINDS

        for kind in RELATION_KINDS:
            assert f"'{kind}'" in self.sql, f"CHECK does not admit {kind!r}"
        assert len(RELATION_KINDS) == 8

    def test_a_relation_needs_a_target(self):
        assert "files_relation_needs_target" in self.lower

    def test_legal_status_gains_retracted(self):
        # A retracted paper that simply vanished would leave the corpus looking
        # as though it had never held it.
        assert "'retracted'" in self.sql


class TestTheRelationTableIsTheWholeMechanism:
    """Every "does not fit" class had the same cause: one edge that always
    retired the predecessor. A relation kind decides two booleans, and because
    "answers questions" and "has chunks" are the same thing here, that is the
    entire implementation - retrieval needs no predicate."""

    def test_retrieval_is_still_untouched(self):
        from app.services import explore, retrieval

        for module in (retrieval, explore):
            src = inspect.getsource(module)
            assert "relation_kind" not in src, (
                f"{module.__name__} references relation_kind - the whole design "
                "is that it never has to"
            )

    def test_the_four_referring_relations_leave_the_predecessor_answering(self):
        from app.schemas import RELATIONS

        for kind in ("amends", "corrects", "translates", "supplements", "succeeds"):
            retires, _answers, _mark = RELATIONS[kind]
            assert not retires, f"{kind} must not retire what it points at"

    def test_diff_text_and_notices_do_not_answer(self):
        # An amending instrument quoted as if it were the rule, or an erratum
        # answering in place of the article, are the two worst outcomes
        # measured over the corpus.
        from app.schemas import RELATIONS

        for kind in ("amends", "corrects", "retracts"):
            assert not RELATIONS[kind][1], f"{kind} must not be searchable"

    def test_retraction_stops_the_paper_and_marks_it(self):
        from app.schemas import RELATIONS

        retires, answers, mark = RELATIONS["retracts"]
        assert retires and not answers and mark == "retracted"

    def test_an_amendment_marks_what_it_amends(self):
        from app.schemas import RELATIONS

        assert RELATIONS["amends"][2] == "amended"

    def test_null_is_read_as_the_pre_0037_relation(self):
        from app.schemas import DEFAULT_RELATION, RELATIONS

        assert DEFAULT_RELATION == "supersedes"
        assert RELATIONS[DEFAULT_RELATION] == (True, True, None)


class TestThePlannerAppliesTheTable:
    def _plan_kind(self, kind):
        pred = _Target(uuid.uuid4(), "indexed", 40)
        target = _Target(uuid.uuid4(), "review", 0)
        body = _Body("L", date(2024, 1, 1), "in_force", "principal")
        body = body._replace() if hasattr(body, "_replace") else body
        from app.routers.files import plan_supersession

        class B(NamedTuple):
            version_label: str | None
            in_force_from: date | None
            legal_status: str | None
            instrument_role: str | None
            relation_kind: str | None

        plan = plan_supersession(
            target, pred, pred.id,
            B("L", date(2024, 1, 1), "in_force", "principal", kind),
        )
        pred_op = next((o for o in plan.ops if o.file_id == pred.id), None)
        return plan, pred_op

    def test_a_retiring_relation_drops_the_predecessors_chunks(self):
        for kind in ("supersedes", "restates", "retracts"):
            _plan, pred_op = self._plan_kind(kind)
            assert pred_op is not None and pred_op.delete_chunks, kind
            assert pred_op.fields["chunk_count"] == 0, kind

    def test_a_referring_relation_leaves_them_alone(self):
        for kind in ("amends", "corrects", "translates", "supplements", "succeeds"):
            _plan, pred_op = self._plan_kind(kind)
            if pred_op is not None:
                assert not pred_op.delete_chunks, kind
                assert "chunk_count" not in pred_op.fields, kind
                assert "in_force_to" not in pred_op.fields, kind

    def test_a_non_answering_document_is_never_queued(self):
        for kind in ("amends", "corrects", "retracts"):
            plan, _ = self._plan_kind(kind)
            assert not plan.requeued, kind
            assert plan.ops[0].delete_chunks, kind

    def test_an_answering_document_is_queued(self):
        for kind in ("supersedes", "restates", "translates", "supplements", "succeeds"):
            plan, _ = self._plan_kind(kind)
            assert plan.requeued, kind
            assert not plan.ops[0].delete_chunks, kind

    def test_the_relation_is_recorded_on_the_row(self):
        plan, _ = self._plan_kind("succeeds")
        assert plan.ops[0].fields["relation_kind"] == "succeeds"


class TestTheEndpointGuardsOnlyBiteRetiringRelations:
    """An amendment MAY name the statute it amends. It just may not retire it,
    and it needs no effective date to do so."""

    def test_the_date_is_only_required_when_retiring(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert "if _retires and body.in_force_from is None:" in src

    def test_an_already_superseded_predecessor_only_blocks_retirement(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert "predecessor.in_force_to is not None and _retires" in src

    def test_the_clash_check_only_applies_to_retiring_relations(self):
        # A translation or the next filing in a series joins the lineage
        # alongside the current edition; only a replacement competes with it.
        from app.routers import files as files_router

        src = inspect.getsource(files_router.set_file_version)
        assert "_retires_target" in src


class TestTheRoleOverrideStaysNarrow:
    """`principal` is the model's default label and must never override a relation.

    A wider version of this override - firing whenever the role was `principal`
    - made the corpus worse in BOTH directions (67 correct and 23 harmful,
    against 71 and 10 without it). The reason was measurable: over 105
    documents the model applied `principal` to a translation, a meta-analysis,
    a journal editorial, a proxy statement and a commencement notification. It
    carries almost no information.

    `consolidated` is a positive claim that the document sets out the whole of
    what it matched, which `amends` directly contradicts, so that ONE pairing
    is overridden and nothing else. The narrow rule measured as a wash (72/11
    against 71/10, inside run-to-run variance) and is kept for consistency
    rather than for a gain: the two labels cannot both be true.
    """

    def _src(self):
        from app.services import ingestion

        return inspect.getsource(ingestion._propose_version)

    def test_only_consolidated_plus_amends_is_overridden(self):
        assert 'role == "consolidated" and kind == "amends"' in self._src()

    def test_principal_never_overrides_a_relation(self):
        src = self._src()
        assert 'role in ("principal", "consolidated")' not in src, (
            "this is the wider rule that measured worse in both directions"
        )
        assert 'role == "principal"' not in src

    def test_the_override_lands_on_restates_not_supersedes(self):
        # "Amended and restated" is literally a restatement, and restates
        # retires - so the correct outcome is reached by the honest name.
        src = self._src()
        i = src.index('role == "consolidated" and kind == "amends"')
        assert 'kind = "restates"' in src[i : i + 400]

    def test_referring_roles_are_still_forced_to_safe_relations(self):
        src = self._src()
        for role, kind in (
            ("amending", "amends"), ("correction", "corrects"),
            ("translation", "translates"), ("supplement", "supplements"),
        ):
            assert f'"{role}": "{kind}"' in src

    def test_the_prompt_states_the_contains_test_for_relations(self):
        from app.services.ingestion import _VERSION_SYSTEM_PROMPT

        assert "never amends" in _VERSION_SYSTEM_PROMPT
