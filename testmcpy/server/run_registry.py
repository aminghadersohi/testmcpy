"""In-memory registry of in-flight test runs.

A ``RunHandle`` owns the ``asyncio.Task`` that drives a run plus a bounded
log buffer. WebSocket connections become *attachments* to a handle rather
than owners — that decoupling is what lets a browser reload survive an
in-flight run (the WS closes, the task keeps running, a fresh WS reattaches
via ``run_id``).

In-memory only: a single uvicorn worker (confirmed) plus an acceptable
"runs are lost on server restart" trade-off for v1. Runs that complete
(or stop / error) are retained for ``CLEANUP_TTL`` so a slow reload can
still pick up the final state, then GC'd lazily on the next ``create_run``.
"""

from __future__ import annotations

import asyncio
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Literal

# Bounded log buffer per run — sized to fit a long suite without unbounded
# growth. ~20k log lines covers C00-C04 with verbose Claude SDK output and
# still leaves headroom; older lines are evicted FIFO if a runaway emitter
# blows past it. Replays send the buffer as-is, so a reload after eviction
# sees only the tail (acceptable — the UI banner can hint at truncation).
LOG_BUFFER_MAX = 20_000

# How long to retain a finished run handle so a slow reload can still
# attach and see the final state. After this, lazy GC discards it.
CLEANUP_TTL = timedelta(minutes=30)

RunStatus = Literal["running", "completed", "error", "stopped"]
RunKind = Literal["single", "directory"]


def _mint_run_id() -> str:
    """Match the shape used by `results.save_test_run_to_file` so the
    in-flight registry id and the eventual saved-history record line up
    on a single identifier."""
    return f"{uuid.uuid4().hex[:8]}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"


@dataclass
class RunHandle:
    """Live state for an in-flight (or recently finished) run.

    ``attached_ws`` is *opaque* to this module — the websocket handler
    parks an ``asyncio.Queue`` here that the run's ``send_log`` callback
    publishes lines onto. The handler drains the queue back to the client.
    Storing a queue (not the raw WebSocket) lets us swap attachments
    atomically when a second client takes over.
    """

    run_id: str
    kind: RunKind
    started_at: datetime
    meta: dict[str, Any]
    log_buffer: deque[str] = field(default_factory=lambda: deque(maxlen=LOG_BUFFER_MAX))
    # Mirror of test_complete / file_start / file_complete / all_complete
    # messages — replayed to a reattaching client AFTER the log buffer
    # so the UI can rebuild its results/progress panels without us having
    # to peek inside test_runner.
    structured_events: list[dict[str, Any]] = field(default_factory=list)
    status: RunStatus = "running"
    finished_at: datetime | None = None
    summary: dict[str, Any] | None = None
    results: list[dict[str, Any]] = field(default_factory=list)
    task: asyncio.Task | None = None
    # Queue published to by send_log + send_structured. Replaced when a
    # new client attaches; ``None`` when no client is currently watching.
    attached_queue: asyncio.Queue | None = None
    # Bumped each time a new attachment supersedes the previous — lets
    # the prior listener detect supersession and exit cleanly.
    attachment_token: int = 0

    @property
    def is_finished(self) -> bool:
        return self.status != "running"


# Module-level registry. Reads from a single uvicorn worker, so a plain
# dict + asyncio.Lock is enough — no cross-process or threading concerns.
_runs: dict[str, RunHandle] = {}
_lock = asyncio.Lock()


def _gc_finished_unlocked(now: datetime | None = None) -> None:
    """Discard finished handles whose ``finished_at`` is older than
    ``CLEANUP_TTL``. Called under the registry lock."""
    if now is None:
        now = datetime.now()
    cutoff = now - CLEANUP_TTL
    stale = [
        rid
        for rid, h in _runs.items()
        if h.is_finished and h.finished_at is not None and h.finished_at < cutoff
    ]
    for rid in stale:
        del _runs[rid]


async def create_run(*, kind: RunKind, meta: dict[str, Any]) -> RunHandle:
    """Mint a run id, register a fresh ``RunHandle`` and return it.

    The caller is responsible for setting ``handle.task`` once it spawns
    the runner coroutine — we don't take the task as an arg so the
    handle can exist (with id, buffer, attachment) before the task is
    actually scheduled, simplifying the websocket handshake.
    """
    async with _lock:
        _gc_finished_unlocked()
        run_id = _mint_run_id()
        # Vanishingly unlikely collision (uuid prefix + second-level
        # timestamp) but cheap to guard against in tests.
        while run_id in _runs:
            run_id = _mint_run_id()
        handle = RunHandle(
            run_id=run_id,
            kind=kind,
            started_at=datetime.now(),
            meta=dict(meta),
        )
        _runs[run_id] = handle
        return handle


