"""SSE framing, and the thread/context guarantee the streaming query relies on.

The streaming query path holds a Langfuse trace, an embedding-usage scope and a
deferred usage write open ACROSS yields. All three are ContextVar-based, so they
are only correct if the whole generator runs in one context - which is why
sse_response drives it on a single dedicated thread instead of handing a sync
iterable to Starlette's per-`next()` threadpool.
"""
import asyncio
import contextvars
import json
import threading

import pytest

from app.sse import sse_response

_probe: contextvars.ContextVar[str] = contextvars.ContextVar("probe", default="")


def drain(response):
    async def go():
        return [chunk async for chunk in response.body_iterator]

    return asyncio.run(go())


class TestFraming:
    def test_events_become_data_frames(self):
        frames = drain(sse_response([{"type": "token", "text": "hi"}]))
        assert frames == ['data: {"type": "token", "text": "hi"}\n\n']

    def test_ping_becomes_a_comment_frame(self):
        """Spec-compliant parsers ignore comments, so clients see nothing -
        but idle proxies see traffic and keep the connection open."""
        frames = drain(sse_response([{"type": "ping"}]))
        assert frames == [": keep-alive\n\n"]

    def test_order_is_preserved(self):
        events = [{"type": "token", "text": str(i)} for i in range(20)]
        frames = drain(sse_response(events))
        texts = [json.loads(f[len("data: "):])["text"] for f in frames]
        assert texts == [str(i) for i in range(20)]

    def test_empty_stream(self):
        assert drain(sse_response([])) == []

    def test_response_headers_disable_buffering(self):
        resp = sse_response([])
        assert resp.headers["x-accel-buffering"] == "no"
        assert resp.media_type == "text/event-stream"


class TestSingleThreadedContext:
    def test_every_yield_runs_on_one_thread(self):
        """A sanity check, not the load-bearing one.

        Thread identity alone does NOT catch the original bug: anyio often
        reuses one idle worker, so the old implementation passes this too. The
        defect was Context identity, which the next test pins down.
        """
        seen: set[int] = set()

        def gen():
            for i in range(30):
                seen.add(threading.get_ident())
                yield {"type": "token", "text": str(i)}

        drain(sse_response(gen()))
        assert len(seen) == 1, f"generator hopped threads: {seen}"

    def test_contextvars_set_before_a_yield_survive_after_it(self):
        """THE regression test - verified to fail on the old implementation.

        Starlette drove the sync generator through `anyio.to_thread.run_sync`,
        which gives each `next()` a FRESH COPY of the context. A variable set
        before a yield therefore read back as unset after it (measured: the
        probe came back `<unset>` both times).

        That is why `tracing.query_trace` could not hold across a streamed
        answer: its OTEL token was created in one context and detached in
        another, raising "Token was created in a different Context", leaving
        the span unclosed and streamed generations not nested under their root
        trace.
        """
        observed = []

        def gen():
            _probe.set("set-before-first-yield")
            yield {"type": "token", "text": "a"}
            observed.append(_probe.get())
            yield {"type": "token", "text": "b"}
            observed.append(_probe.get())

        drain(sse_response(gen()))
        assert observed == ["set-before-first-yield"] * 2

    def test_a_context_manager_can_span_the_whole_stream(self):
        """`with tracing.query_trace(...): yield from events` - the exit has to
        see the same context the enter established, or an OTEL detach raises
        and the trace is never closed."""
        events = []

        class Marker:
            def __enter__(self):
                events.append(("enter", threading.get_ident()))
                return self

            def __exit__(self, *a):
                events.append(("exit", threading.get_ident()))
                return False

        def gen():
            with Marker():
                for i in range(10):
                    yield {"type": "token", "text": str(i)}

        drain(sse_response(gen()))
        assert [e[0] for e in events] == ["enter", "exit"]
        assert events[0][1] == events[1][1], "entered and exited on different threads"


class TestFinallyStillRuns:
    def test_the_generators_finally_runs_on_normal_completion(self):
        """That block is where the usage row is written."""
        ran = []

        def gen():
            try:
                yield {"type": "token", "text": "x"}
            finally:
                ran.append(True)

        drain(sse_response(gen()))
        assert ran == [True]

    def test_a_producer_exception_propagates(self):
        """A failure must surface, not silently truncate the stream."""
        def gen():
            yield {"type": "token", "text": "x"}
            raise RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            drain(sse_response(gen()))

    def test_the_stream_is_lazy(self):
        """sse_response must not start producing before the response is
        iterated - the route returns first, and the query has not run yet."""
        started = []

        def gen():
            started.append(True)
            yield {"type": "token", "text": "x"}

        sse_response(gen())
        assert started == [], "generator ran at construction time"
