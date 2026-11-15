from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.day import Order
from app.schemas.plan import Alert


class EventType(str, Enum):
    NEW_ORDER = "NEW_ORDER"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    VISIT_DELAYED = "VISIT_DELAYED"
    ORDER_TRANSFERRED = "ORDER_TRANSFERRED"
    STAFF_UNAVAILABLE = "STAFF_UNAVAILABLE"
    TIME_TICK = "TIME_TICK"


class CancelReason(str, Enum):
    NOT_CONFIRMED = "NOT_CONFIRMED"
    CUSTOMER_REQUEST = "CUSTOMER_REQUEST"


class TransferredTo(str, Enum):
    STATION_EQUIPMENT = "STATION_EQUIPMENT"
    TRUNK_CABLE = "TRUNK_CABLE"


class UnavailableReason(str, Enum):
    VEHICLE_BREAKDOWN = "VEHICLE_BREAKDOWN"
    ILLNESS = "ILLNESS"
    OTHER = "OTHER"


class EventBase(BaseModel):
    model_config = ConfigDict(extra="ignore")

    event_id: str = Field(..., min_length=1)
    timestamp: datetime

    @model_validator(mode="after")
    def check_tz(self) -> "EventBase":
        if self.timestamp.tzinfo is None:
            raise ValueError("event timestamp must include timezone offset")
        return self


class NewOrderEvent(EventBase):
    type: Literal[EventType.NEW_ORDER]
    order: Order


class OrderCancelledEvent(EventBase):
    type: Literal[EventType.ORDER_CANCELLED]
    order_id: str = Field(..., min_length=1)
    reason: CancelReason


class VisitDelayedEvent(EventBase):
    type: Literal[EventType.VISIT_DELAYED]
    staff_id: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
    expected_end: datetime

    @model_validator(mode="after")
    def check_expected_end_tz(self) -> "VisitDelayedEvent":
        if self.expected_end.tzinfo is None:
            raise ValueError("expected_end must include timezone offset")
        return self


class OrderTransferredEvent(EventBase):
    type: Literal[EventType.ORDER_TRANSFERRED]
    staff_id: str = Field(..., min_length=1)
    order_id: str = Field(..., min_length=1)
    actual_end: datetime
    transferred_to: TransferredTo

    @model_validator(mode="after")
    def check_actual_end_tz(self) -> "OrderTransferredEvent":
        if self.actual_end.tzinfo is None:
            raise ValueError("actual_end must include timezone offset")
        return self


class StaffUnavailableEvent(EventBase):
    type: Literal[EventType.STAFF_UNAVAILABLE]
    staff_id: str = Field(..., min_length=1)
    until: Optional[datetime] = None
    reason: UnavailableReason

    @model_validator(mode="after")
    def check_until_tz(self) -> "StaffUnavailableEvent":
        if self.until is not None and self.until.tzinfo is None:
            raise ValueError("until must include timezone offset")
        return self


class TimeTickEvent(EventBase):
    type: Literal[EventType.TIME_TICK]


Event = Annotated[
    Union[
        NewOrderEvent,
        OrderCancelledEvent,
        VisitDelayedEvent,
        OrderTransferredEvent,
        StaffUnavailableEvent,
        TimeTickEvent,
    ],
    Field(discriminator="type"),
]


class EventResult(BaseModel):
    event_id: str
    accepted: bool
    duplicate: bool
    plan_version: int = Field(..., ge=1)
    as_of: datetime
    processing_ms: Optional[int] = Field(default=None, ge=0)
    changed_staff_ids: list[str] = Field(default_factory=list)
    new_alerts: list[Alert] = Field(default_factory=list)
    message: Optional[str] = None
