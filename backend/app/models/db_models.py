from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.database.session import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ServiceCenterModel(Base):
    __tablename__ = "service_centers"

    service_center_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str] = mapped_column(String(512))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    open_time: Mapped[str] = mapped_column(String(8))
    close_time: Mapped[str] = mapped_column(String(8))
    restock_duration_min: Mapped[int] = mapped_column(Integer)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class StaffModel(Base):
    __tablename__ = "staff"

    staff_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    service_center_id: Mapped[str] = mapped_column(String(64), index=True)
    height_permit: Mapped[bool] = mapped_column(Boolean)
    experience_years: Mapped[float | None] = mapped_column(Float, nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class AccessNodeModel(Base):
    __tablename__ = "access_nodes"

    access_node_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_type: Mapped[str] = mapped_column(String(32))
    technology: Mapped[str] = mapped_column(String(32))
    name: Mapped[str] = mapped_column(String(255))
    address: Mapped[str | None] = mapped_column(String(512), nullable=True)
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class BuildingModel(Base):
    __tablename__ = "buildings"

    building_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    address: Mapped[str] = mapped_column(String(512))
    lat: Mapped[float] = mapped_column(Float)
    lon: Mapped[float] = mapped_column(Float)
    building_type: Mapped[str] = mapped_column(String(32))
    overhead_line: Mapped[bool] = mapped_column(Boolean)
    zone_service_center_id: Mapped[str | None] = mapped_column(String(64), nullable=True)


class AccessNodeBuildingModel(Base):
    __tablename__ = "access_node_buildings"

    access_node_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("access_nodes.access_node_id", ondelete="CASCADE"), primary_key=True
    )
    building_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("buildings.building_id", ondelete="CASCADE"), primary_key=True
    )


class WorkTypeModel(Base):
    __tablename__ = "work_types"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    duration_min: Mapped[int] = mapped_column(Integer)
    max_start_delay_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    deadline_kind: Mapped[str] = mapped_column(String(32))
    deadline_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    repeat_deadline_value: Mapped[int | None] = mapped_column(Integer, nullable=True)
    pgp_relevant: Mapped[bool] = mapped_column(Boolean)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class TravelMatrixModel(Base):
    __tablename__ = "travel_matrices"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    matrix_id: Mapped[str] = mapped_column(String(128))
    points_count: Mapped[int] = mapped_column(Integer)
    compressed_blob: Mapped[bytes] = mapped_column(LargeBinary)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class DayModel(Base):
    __tablename__ = "days"

    date: Mapped[str] = mapped_column(String(16), primary_key=True)
    now_iso: Mapped[str] = mapped_column(String(64))
    as_of_iso: Mapped[str] = mapped_column(String(64))
    plan_version: Mapped[int] = mapped_column(Integer, default=0)
    based_on_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    absent_staff_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    staff_unavailability: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class OrderModel(Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("day_date", "order_id", name="uq_day_order"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_date: Mapped[str] = mapped_column(String(16), ForeignKey("days.date", ondelete="CASCADE"), index=True)
    order_id: Mapped[str] = mapped_column(String(64), index=True)
    access_node_id: Mapped[str] = mapped_column(String(64), index=True)
    work_type_code: Mapped[str] = mapped_column(String(64))
    is_cancelled: Mapped[bool] = mapped_column(Boolean, default=False)
    cancelled_at: Mapped[str | None] = mapped_column(String(64), nullable=True)
    cancel_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    override_end_iso: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_transferred_on_site: Mapped[bool] = mapped_column(Boolean, default=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class PlanSnapshotModel(Base):
    __tablename__ = "plan_snapshots"
    __table_args__ = (UniqueConstraint("day_date", "plan_version", name="uq_day_plan_version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_date: Mapped[str] = mapped_column(String(16), ForeignKey("days.date", ondelete="CASCADE"), index=True)
    plan_version: Mapped[int] = mapped_column(Integer)
    based_on_event_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    as_of_iso: Mapped[str] = mapped_column(String(64))
    plan_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class EventLogModel(Base):
    __tablename__ = "event_logs"
    __table_args__ = (UniqueConstraint("day_date", "event_id", name="uq_day_event_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_date: Mapped[str] = mapped_column(String(16), ForeignKey("days.date", ondelete="CASCADE"), index=True)
    event_id: Mapped[str] = mapped_column(String(128), index=True)
    event_type: Mapped[str] = mapped_column(String(64))
    timestamp_iso: Mapped[str] = mapped_column(String(64))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AlertModel(Base):
    __tablename__ = "alerts"
    __table_args__ = (UniqueConstraint("day_date", "alert_id", name="uq_day_alert_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_date: Mapped[str] = mapped_column(String(16), ForeignKey("days.date", ondelete="CASCADE"), index=True)
    alert_id: Mapped[str] = mapped_column(String(128))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON)


class PgpGroupModel(Base):
    __tablename__ = "pgp_groups"
    __table_args__ = (UniqueConstraint("day_date", "group_id", name="uq_day_pgp_group"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    day_date: Mapped[str] = mapped_column(String(16), ForeignKey("days.date", ondelete="CASCADE"), index=True)
    group_id: Mapped[str] = mapped_column(String(128))
    access_node_id: Mapped[str] = mapped_column(String(64))
    detected_at_iso: Mapped[str] = mapped_column(String(64))
    order_ids: Mapped[list[str]] = mapped_column(JSON)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
