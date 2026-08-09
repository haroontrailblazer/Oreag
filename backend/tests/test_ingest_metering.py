"""Ingest and Matryoshka restore must both report their embedding.

These are the two paths that run OUTSIDE an HTTP request, so the usage
middleware never covers them:

  * ingest happens on a daemon worker thread long after the upload route
    returned, which is why a UI file upload wrote vectors and recorded nothing;
  * a grow-back restores vectors from the archive and calls no provider at all,
    so there is no usage to observe - only a saving to replay.
"""
import inspect

from app.services import ingestion


class _FakeSession:
    """Just enough session for _record_ingest_usage's lookups."""

    def get(self, model, ident):
        import types

        return types.SimpleNamespace(
            id=ident, project_id="p", embedding_tokens=None, owner_id="o"
        )

    def commit(self):
        pass

    def close(self):
        pass


class TestIngestOpensItsOwnScope:
    def test_ingest_file_wraps_the_work_in_an_embedding_scope(self):
        """The middleware cannot reach a worker thread; ingest must scope
        itself or every uploaded file embeds for free on paper."""
        src = inspect.getsource(ingestion.ingest_file)
        assert "embedding_usage.scope()" in src
        assert "_record_ingest_usage" in src

    def test_usage_is_recorded_in_a_finally(self):
        """A file that fails halfway has still paid for what it embedded."""
        src = inspect.getsource(ingestion.ingest_file)
        finally_at = src.index("finally:")
        assert src.index("_record_ingest_usage") > finally_at

    def test_the_file_is_stamped_for_a_future_restore(self):
        """Without files.embedding_tokens a grow-back cannot report its saving
        - the cost cannot be recomputed without doing the avoided work."""
        src = inspect.getsource(ingestion._record_ingest_usage)
        assert "file.embedding_tokens" in src

    def test_unmeasured_ingest_writes_nothing(self):
        """A local embedder reports no tokens; that must stay NULL, not 0."""
        src = inspect.getsource(ingestion._record_ingest_usage)
        assert "embedding.total.known" in src
        assert "embedding.llm_total.known" in src

    def test_captioning_alone_is_enough_to_write_a_row(self, monkeypatch):
        """An audio file spends on transcription and embeds a short transcript;
        an image-heavy PDF spends most of its money on captioning. Requiring
        BOTH sides would drop whichever one actually carried the cost."""
        from app.providers.base import TokenUsage
        from app.services import embedding_usage

        written = []
        monkeypatch.setattr(ingestion, "record_usage",
                            lambda db, **kw: written.append(kw))
        monkeypatch.setattr(ingestion, "SessionLocal", lambda: _FakeSession())

        with embedding_usage.scope() as acc:
            embedding_usage.record_llm(TokenUsage(900, 40, "gpt-4o-mini"))
            ingestion._record_ingest_usage("fid", acc)

        assert written, "captioning-only ingest wrote no usage row"
        assert written[0]["usage"] == TokenUsage(900, 40, "gpt-4o-mini")
        # No embedding happened, so that side stays unmeasured rather than 0.
        assert not written[0]["embedding"].known

    def test_nothing_measured_writes_nothing(self):
        from app.services import embedding_usage

        with embedding_usage.scope() as acc:
            assert acc.total.known is False and acc.llm_total.known is False


class TestMatryoshkaRestoreSaving:
    def test_only_restored_files_count(self):
        """Gap files are about to be re-embedded and PAID for, so counting
        them would report a saving that is about to be spent."""
        from app.routers import files as files_router

        src = inspect.getsource(files_router._record_restore_savings)
        assert "f.id not in gap" in src

    def test_the_saving_is_replayed_never_estimated(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router._record_restore_savings)
        assert "f.embedding_tokens" in src
        # Check the CODE, not the prose: the docstring says "never estimated",
        # which a naive substring scan of the whole source would trip over.
        body = src.split(chr(34) * 3)
        # index 0 is the signature, 1 is the docstring, 2 onwards is real code
        code = "".join(body[2:]) if len(body) > 2 else src
        code = "".join(
            line for line in code.splitlines()
            if not line.strip().startswith("#")
        )
        assert "avg" not in code.lower()
        assert "* len(" not in code, "a saving must never be count x rate"

    def test_files_with_no_recorded_cost_contribute_nothing(self):
        """Ingested before metering existed: unmeasured, not zero."""
        from app.routers import files as files_router

        src = inspect.getsource(files_router._record_restore_savings)
        assert "is not None" in src
        assert "if not tokens:" in src

    def test_it_is_called_on_the_restore_path(self):
        from app.routers import files as files_router

        src = inspect.getsource(files_router.reindex_project)
        assert "_record_restore_savings" in src


class TestSavedEmbeddingIsPricedLikeAnEmbedding:
    def test_record_usage_prices_it_with_the_embedding_table(self, ):
        """Chat prices are 10-100x higher; crossing the tables would overstate
        the saving by orders of magnitude."""
        from app.services import usage

        src = inspect.getsource(usage.record_usage)
        saved_block = src[src.index("saved_embedding_cost_usd"):]
        assert "embedding_cost_for" in saved_block
