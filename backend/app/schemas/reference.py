from __future__ import annotations

from enum import Enum
from typing import Annotated, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.schemas.common import BuildingType, Equipment, Profile, Technology, WorkTypeCode

LocalTimeStr = Annotated[str, Field(pattern=r"^([01][0-9]|2[0-3]):[0-5][0-9]$")]


class OpeningHours(BaseModel):
    model_config = ConfigDict(extra="forbid")

    open: LocalTimeStr
    close: LocalTimeStr


class ServiceCenter(BaseModel):
    model_config = ConfigDict(extra="ignore")

    service_center_id: str = Field(..., min_length=1)
    name: str
    address: str
    lat: float = Field(..., ge=-90.0, le=90.0)
    lon: float = Field(..., ge=-180.0, le=180.0)
    opening_hours: OpeningHours
    restock_duration_min: int = Field(..., ge=0)


class BreakWindow(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    from_: LocalTimeStr = Field(..., alias="from")
    to: LocalTimeStr


class Shift(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: LocalTimeStr
    end: LocalTimeStr
    break_duration_min: int = Field(..., ge=0)
    break_window: BreakWindow


class Staff(BaseModel):
    model_config = ConfigDict(extra="ignore")

    staff_id: str = Field(..., min_length=1)
    display_name: Optional[str] = None
    service_center_id: str = Field(..., min_length=1)
    profiles: list[Profile] = Field(..., min_length=1)
    technologies: list[Technology] = Field(..., min_length=1)
    height_permit: bool
    shift: Shift
    equipment_start: Equipment
    equipment_capacity: Equipment
    experience_years: Optional[float] = Field(default=None, ge=0.0)


class Building(BaseModel):
    model_config = ConfigDict(extra="ignore")

    building_id: str = Field(..., min_length=1)
    address: str
    lat: float
    lon: float
    building_type: BuildingType
    overhead_line: bool
    zone_service_center_id: Optional[str] = None


class NodeType(str, Enum):
    OLT = "OLT"
    SWITCH = "SWITCH"
    DSLAM = "DSLAM"
    CMTS = "CMTS"


class AccessNode(BaseModel):
    model_config = ConfigDict(extra="ignore")

    access_node_id: str = Field(..., min_length=1)
    node_type: NodeType
    technology: Technology
    name: str
    address: Optional[str] = None
    lat: float
    lon: float
    buildings: list[Building] = Field(..., min_length=1)


class DeadlineKind(str, Enum):
    SLOT = "SLOT"
    HOURS = "HOURS"
    WORKING_DAYS = "WORKING_DAYS"


class WorkType(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: WorkTypeCode
    name: str
    profiles: list[Profile] = Field(..., min_length=1)
    duration_min: int = Field(..., ge=1)
    max_start_delay_min: Optional[int] = Field(default=None, ge=0)
    deadline_kind: DeadlineKind
    deadline_value: Optional[int] = Field(default=None, ge=1)
    repeat_deadline_value: Optional[int] = Field(default=None, ge=1)
    pgp_relevant: bool


class ReferenceData(BaseModel):
    model_config = ConfigDict(extra="ignore")

    service_centers: list[ServiceCenter] = Field(..., min_length=1)
    staff: list[Staff] = Field(..., min_length=1)
    access_nodes: list[AccessNode] = Field(..., min_length=1)
    work_types: list[WorkType] = Field(..., min_length=1)


class HourlyFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    hour: int = Field(..., ge=0, le=23)
    factor: float = Field(..., ge=0.0)


class TravelMatrix(BaseModel):
    model_config = ConfigDict(extra="ignore")

    matrix_id: str = Field(..., min_length=1)
    points: list[str] = Field(..., min_length=2)
    durations_sec: list[list[int]]
    distances_m: list[list[int]]
    hourly_factors: Optional[list[HourlyFactor]] = None

    @model_validator(mode="after")
    def check_dimensions(self) -> "TravelMatrix":
        n = len(self.points)
        if len(set(self.points)) != n:
            raise ValueError("points must contain unique identifiers")
        if len(self.durations_sec) != n or any(len(row) != n for row in self.durations_sec):
            raise ValueError(f"durations_sec must be an {n}x{n} square matrix")
        if len(self.distances_m) != n or any(len(row) != n for row in self.distances_m):
            raise ValueError(f"distances_m must be an {n}x{n} square matrix")
        for i in range(n):
            if self.durations_sec[i][i] != 0 or self.distances_m[i][i] != 0:
                raise ValueError("travel time and distance from a point to itself must be 0")
            for j in range(n):
                if self.durations_sec[i][j] < 0:
                    raise ValueError("durations_sec values must be >= 0")
                if self.distances_m[i][j] < 0:
                    raise ValueError("distances_m values must be >= 0")
        return self
