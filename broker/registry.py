"""In-memory subscriber registry.

The registry is a plain Python dictionary (no database, as required by the
assignment):

    {
        "student_A": {"callback_url": "http://localhost:5001/notify",
                      "registered_at": "2026-11-11T10:00:00+00:00"},
        ...
    }

All access goes through :class:`SubscriberRegistry` so the rest of the broker
never touches the dictionary directly.
"""
from __future__ import annotations

import threading
from datetime import datetime, timezone
from typing import Dict, List, Optional


class DuplicateSubscriberError(Exception):
    """Raised when a subscriber ID is already registered."""


class SubscriberNotFoundError(Exception):
    """Raised when a subscriber ID is not registered."""


class SubscriberRegistry:
    def __init__(self) -> None:
        self._subscribers: Dict[str, Dict[str, str]] = {}
        self._lock = threading.Lock()

    def register(self, subscriber_id: str, callback_url: str) -> Dict[str, str]:
        """Add a subscriber. Raises DuplicateSubscriberError if the ID exists."""
        with self._lock:
            if subscriber_id in self._subscribers:
                raise DuplicateSubscriberError(
                    f"Subscriber '{subscriber_id}' is already registered."
                )
            record = {
                "callback_url": callback_url,
                "registered_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            }
            self._subscribers[subscriber_id] = record
            return {"subscriber_id": subscriber_id, **record}

    def unregister(self, subscriber_id: str) -> None:
        """Remove a subscriber. Raises SubscriberNotFoundError if unknown."""
        with self._lock:
            if subscriber_id not in self._subscribers:
                raise SubscriberNotFoundError(
                    f"Subscriber '{subscriber_id}' is not registered."
                )
            del self._subscribers[subscriber_id]

    def get(self, subscriber_id: str) -> Optional[Dict[str, str]]:
        with self._lock:
            record = self._subscribers.get(subscriber_id)
            return dict(record) if record else None

    def list_all(self) -> List[Dict[str, str]]:
        """Return a snapshot (copy) of all subscribers."""
        with self._lock:
            return [
                {"subscriber_id": sid, **record}
                for sid, record in self._subscribers.items()
            ]

    def callback_urls(self) -> Dict[str, str]:
        """Snapshot of {subscriber_id: callback_url} used for recipient selection."""
        with self._lock:
            return {sid: rec["callback_url"] for sid, rec in self._subscribers.items()}

    def __len__(self) -> int:
        with self._lock:
            return len(self._subscribers)
