"""Campaign recipient queue management and resume state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import threading
from typing import Any


DEFAULT_QUEUE_STATE_PATH = Path("data") / "queue-state.json"


class QueueError(RuntimeError):
    """Raised when queue operations fail."""


@dataclass(frozen=True)
class QueueItem:
    """One recipient queue item."""

    email: str
    name: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    control: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return JSON-ready queue item."""
        return {
            "email": self.email,
            "name": self.name,
            "data": self.data,
            "control": self.control,
        }


@dataclass(frozen=True)
class QueueSnapshot:
    """Queue progress snapshot."""

    total: int
    processed: int
    remaining: int
    state_path: str


class QueueManager:
    """Persistent queue state for campaign resume."""

    def __init__(self, state_path: str | Path = DEFAULT_QUEUE_STATE_PATH) -> None:
        self.state_path = Path(state_path)
        self._items: list[QueueItem] = []
        self._index = 0
        self._metadata: dict[str, Any] = {}
        self._lock = threading.RLock()

    def build_from_recipients(
        self,
        recipients: list[dict[str, Any] | str],
        control_recipients: list[dict[str, Any] | str] | None = None,
        control_every: int = 0,
        metadata: dict[str, Any] | None = None,
    ) -> QueueSnapshot:
        """Build a queue from recipients and optional control injection."""
        control_recipients = control_recipients or []
        items: list[QueueItem] = []
        controls = [_normalize_recipient(item, control=True) for item in control_recipients]
        control_index = 0

        for index, recipient in enumerate(recipients, start=1):
            items.append(_normalize_recipient(recipient, control=False))
            if controls and control_every > 0 and index % control_every == 0:
                items.append(controls[control_index % len(controls)])
                control_index += 1

        if not items:
            raise QueueError("Очередь пуста")

        with self._lock:
            self._items = items
            self._index = 0
            self._metadata = dict(metadata or {})
            self.save_state()
            return self.snapshot()

    def load_state(self) -> QueueSnapshot:
        """Load unfinished queue state from disk."""
        if not self.state_path.exists():
            raise QueueError("Сохранённая очередь не найдена")

        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise QueueError(f"Не удалось прочитать queue-state.json: {exc}") from exc

        raw_items = payload.get("items")
        index = payload.get("index", 0)
        if not isinstance(raw_items, list):
            raise QueueError("queue-state.json повреждён: нет items")
        if not isinstance(index, int):
            raise QueueError("queue-state.json повреждён: index некорректный")

        items = [_queue_item_from_dict(item) for item in raw_items if isinstance(item, dict)]
        with self._lock:
            self._items = items
            self._index = max(0, min(index, len(items)))
            metadata = payload.get("metadata")
            self._metadata = dict(metadata) if isinstance(metadata, dict) else {}
            return self.snapshot()

    def has_unfinished_state(self) -> bool:
        """Return True if queue-state.json contains unfinished queue."""
        if not self.state_path.exists():
            return False
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return False
        items = payload.get("items")
        index = payload.get("index", 0)
        return isinstance(items, list) and isinstance(index, int) and index < len(items)

    def next_item(self) -> QueueItem | None:
        """Return current queue item without advancing."""
        with self._lock:
            if self._index >= len(self._items):
                return None
            return self._items[self._index]

    def mark_current_processed(self) -> QueueSnapshot:
        """Advance queue by one item and persist state."""
        with self._lock:
            if self._index < len(self._items):
                self._index += 1
            self.save_state()
            return self.snapshot()

    def save_state(self) -> None:
        """Persist queue state to data/queue-state.json."""
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "updated_at": _utc_now(),
            "index": self._index,
            "total": len(self._items),
            "metadata": self._metadata,
            "items": [item.as_dict() for item in self._items],
        }
        self.state_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear_state(self) -> None:
        """Clear in-memory and persisted queue state."""
        with self._lock:
            self._items = []
            self._index = 0
        if self.state_path.exists():
            self.state_path.unlink()

    def snapshot(self) -> QueueSnapshot:
        """Return queue progress snapshot."""
        with self._lock:
            total = len(self._items)
            processed = min(self._index, total)
            return QueueSnapshot(
                total=total,
                processed=processed,
                remaining=max(0, total - processed),
                state_path=str(self.state_path),
            )


def _normalize_recipient(raw: dict[str, Any] | str, control: bool) -> QueueItem:
    if isinstance(raw, str):
        email = raw.strip()
        data: dict[str, Any] = {"email": email}
        name = ""
    else:
        data = dict(raw)
        email = str(data.get("email", "")).strip()
        name = str(data.get("name", "")).strip()

    if not email:
        raise QueueError("В базе получателей есть строка без email")
    data.setdefault("email", email)
    if name:
        data.setdefault("name", name)
    return QueueItem(email=email, name=name, data=data, control=control)


def _queue_item_from_dict(raw: dict[str, Any]) -> QueueItem:
    email = str(raw.get("email", "")).strip()
    if not email:
        raise QueueError("queue-state.json содержит recipient без email")
    name = str(raw.get("name", "")).strip()
    data = raw.get("data") if isinstance(raw.get("data"), dict) else {"email": email, "name": name}
    return QueueItem(
        email=email,
        name=name,
        data=dict(data),
        control=bool(raw.get("control", False)),
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
