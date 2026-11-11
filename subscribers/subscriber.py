"""Reusable subscriber application.

One file, many independent processes - each instance gets its own ID and port:

    python -m subscribers.subscriber --id student_A --port 5001
    python -m subscribers.subscriber --id student_B --port 5002
    python -m subscribers.subscriber --id student_C --port 5003

The subscriber exposes ``POST /notify``; the broker calls it over HTTP whenever
an event is delivered to this subscriber.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
from typing import Optional

import httpx
import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel

BANNER_WIDTH = 33


class Event(BaseModel):
    """Payload sent by the broker (see broker/publisher.py)."""

    event_type: str
    message: str
    mode: str
    publisher: str = "unknown"
    event_id: Optional[str] = None
    timestamp: Optional[str] = None


def print_notification(subscriber_id: str, event: Event) -> None:
    line = "=" * BANNER_WIDTH
    print(
        f"\n{line}\n"
        f"SUBSCRIBER {subscriber_id}\n"
        f"{line}\n"
        f"New Event Received!\n\n"
        f"Event: {event.event_type}\n"
        f"Message: {event.message}\n"
        f"Mode: {event.mode}\n"
        f"From: {event.publisher}\n"
        f"{line}",
        flush=True,
    )


def create_app(
    subscriber_id: str,
    delay: float = 0.0,
    register_url: Optional[str] = None,
    callback_url: Optional[str] = None,
) -> FastAPI:
    """Build the subscriber's FastAPI app.

    delay        - artificial seconds to wait before replying (simulates a slow
                   subscriber, useful for demonstrating the broker's timeout).
    register_url - if given, register with the broker at startup
                   (e.g. http://localhost:8000); otherwise register manually.
    """

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if register_url:
            try:
                async with httpx.AsyncClient(timeout=5.0) as client:
                    resp = await client.post(
                        f"{register_url.rstrip('/')}/subscribe",
                        json={"subscriber_id": subscriber_id, "callback_url": callback_url},
                    )
                print(f"[{subscriber_id}] Auto-register: HTTP {resp.status_code} {resp.text}", flush=True)
            except httpx.HTTPError as exc:
                print(f"[{subscriber_id}] Auto-register failed: {exc}", flush=True)
        yield

    app = FastAPI(title=f"Subscriber {subscriber_id}", lifespan=lifespan)

    @app.post("/notify")
    async def notify(event: Event) -> dict:
        """Callback endpoint called by the broker."""
        print_notification(subscriber_id, event)
        if delay > 0:
            await asyncio.sleep(delay)
        return {
            "status": "received",
            "subscriber_id": subscriber_id,
            "event_type": event.event_type,
        }

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok", "subscriber_id": subscriber_id}

    return app


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Pub-Sub subscriber application")
    parser.add_argument("--id", required=True, dest="subscriber_id",
                        help="subscriber ID, e.g. student_A")
    parser.add_argument("--port", required=True, type=int, help="port to listen on")
    parser.add_argument("--host", default="127.0.0.1", help="interface to bind (default 127.0.0.1)")
    parser.add_argument("--register", action="store_true",
                        help="automatically register with the broker at startup")
    parser.add_argument("--broker-url", default="http://localhost:8000",
                        help="broker base URL used with --register (default http://localhost:8000)")
    parser.add_argument("--delay", type=float, default=0.0,
                        help="simulate a slow subscriber: seconds to wait before replying")
    return parser.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    public_host = "127.0.0.1" if args.host in ("0.0.0.0", "") else args.host
    callback_url = f"http://{public_host}:{args.port}/notify"

    app = create_app(
        args.subscriber_id,
        delay=args.delay,
        register_url=args.broker_url if args.register else None,
        callback_url=callback_url,
    )
    print(f"Subscriber '{args.subscriber_id}' listening on {callback_url}", flush=True)
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
