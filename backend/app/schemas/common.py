from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class Technology(str, Enum):
    PON = "PON"
    FTTB = "FTTB"
    XDSL = "XDSL"
    DOCSIS = "DOCSIS"


class Profile(str, Enum):
    INSTALL = "INSTALL"
    LTP3 = "LTP3"


class WorkTypeCode(str, Enum):
    INST_PON_MKD = "INST_PON_MKD"
    INST_FTTB_MKD = "INST_FTTB_MKD"
    INST_PRIVATE_VLS = "INST_PRIVATE_VLS"
    ADD_SERVICE = "ADD_SERVICE"
    SURVEY_PRIVATE = "SURVEY_PRIVATE"
    REPAIR = "REPAIR"
    DEGRADATION = "DEGRADATION"
    DISMANTLE = "DISMANTLE"


class BuildingType(str, Enum):
    MKD = "MKD"
    PRIVATE = "PRIVATE"


class Equipment(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ONT: int = Field(..., ge=0)
    ROUTER: int = Field(..., ge=0)
    STB: int = Field(..., ge=0)

    def can_supply(self, req: "Equipment") -> bool:
        return self.ONT >= req.ONT and self.ROUTER >= req.ROUTER and self.STB >= req.STB

    def subtract(self, req: "Equipment") -> "Equipment":
        return Equipment(
            ONT=self.ONT - req.ONT,
            ROUTER=self.ROUTER - req.ROUTER,
            STB=self.STB - req.STB,
        )


class TimeWindow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start: datetime
    end: datetime


class Health(BaseModel):
    status: str = "ok"
    team: Optional[str] = None
    version: Optional[str] = None


class LoadResult(BaseModel):
    status: str = "loaded"
    counts: dict[str, int] = Field(default_factory=dict)


class ErrorDetail(BaseModel):
    field: Optional[str] = None
    message: str


class ErrorBody(BaseModel):
    code: str
    message: str
    details: list[ErrorDetail] = Field(default_factory=list)


class ErrorResponse(BaseModel):
    error: ErrorBody


def make_error(code: str, message: str, details: Optional[list[dict[str, Any]]] = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details or [],
        }
    }