async def get_run(run_id: str) -> RunHandle | None:
    """Look up a handle by id. Returns ``None`` if absent (never created
    or already GC'd)."""
    async with _lock:
        return _runs.get(run_id)


async def list_active() -> list[RunHandle]:
    """Snapshot of currently-running handles. Used by lightweight debug
    endpoints / future status pages."""
    async with _lock:
        return [h for h in _runs.values() if not h.is_finished]


async def finalize(run_id: str, *, status: RunStatus, summary: dict | None = None) -> None:
    """Mark a handle finished and stamp ``finished_at``. Idempotent — a
    duplicate call (e.g. the same task hitting both completion and an
    error path) leaves the first-write status in place."""
    async with _lock:
        handle = _runs.get(run_id)
        if handle is None or handle.is_finished:
            return
        handle.status = status
        handle.finished_at = datetime.now()
        if summary is not None:
            handle.summary = summary


def _publish(handle: RunHandle, message: dict[str, Any]) -> None:
    """Append the message to the handle's log buffer (if it's a 'log'
    or 'log_replay' shape) and push onto the attached queue if any
    listener is currently watching. Safe to call without the registry
    lock — log buffer + queue are independently safe.
    """
    if message.get("type") == "log":
        handle.log_buffer.append(message.get("message", ""))
    else:
        # test_start / test_complete / file_start / file_complete /
        # all_complete / error — replayed after the log buffer on
        # reattach so the UI can rebuild its progress + results.
        handle.structured_events.append(message)
    queue = handle.attached_queue
    if queue is not None:
        try:
            queue.put_nowait(message)
        except asyncio.QueueFull:
            # Pathological — queue is unbounded by default; if a caller
            # bounded it, drop the message rather than block the run.
            pass


def log(handle: RunHandle, message: str) -> None:
    """Buffer a free-text log line and forward to any current attachment."""
    _publish(handle, {"type": "log", "message": message})


def event(handle: RunHandle, message: dict[str, Any]) -> None:
    """Buffer a structured event (test_start / file_start / etc) and
    forward to any current attachment. The ``type`` field on the message
    is preserved verbatim — the websocket handler does NOT translate it."""
    _publish(handle, message)


async def attach(handle: RunHandle) -> tuple[asyncio.Queue, int]:
    """Register a fresh queue as the run's current attachment.

    Returns ``(queue, token)``. ``token`` is the attachment's identity —
    if a later attach supersedes this one, the previous listener can
    detect it by comparing ``handle.attachment_token != token`` and exit.

    Also enqueues a ``superseded`` marker onto the *previous* queue (if
    any) so the prior listener wakes up and notices.
    """
    async with _lock:
        previous = handle.attached_queue
        previous_token = handle.attachment_token
        new_queue: asyncio.Queue = asyncio.Queue()
        handle.attached_queue = new_queue
        handle.attachment_token += 1
        token = handle.attachment_token
    if previous is not None:
        try:
            previous.put_nowait({"type": "superseded", "by_token": token})
        except asyncio.QueueFull:
            pass
        # Discard the supersedee's token reference — the caller-side
        # loop will see `handle.attached_queue is not its own queue`
        # OR receive the explicit superseded message and exit.
        del previous_token
    return new_queue, token


async def detach(handle: RunHandle, token: int) -> None:
    """Drop the current attachment if it still matches ``token``.

    Called when a client websocket goes away (disconnect OR explicit
    end-of-stream). Skips the no-op case where a newer attachment has
    already replaced us.
    """
    async with _lock:
        if handle.attachment_token == token:
            handle.attached_queue = None


def buffered_replay(handle: RunHandle) -> list[dict[str, Any]]:
    """Snapshot of everything to send to a fresh attachment before live
    streaming starts. Order: log lines first (so they render as the
    backlog), then structured events (so the UI's progress + results
    panels reflect prior state)."""
    return [
        *({"type": "log_replay", "message": line} for line in handle.log_buffer),
        *handle.structured_events,
    ]


async def reset_for_tests() -> None:
    """Test-only: clear the entire registry. Keeps unit tests
    independent of one another even when they share the module-level
    state."""
    async with _lock:
        _runs.clear()
