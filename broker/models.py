"""Request and response schemas (Pydantic) for the broker's REST API."""
from __future__ import annotations

from enum import Enum
from typing import List, Literal, Optional
from urllib.parse import urlparse

from pydantic import BaseModel, Field, field_validator


class CommunicationMode(str, Enum):
    """The three group-communication modes supported by the broker."""

    UNICAST = "unicast"      # one specific subscriber
    MULTICAST = "multicast"  # a selected group of subscribers
    BROADCAST = "broadcast"  # every registered subscriber


# --------------------------------------------------------------------------- #
# Subscription
# --------------------------------------------------------------------------- #
class SubscribeRequest(BaseModel):
    subscriber_id: str = Field(
        ...,
        min_length=1,
        max_length=64,
        pattern=r"^[A-Za-z0-9_.-]+$",
        description="Unique subscriber ID (letters, digits, '_', '-', '.').",
        examples=["student_A"],
    )
    callback_url: str = Field(
        ...,
        description="URL the broker will POST events to.",
        examples=["http://localhost:5001/notify"],
    )

    @field_validator("callback_url")
    @classmethod
    def _validate_callback_url(cls, value: str) -> str:
        value = value.strip()
        parsed = urlparse(value)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            raise ValueError(
                "callback_url must be a valid http:// or https:// URL, "
                "e.g. http://localhost:5001/notify"
            )
        return value


class SubscriberInfo(BaseModel):
    subscriber_id: str
    callback_url: str
    registered_at: str


class SubscribeResponse(BaseModel):
    message: str
    subscriber: SubscriberInfo


class UnsubscribeResponse(BaseModel):
    message: str
    subscriber_id: str


class SubscribersResponse(BaseModel):
    total: int
    subscribers: List[SubscriberInfo]


# --------------------------------------------------------------------------- #
# Publishing
# --------------------------------------------------------------------------- #
class PublishRequest(BaseModel):
    event_type: str = Field(..., min_length=1, examples=["holiday_announcement"])
    message: str = Field(..., min_length=1, examples=["Tomorrow is a holiday!"])
    mode: CommunicationMode = Field(..., examples=["broadcast"])
    recipients: Optional[List[str]] = Field(
        default=None,
        description=(
            "Subscriber IDs. Required for unicast (exactly one) and multicast "
            "(one or more). Ignored for broadcast."
        ),
        examples=[["student_A", "student_C"]],
    )


class DeliveryResult(BaseModel):
    subscriber_id: str
    status: Literal["success", "failed"]
    http_status: Optional[int] = None
    error: Optional[str] = None


class PublishResponse(BaseModel):
    message: str
    event_id: str
    event_type: str
    mode: CommunicationMode
    total_recipients: int
    successful_deliveries: int
    failed_deliveries: int
    invalid_recipients: List[str] = Field(
        default_factory=list,
        description="Requested recipient IDs that are not registered (multicast).",
    )
    results: List[DeliveryResult]
