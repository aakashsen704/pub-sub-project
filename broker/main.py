"""Central broker: the REST API of the Pub-Sub system.

Run with:
    uvicorn broker.main:app --host 127.0.0.1 --port 8000
Interactive API docs (Swagger UI): http://localhost:8000/docs
"""
from __future__ import annotations

import logging

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from .models import (
    PublishRequest,
    PublishResponse,
    SubscribeRequest,
    SubscribeResponse,
    SubscribersResponse,
    UnsubscribeResponse,
)
from .publisher import PublishError, publish_event
from .registry import (
    DuplicateSubscriberError,
    SubscriberNotFoundError,
    SubscriberRegistry,
)

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s"
)
logger = logging.getLogger("broker")

app = FastAPI(
    title="Simple Pub-Sub Broker",
    description=(
        "Central broker of a Publish-Subscribe system using REST. Subscribers "
        "register a callback URL; publishers send events to /publish; the "
        "broker delivers them via HTTP POST (unicast, multicast or broadcast)."
    ),
    version="1.0.0",
)

# The single, in-memory subscriber registry (lost when the broker restarts).
registry = SubscriberRegistry()


# --------------------------------------------------------------------------- #
# Error handlers: turn domain errors into clean JSON responses
# --------------------------------------------------------------------------- #
def _error(status_code: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": detail})


@app.exception_handler(DuplicateSubscriberError)
async def _duplicate_handler(_: Request, exc: DuplicateSubscriberError) -> JSONResponse:
    return _error(status.HTTP_409_CONFLICT, str(exc))


@app.exception_handler(SubscriberNotFoundError)
async def _not_found_handler(_: Request, exc: SubscriberNotFoundError) -> JSONResponse:
    return _error(status.HTTP_404_NOT_FOUND, str(exc))


@app.exception_handler(PublishError)
async def _publish_error_handler(_: Request, exc: PublishError) -> JSONResponse:
    return _error(exc.status_code, exc.detail)


# Missing fields / wrong types / invalid mode are rejected automatically by
# FastAPI with HTTP 422 and a description of each problem.


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/", tags=["info"])
async def root() -> dict:
    """Basic service information."""
    return {
        "service": "Simple Pub-Sub Broker",
        "docs": "/docs",
        "registered_subscribers": len(registry),
        "endpoints": [
            "POST /subscribe",
            "DELETE /unsubscribe/{subscriber_id}",
            "GET /subscribers",
            "POST /publish",
        ],
    }


@app.post(
    "/subscribe",
    response_model=SubscribeResponse,
    status_code=status.HTTP_201_CREATED,
    tags=["subscribers"],
)
async def subscribe(request: SubscribeRequest) -> dict:
    """Register a subscriber (ID must be unique)."""
    subscriber = registry.register(request.subscriber_id, request.callback_url)
    logger.info("Registered %s -> %s", request.subscriber_id, request.callback_url)
    return {"message": "Subscriber registered successfully", "subscriber": subscriber}


@app.delete(
    "/unsubscribe/{subscriber_id}",
    response_model=UnsubscribeResponse,
    tags=["subscribers"],
)
async def unsubscribe(subscriber_id: str) -> dict:
    """Remove a subscriber from the registry."""
    registry.unregister(subscriber_id)
    logger.info("Unregistered %s", subscriber_id)
    return {"message": "Subscriber unregistered successfully", "subscriber_id": subscriber_id}


@app.get("/subscribers", response_model=SubscribersResponse, tags=["subscribers"])
async def list_subscribers() -> dict:
    """List all currently registered subscribers."""
    subscribers = registry.list_all()
    return {"total": len(subscribers), "subscribers": subscribers}


@app.post(
    "/publish",
    response_model=PublishResponse,
    response_model_exclude_none=True,
    tags=["publisher"],
)
async def publish(request: PublishRequest) -> dict:
    """Publish an event (unicast / multicast / broadcast) and return delivery results."""
    return await publish_event(request, registry)
