"""Observe existing cache decisions without additional Redis or database reads."""
from . import query_timeline


def start(*, signature, history_turns, history_unavailable, bypass, exact_enabled, semantic_enabled, backend, ttl):
    timeline = query_timeline.current()
    if timeline is None:
        return
    version = next((part[1:] for part in signature.split("|") if part.startswith("v") and part[1:].isdigit()), None)
    skipped = "context_unavailable" if history_unavailable else "bypassed" if bypass else None
    timeline.cache_details = {
        "version": 1, "exact": skipped or ("not_checked" if exact_enabled else "disabled"),
        "semantic": skipped or ("conversation_context" if history_turns else "not_checked" if semantic_enabled else "disabled"),
        "conversation_turns": history_turns, "content_version": int(version) if version else None,
        "exact_backend": backend, "exact_ttl_seconds": ttl if exact_enabled else None,
    }


def record(layer, reason):
    timeline = query_timeline.current()
    if timeline is not None and hasattr(timeline, "cache_details"):
        with timeline.lock:
            timeline.cache_details[layer] = reason


def snapshot(cache_layer):
    timeline = query_timeline.current()
    if timeline is None or not hasattr(timeline, "cache_details"):
        return None
    with timeline.lock:
        result = dict(timeline.cache_details)
    if cache_layer == "l1":
        result["exact"] = "hit"
        if result["semantic"] == "not_checked":
            result["semantic"] = "exact_hit"
    elif cache_layer == "l2":
        result["semantic"] = "hit"
    return result
