from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from app.schemas.common import Equipment, TimeWindow


class RouteStatus(str, Enum):
    ACTIVE = "ACTIVE"
    UNAVAILABLE = "UNAVAILABLE"


class StopType(str, Enum):
    DEPOT_START = "DEPOT_START"
    VISIT = "VISIT"
    BREAK = "BREAK"
    RESTOCK = "RESTOCK"
    DEPOT_END = "DEPOT_END"


class StopStatus(str, Enum):
    PLANNED = "PLANNED"
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"


class Stop(BaseModel):
    model_config = ConfigDict(extra="ignore")

    seq: int = Field(..., ge=1)
    type: StopType
    location_id: str
    order_id: Optional[str] = None
    arrival: datetime
    start: datetime
    end: datetime
    travel_sec: Optional[int] = Field(default=None, ge=0)
    distance_m: Optional[int] = Field(default=None, ge=0)
    status: Optional[StopStatus] = None
    equipment_after: Optional[Equipment] = None
    explanation: Optional[str] = None


class RouteTotals(BaseModel):
    visits: int = Field(default=0, ge=0)
    travel_sec: int = Field(default=0, ge=0)
    distance_m: int = Field(default=0, ge=0)
    work_min: int = Field(default=0, ge=0)
    utilization: float = Field(default=0.0, ge=0.0)


class Route(BaseModel):
    staff_id: str
    service_center_id: str
    status: RouteStatus
    unavailable_from: Optional[datetime] = None
    unavailable_until: Optional[datetime] = None
    stops: list[Stop]
    totals: Optional[RouteTotals] = None


class UnassignedReasonCode(str, Enum):
    NO_QUALIFIED_STAFF = "NO_QUALIFIED_STAFF"
    NO_SHIFT_TIME = "NO_SHIFT_TIME"
    SLOT_UNREACHABLE = "SLOT_UNREACHABLE"
    NO_EQUIPMENT = "NO_EQUIPMENT"
    STAFF_UNAVAILABLE = "STAFF_UNAVAILABLE"
    OTHER = "OTHER"


class UnassignedSuggestedAction(str, Enum):
    RESCHEDULE = "RESCHEDULE"
    REASSIGN = "REASSIGN"
    ESCALATE = "ESCALATE"


class UnassignedOrder(BaseModel):
    order_id: str
    reason_code: UnassignedReasonCode
    reason_text: str
    suggested_action: UnassignedSuggestedAction
    proposed_slot: Optional[TimeWindow] = None
    since: Optional[datetime] = None


class PgpAction(str, Enum):
    TRANSFER_TO_STATION = "TRANSFER_TO_STATION"


class PgpGroup(BaseModel):
    group_id: str
    access_node_id: str
    order_ids: list[str] = Field(..., min_length=2)
    detected_at: datetime
    action: PgpAction = PgpAction.TRANSFER_TO_STATION
    comment: Optional[str] = None


class CancelledOrder(BaseModel):
    order_id: str
    cancelled_at: datetime
    event_id: Optional[str] = None


class AlertType(str, Enum):
    LATE_RISK = "LATE_RISK"
    PGP_DETECTED = "PGP_DETECTED"
    UNASSIGNED = "UNASSIGNED"


class AlertStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RESOLVED = "RESOLVED"


class AlertSuggestedAction(str, Enum):
    REASSIGN = "REASSIGN"
    RESCHEDULE = "RESCHEDULE"
    TRANSFER_TO_STATION = "TRANSFER_TO_STATION"
    NONE = "NONE"


class Alert(BaseModel):
    alert_id: str
    created_at: datetime
    type: AlertType
    status: AlertStatus
    resolved_at: Optional[datetime] = None
    order_id: Optional[str] = None
    group_id: Optional[str] = None
    staff_id: Optional[str] = None
    forecast_start: Optional[datetime] = None
    lateness_min: Optional[int] = None
    suggested_action: AlertSuggestedAction
    suggested_staff_id: Optional[str] = None
    proposed_slot: Optional[TimeWindow] = None
    applied: bool = False
    message: str


class PlanSummary(BaseModel):
    orders_total: int
    visits_planned: int
    unassigned: int
    pgp_orders: int
    cancelled: int
    travel_sec_total: int
    utilization_cv: float


class Plan(BaseModel):
    date: date_type
    plan_version: int = Field(..., ge=1)
    based_on_event_id: Optional[str] = None
    as_of: datetime
    computation_ms: Optional[int] = Field(default=None, ge=0)
    routes: list[Route]
    unassigned: list[UnassignedOrder]
    pgp_groups: list[PgpGroup]
    cancelled: list[CancelledOrder]
    alerts: list[Alert]
    summary: Optional[PlanSummary] = None
