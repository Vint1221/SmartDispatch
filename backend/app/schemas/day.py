from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import BuildingType, Equipment, Technology, TimeWindow, WorkTypeCode


class Order(BaseModel):
    model_config = ConfigDict(extra="ignore")

    order_id: str = Field(..., min_length=1)
    work_type_code: WorkTypeCode
    technology: Technology
    building_id: str = Field(..., min_length=1)
    address: str
    lat: float
    lon: float
    building_type: BuildingType
    requires_height: bool
    access_node_id: str = Field(..., min_length=1)
    registered_at: datetime
    slot: TimeWindow
    latest_start: datetime
    deadline: datetime
    required_equipment: Equipment
    is_repeat: bool
    previous_order_id: Optional[str] = None
    target_staff_id: Optional[str] = None

    @model_validator(mode="after")
    def check_timezones(self) -> "Order":
        if (
            self.registered_at.tzinfo is None
            or self.slot.start.tzinfo is None
            or self.slot.end.tzinfo is None
            or self.latest_start.tzinfo is None
            or self.deadline.tzinfo is None
        ):
            raise ValueError("All order timestamps must include timezone offset")
        if self.slot.end < self.slot.start:
            raise ValueError("slot.end must be >= slot.start")
        return self


class DayInput(BaseModel):
    model_config = ConfigDict(extra="ignore")

    date: date_type
    now: datetime
    orders: list[Order]
    absent_staff_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_day(self) -> "DayInput":
        if self.now.tzinfo is None:
            raise ValueError("now must include timezone offset")
        if len(set(self.absent_staff_ids)) != len(self.absent_staff_ids):
            raise ValueError("absent_staff_ids must be unique")
        return self


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    time_limit_sec: int = Field(default=300, ge=1, le=300)
