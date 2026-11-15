from __future__ import annotations

from datetime import date as date_type
from typing import Optional
import logging

from fastapi import APIRouter, Body, Depends, Path
from sqlalchemy.orm import Session

from app.config import settings
from app.database.session import get_db
from app.demo_data import build_demo_dataset
from app.routing.osrm_demo import build_osrm_demo_matrix
from app.models.db_models import PlanSnapshotModel
from app.schemas.common import Health, LoadResult
from app.schemas.day import DayInput, PlanRequest
from app.schemas.events import Event, EventResult
from app.schemas.plan import Plan
from app.schemas.reference import ReferenceData, TravelMatrix
from app.services.dispatch_service import ApiDomainError, dispatch_service

router = APIRouter()
logger = logging.getLogger(__name__)


def _validate_date_str(date_val: date_type) -> str:
    return date_val.isoformat()


@router.get("/health", response_model=Health, tags=["service"])
def get_health() -> Health:
    return Health(status="ok", team=settings.team_name, version=settings.app_version)


@router.put("/reference", response_model=LoadResult, tags=["reference"])
def put_reference(
    payload: ReferenceData,
    db: Session = Depends(get_db),
) -> LoadResult:
    counts = dispatch_service.load_reference(db, payload)
    return LoadResult(status="loaded", counts=counts)


@router.put("/reference/travel-matrix", response_model=LoadResult, tags=["reference"])
def put_travel_matrix(
    payload: TravelMatrix,
    db: Session = Depends(get_db),
) -> LoadResult:
    counts = dispatch_service.load_travel_matrix(db, payload)
    return LoadResult(status="loaded", counts=counts)


@router.put("/days/{date}", response_model=LoadResult, tags=["day"])
def put_day(
    payload: DayInput,
    date: date_type = Path(..., description="Рабочий день YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> LoadResult:
    counts = dispatch_service.load_day(db, _validate_date_str(date), payload)
    return LoadResult(status="loaded", counts=counts)


@router.post("/days/{date}/plan", response_model=Plan, tags=["plan"])
def build_plan(
    date: date_type = Path(..., description="Рабочий день YYYY-MM-DD"),
    payload: Optional[PlanRequest] = Body(default=None),
    db: Session = Depends(get_db),
) -> Plan:
    limit = payload.time_limit_sec if payload is not None else 300
    return dispatch_service.build_plan(db, _validate_date_str(date), time_limit_sec=limit)


@router.get("/days/{date}/plan", response_model=Plan, tags=["plan"])
def get_plan(
    date: date_type = Path(..., description="Рабочий день YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> Plan:
    return dispatch_service.get_plan(db, _validate_date_str(date))


@router.post("/days/{date}/events", response_model=EventResult, tags=["events"])
def post_event(
    payload: Event,
    date: date_type = Path(..., description="Рабочий день YYYY-MM-DD"),
    db: Session = Depends(get_db),
) -> EventResult:
    return dispatch_service.process_event(db, _validate_date_str(date), payload)


# ---------- Дополнительные UI / DEMO эндпоинты (разрешены п. 7 спецификации) ----------


@router.post("/ui/demo/bootstrap", tags=["ui"])
def ui_demo_bootstrap(
    num_orders: int = 90,
    date: str = "2026-10-26",
    db: Session = Depends(get_db),
) -> dict:
    ref, matrix, day_input, demo_events = build_demo_dataset(date_str=date, num_orders=max(20, min(num_orders, 400)))
    matrix_source = "SYNTHETIC_FALLBACK"
    try:
        matrix = build_osrm_demo_matrix(ref, matrix)
        matrix_source = "OSRM_DRIVING"
    except Exception as exc:  # DEMO remains usable if the public routing server is unavailable.
        logger.warning("OSRM DEMO matrix unavailable; using synthetic fallback: %s", exc)
    ref_counts = dispatch_service.load_reference(db, ref)
    matrix_counts = dispatch_service.load_travel_matrix(db, matrix)
    day_counts = dispatch_service.load_day(db, date, day_input)
    plan = dispatch_service.build_plan(db, date, time_limit_sec=30)
    return {
        "demo": True,
        "date": date,
        "matrix_source": matrix_source,
        "counts": {**ref_counts, **matrix_counts, **day_counts},
        "plan": plan.model_dump(mode="json"),
        "demo_events": demo_events,
    }


@router.get("/ui/state", tags=["ui"])
def ui_state(db: Session = Depends(get_db)) -> dict:
    snap = db.query(PlanSnapshotModel).order_by(PlanSnapshotModel.id.desc()).first()
    if snap is None:
        return {"has_plan": False, "date": None}
    return {"has_plan": True, "date": snap.day_date}


@router.get("/ui/days/{date}/context", tags=["ui"])
def ui_day_context(
    date: date_type = Path(...),
    db: Session = Depends(get_db),
) -> dict:
    date_str = _validate_date_str(date)
    ref, _ = dispatch_service._ensure_ref_and_matrix(db)
    state = dispatch_service._get_day_state(db, date_str)
    if state.current_plan is None:
        raise ApiDomainError(404, "PLAN_NOT_FOUND", f"План на {date_str} ещё не построен")
    return {
        "plan": state.current_plan.model_dump(mode="json"),
        "service_centers": [sc.model_dump(mode="json") for sc in ref.service_centers],
        "staff": [st.model_dump(mode="json", by_alias=True) for st in ref.staff if st.staff_id not in state.absent_staff_ids],
        "orders": {oid: o.model_dump(mode="json") for oid, o in state.orders_by_id.items()},
        "events": [r.model_dump(mode="json") for r in state.accepted_events.values()],
        "work_types": [wt.model_dump(mode="json") for wt in ref.work_types],
        "access_nodes": [an.model_dump(mode="json") for an in ref.access_nodes],
    }
