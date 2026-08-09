"""Server-Sent Events helper: wrap an event-dict generator as an SSE response."""
import json
import logging
import queue
import threading
from collections.abc import Iterable

from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

# Disable proxy/browser buffering so tokens reach the client as they are yielded
# (X-Accel-Buffering is honoured by nginx, which Render sits behind).
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}

# Sentinel pushed when the producer finishes, so the consumer can stop without
# a timeout. A plain None would be ambiguous if a frame were ever None.
_DONE = object()


def sse_response(events: Iterable[dict]) -> StreamingResponse:
    """Serialize each event dict as a `data: <json>\\n\\n` SSE frame.

    The generator runs on ONE dedicated thread rather than being handed to
    Starlette as a sync iterable.

    WHY THAT MATTERS. Starlette drives a sync iterable with
    `iterate_in_threadpool`, which calls `next()` through the anyio worker
    pool - and consecutive calls can land on DIFFERENT threads. The streaming
    query path holds a Langfuse/OTEL trace open across those yields, and an
    OTEL context token created on one thread cannot be detached on another:
    it raises "Token was created in a different Context", the span never
    detaches, and the stale context leaks into a pooled worker thread that the
    NEXT request may reuse - so one request's observations could nest under a
    different request's trace.

    One thread for the whole generator makes every ContextVar coherent from
    first token to last, which is what the trace, the embedding-usage scope and
    the usage write in the generator's `finally` all assume. It also removes a
    threadpool hop per token.
    """

    def frames():
        for event in events:
            if event.get("type") == "ping":
                # SSE comment frame: keeps idle proxies from killing the
                # connection during silent phases (context gathering can take
                # tens of seconds before the first token). Spec-compliant
                # parsers ignore comments, so clients see nothing.
                yield ": keep-alive\n\n"
                continue
            yield f"data: {json.dumps(event)}\n\n"

    async def single_threaded():
        import anyio

        # Bounded: if the client stops reading, the producer blocks here rather
        # than buffering an unbounded answer in memory.
        pipe: queue.Queue = queue.Queue(maxsize=64)

        def produce():
            try:
                for frame in frames():
                    pipe.put(frame)
            except Exception as exc:  # pragma: no cover - defensive
                logger.exception("SSE producer failed")
                pipe.put(exc)
            finally:
                pipe.put(_DONE)

        thread = threading.Thread(
            target=produce, name="oreag-sse", daemon=True
        )
        thread.start()
        try:
            while True:
                item = await anyio.to_thread.run_sync(pipe.get)
                if item is _DONE:
                    break
                if isinstance(item, Exception):
                    raise item
                yield item
        finally:
            # A disconnected client abandons this async generator. Draining
            # lets the producer's own `finally` run - which is where the usage
            # row is written and the trace is closed - instead of leaving the
            # thread blocked on a full queue forever.
            while thread.is_alive():
                try:
                    if pipe.get(timeout=5) is _DONE:
                        break
                except queue.Empty:
                    logger.warning("SSE producer did not finish; abandoning")
                    break

    return StreamingResponse(
        single_threaded(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
