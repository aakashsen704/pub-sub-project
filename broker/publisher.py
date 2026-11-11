"""Event publishing logic: recipient selection and HTTP callback delivery.

Flow for every published event:

    1. select_recipients()   - decide who gets the event (unicast/multicast/broadcast)
    2. deliver()             - POST the event to each selected subscriber's callback URL
                               (concurrently, with a timeout, never raising on failure)
    3. build the delivery summary returned to the publisher

The broker talks to subscribers ONLY through HTTP - it never calls subscriber
code or touches subscriber memory directly.
"""
from __future__ import annotations

import asyncio
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .models import CommunicationMode, PublishRequest
from .registry import SubscriberRegistry

logger = logging.getLogger("broker.publisher")

PUBLISHER_NAME = "main_broker"

# Total time allowed per callback; connecting must succeed within 2 seconds.
# Override with the PUBSUB_CALLBACK_TIMEOUT environment variable (seconds).
CALLBACK_TIMEOUT_SECONDS = float(os.getenv("PUBSUB_CALLBACK_TIMEOUT", "5"))


class PublishError(Exception):
    """A publish request that is invalid; carries the HTTP status to return."""

    def __init__(self, status_code: int, detail: str) -> None:
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


# --------------------------------------------------------------------------- #
# Step 1: recipient selection
# --------------------------------------------------------------------------- #
def select_recipients(
    mode: CommunicationMode,
    requested: Optional[List[str]],
    registry: SubscriberRegistry,
) -> Tuple[Dict[str, str], List[str]]:
    """Return ({subscriber_id: callback_url} to notify, [invalid IDs]).

    Raises PublishError for requests that cannot be served at all.
    """
    registered = registry.callback_urls()  # snapshot

    if mode is CommunicationMode.BROADCAST:
        # Every registered subscriber; any 'recipients' list is ignored.
        return registered, []

    # Unicast / multicast need an explicit recipient list (duplicates removed).
    recipients = list(dict.fromkeys(requested or []))

    if mode is CommunicationMode.UNICAST:
        if len(recipients) != 1:
            raise PublishError(
                400,
                "Unicast requires exactly one recipient in 'recipients' "
                f"(got {len(recipients)}).",
            )
        target = recipients[0]
        if target not in registered:
            raise PublishError(404, f"Subscriber '{target}' is not registered.")
        return {target: registered[target]}, []

    # MULTICAST
    if not recipients:
        raise PublishError(
            400, "Multicast requires a non-empty 'recipients' list."
        )
    valid = {sid: registered[sid] for sid in recipients if sid in registered}
    invalid = [sid for sid in recipients if sid not in registered]
    if not valid:
        raise PublishError(
            404,
            "None of the requested recipients are registered: "
            + ", ".join(invalid),
        )
    return valid, invalid


# --------------------------------------------------------------------------- #
# Step 2: HTTP callback delivery
# --------------------------------------------------------------------------- #
async def _deliver_one(
    client: httpx.AsyncClient,
    subscriber_id: str,
    callback_url: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """POST the event to one subscriber. Never raises - failures become results."""
    try:
        response = await client.post(callback_url, json=payload)
        if response.is_success:
            logger.info("Delivered to %s (HTTP %s)", subscriber_id, response.status_code)
            return {
                "subscriber_id": subscriber_id,
                "status": "success",
                "http_status": response.status_code,
            }
        logger.warning("Subscriber %s answered HTTP %s", subscriber_id, response.status_code)
        return {
            "subscriber_id": subscriber_id,
            "status": "failed",
            "http_status": response.status_code,
            "error": f"Subscriber returned HTTP {response.status_code}",
        }
    except httpx.TimeoutException:
        error = f"Timeout: no response within {CALLBACK_TIMEOUT_SECONDS:g}s"
    except httpx.ConnectError:
        error = "Connection refused (subscriber offline or unreachable)"
    except httpx.HTTPError as exc:
        error = f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__
    except Exception as exc:  # defensive: one bad callback must never break the rest
        error = f"Unexpected error: {type(exc).__name__}: {exc}"

    logger.warning("Delivery to %s failed: %s", subscriber_id, error)
    return {"subscriber_id": subscriber_id, "status": "failed", "error": error}


async def deliver(
    targets: Dict[str, str], payload: Dict[str, Any]
) -> List[Dict[str, Any]]:
    """Send the payload to all targets concurrently and collect the results."""
    timeout = httpx.Timeout(CALLBACK_TIMEOUT_SECONDS, connect=min(2.0, CALLBACK_TIMEOUT_SECONDS))
    async with httpx.AsyncClient(timeout=timeout) as client:
        return list(
            await asyncio.gather(
                *(
                    _deliver_one(client, sid, url, payload)
                    for sid, url in targets.items()
                )
            )
        )


# --------------------------------------------------------------------------- #
# Step 3: publish an event end-to-end
# --------------------------------------------------------------------------- #
async def publish_event(
    request: PublishRequest, registry: SubscriberRegistry
) -> Dict[str, Any]:
    targets, invalid = select_recipients(request.mode, request.recipients, registry)

    event_id = str(uuid.uuid4())
    base = {
        "event_id": event_id,
        "event_type": request.event_type,
        "mode": request.mode.value,
    }

    if not targets:  # broadcast with nobody registered
        return {
            "message": "No subscribers are registered; nothing to deliver",
            **base,
            "total_recipients": 0,
            "successful_deliveries": 0,
            "failed_deliveries": 0,
            "invalid_recipients": invalid,
            "results": [],
        }

    payload = {
        "event_id": event_id,
        "event_type": request.event_type,
        "message": request.message,
        "publisher": PUBLISHER_NAME,
        "mode": request.mode.value,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }

    logger.info(
        "Publishing '%s' (%s) to %d subscriber(s): %s",
        request.event_type, request.mode.value, len(targets), ", ".join(targets),
    )
    results = await deliver(targets, payload)

    successes = sum(1 for r in results if r["status"] == "success")
    return {
        "message": "Event processing completed",
        **base,
        "total_recipients": len(results),
        "successful_deliveries": successes,
        "failed_deliveries": len(results) - successes,
        "invalid_recipients": invalid,
        "results": results,
    }
