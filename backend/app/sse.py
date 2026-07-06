"""Server-Sent Events helper: wrap an event-dict generator as an SSE response."""
import json
from collections.abc import Iterable

from fastapi.responses import StreamingResponse

# Disable proxy/browser buffering so tokens reach the client as they are yielded
# (X-Accel-Buffering is honoured by nginx, which Render sits behind).
_SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    "X-Accel-Buffering": "no",
}


def sse_response(events: Iterable[dict]) -> StreamingResponse:
    """Serialize each event dict as a `data: <json>\\n\\n` SSE frame."""

    def frames():
        for event in events:
            yield f"data: {json.dumps(event)}\n\n"

    return StreamingResponse(
        frames(), media_type="text/event-stream", headers=_SSE_HEADERS
    )
