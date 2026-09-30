"""WebSocket hub + transactional notifications.

Events are queued on the DB session and only pushed after the transaction commits, so clients never
see state that later rolls back.
"""
import asyncio
import logging
from collections import defaultdict

from fastapi import WebSocket
from sqlalchemy import event
from sqlalchemy.orm import Session

from ..models import Notification

log = logging.getLogger("nexa.realtime")


class Hub:
    def __init__(self) -> None:
        self.conns: dict[int, set[WebSocket]] = defaultdict(set)
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, user_id: int, ws: WebSocket) -> None:
        self.loop = asyncio.get_running_loop()
        self.conns[user_id].add(ws)

    def disconnect(self, user_id: int, ws: WebSocket) -> None:
        self.conns[user_id].discard(ws)
        if not self.conns[user_id]:
            self.conns.pop(user_id, None)

    def online_user_ids(self) -> set[int]:
        return set(self.conns.keys())

    async def _send(self, user_id: int, payload: dict) -> None:
        for ws in list(self.conns.get(user_id, ())):
            try:
                await ws.send_json(payload)
            except Exception:  # dead socket
                self.disconnect(user_id, ws)

    def push(self, user_id: int, payload: dict) -> None:
        """Thread-safe: callable from sync route handlers running in the threadpool."""
        if self.loop is None or user_id not in self.conns:
            return
        try:
            asyncio.run_coroutine_threadsafe(self._send(user_id, payload), self.loop)
        except RuntimeError:
            log.debug("event loop closed; dropping push")


hub = Hub()


@event.listens_for(Session, "after_commit")
def _flush_events(session: Session) -> None:
    for uid, payload in session.info.pop("pending_events", []):
        hub.push(uid, payload)


@event.listens_for(Session, "after_rollback")
def _drop_events(session: Session) -> None:
    session.info.pop("pending_events", None)


def emit(db: Session, user_id: int, payload: dict) -> None:
    db.info.setdefault("pending_events", []).append((user_id, payload))


def notify(db: Session, user_id: int, kind: str, title: str, body: str = "", data: dict | None = None) -> Notification:
    n = Notification(user_id=user_id, kind=kind, title=title, body=body, data=data or {})
    db.add(n)
    emit(db, user_id, {"type": "notification", "kind": kind, "title": title, "body": body, "data": data or {}})
    return n


def emit_request_update(db: Session, request_id: int, user_ids: set[int], status: str) -> None:
    for uid in user_ids:
        emit(db, uid, {"type": "request_update", "request_id": request_id, "status": status})
