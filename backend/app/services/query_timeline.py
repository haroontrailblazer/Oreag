"""Bounded, request-local timings without prompts, answers, or provider secrets."""
import contextvars
import functools
import inspect
import threading
import time
import uuid
from contextlib import contextmanager

_current = contextvars.ContextVar("query_timeline", default=None)


class Timeline:
    def __init__(self):
        self.start = time.perf_counter()
        self.id = uuid.uuid4().hex
        self.spans = []
        self.lock = threading.Lock()


def current():
    return _current.get()


@contextmanager
def adopt(value):
    token = _current.set(value)
    try:
        yield value
    finally:
        _current.reset(token)


@contextmanager
def phase(stage):
    value, start = current(), time.perf_counter()
    success = False
    try:
        yield
        success = True
    finally:
        if value is not None:
            with value.lock:
                if len(value.spans) < 64:
                    value.spans.append({"stage": stage, "start_ms": round((start - value.start) * 1000, 2),
                        "duration_ms": round((time.perf_counter() - start) * 1000, 2), "success": success})


def capture(fn):
    if inspect.isgeneratorfunction(fn):
        @functools.wraps(fn)
        def stream(*args, **kwargs):
            value, iterator = Timeline(), fn(*args, **kwargs)
            try:
                while True:
                    # StreamingResponse may call next() from different AnyIO contexts.
                    with adopt(value):
                        try:
                            item = next(iterator)
                        except StopIteration as end:
                            return end.value
                    yield item
            finally:
                with adopt(value):
                    iterator.close()
        return stream
    @functools.wraps(fn)
    def call(*args, **kwargs):
        with adopt(Timeline()):
            return fn(*args, **kwargs)
    return call


def measure(stage):
    def decorate(fn):
        def label(kwargs):
            if stage != "llm":
                return stage
            name = kwargs.get("name", "")
            if "translat" in name or "language" in name:
                return "translation"
            return "planning" if any(s in name for s in ("plan", "condense", "clarif")) else "generation"
        if inspect.isgeneratorfunction(fn):
            @functools.wraps(fn)
            def stream(*args, **kwargs):
                with phase(label(kwargs)):
                    return (yield from fn(*args, **kwargs))
            return stream
        @functools.wraps(fn)
        def call(*args, **kwargs):
            with phase(label(kwargs)):
                return fn(*args, **kwargs)
        return call
    return decorate


def snapshot():
    value = current()
    if value is None:
        return None
    with value.lock:
        return {"trace_id": value.id, "total_ms": round((time.perf_counter() - value.start) * 1000, 2),
                "spans": sorted(value.spans, key=lambda span: span["start_ms"])}
