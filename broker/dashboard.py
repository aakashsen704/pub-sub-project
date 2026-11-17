"""Optional demo dashboard (web UI) served by the broker at /dashboard.

The page itself is plain HTML + JavaScript (broker/static/dashboard.html) and only
uses the broker's normal REST endpoints. The one extra endpoint here,
GET /dashboard/inbox, lets the page show what each subscriber has received:
the broker asks every registered subscriber for its events over HTTP
(GET <subscriber>/events), so it works the same with terminals or Docker.
"""
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict
from urllib.parse import urlsplit

import httpx
from fastapi import APIRouter
from fastapi.responses import FileResponse

from .registry import SubscriberRegistry

STATIC_DIR = Path(__file__).parent / "static"


def _events_url(callback_url: str) -> str:
    """http://host:5001/notify -> http://host:5001/events"""
    parts = urlsplit(callback_url)
    return f"{parts.scheme}://{parts.netloc}/events"


async def _fetch_inbox(
    client: httpx.AsyncClient, subscriber_id: str, callback_url: str
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "subscriber_id": subscriber_id,
        "callback_url": callback_url,
        "online": False,
        "events": [],
    }
    try:
        response = await client.get(_events_url(callback_url))
        response.raise_for_status()
        entry["events"] = response.json().get("events", [])
        entry["online"] = True
    except Exception:
        pass  # unreachable or not a compatible subscriber -> shown as offline
    return entry


def create_dashboard_router(registry: SubscriberRegistry) -> APIRouter:
    router = APIRouter(tags=["dashboard"])

    @router.get("/dashboard", include_in_schema=False)
    async def dashboard_page() -> FileResponse:
        return FileResponse(STATIC_DIR / "dashboard.html")

    @router.get("/dashboard/inbox")
    async def dashboard_inbox() -> dict:
        """Registered subscribers with their online status and received events."""
        targets = registry.callback_urls()
        async with httpx.AsyncClient(timeout=httpx.Timeout(1.5)) as client:
            inboxes = await asyncio.gather(
                *(_fetch_inbox(client, sid, url) for sid, url in targets.items())
            )
        return {"inboxes": list(inboxes)}

    return router