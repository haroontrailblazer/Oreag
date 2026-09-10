import contextvars
from concurrent.futures import ThreadPoolExecutor
from app.services import query_timeline as timeline


def test_sync_scopes_are_isolated_and_bounded():
    @timeline.capture
    def query():
        for _ in range(80):
            with timeline.phase("embedding"): pass
        return timeline.snapshot()
    a, b = query(), query()
    assert a["trace_id"] != b["trace_id"]
    assert len(a["spans"]) == 64 and timeline.current() is None


def test_generator_context_transfer_return_value_and_thread_adoption():
    @timeline.measure("llm")
    def llm(**kwargs):
        yield "token"
        return "usage"
    @timeline.capture
    def query():
        usage = yield from llm(name="translate-question")
        assert usage == "usage"
        value = timeline.current()
        def retrieve():
            with timeline.adopt(value), timeline.phase("retrieval"): pass
        with ThreadPoolExecutor(1) as pool: pool.submit(retrieve).result()
        yield timeline.snapshot()
    gen = query()
    assert contextvars.Context().run(next, gen) == "token"
    snapshot = contextvars.Context().run(next, gen)
    assert [s["stage"] for s in snapshot["spans"]] == ["translation", "retrieval"]
    gen.close()
    assert timeline.current() is None
