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


def _row(filename, label=None):
    return _Row(uuid.uuid4(), filename, label)


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
        matched, label, from_date, status = self._parse(
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
            assert self._parse(reply) == (None, None, None, None), reply


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
