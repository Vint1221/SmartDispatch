"""Initial Smart Dispatch schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-26 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "service_centers",
        sa.Column("service_center_id", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=512), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("open_time", sa.String(length=8), nullable=False),
        sa.Column("close_time", sa.String(length=8), nullable=False),
        sa.Column("restock_duration_min", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "staff",
        sa.Column("staff_id", sa.String(length=64), primary_key=True),
        sa.Column("display_name", sa.String(length=255), nullable=True),
        sa.Column("service_center_id", sa.String(length=64), nullable=False),
        sa.Column("height_permit", sa.Boolean(), nullable=False),
        sa.Column("experience_years", sa.Float(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_index("ix_staff_service_center_id", "staff", ["service_center_id"])

    op.create_table(
        "access_nodes",
        sa.Column("access_node_id", sa.String(length=64), primary_key=True),
        sa.Column("node_type", sa.String(length=32), nullable=False),
        sa.Column("technology", sa.String(length=32), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("address", sa.String(length=512), nullable=True),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "buildings",
        sa.Column("building_id", sa.String(length=64), primary_key=True),
        sa.Column("address", sa.String(length=512), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("building_type", sa.String(length=32), nullable=False),
        sa.Column("overhead_line", sa.Boolean(), nullable=False),
        sa.Column("zone_service_center_id", sa.String(length=64), nullable=True),
    )
    op.create_table(
        "access_node_buildings",
        sa.Column(
            "access_node_id",
            sa.String(length=64),
            sa.ForeignKey("access_nodes.access_node_id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "building_id",
            sa.String(length=64),
            sa.ForeignKey("buildings.building_id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_table(
        "work_types",
        sa.Column("code", sa.String(length=64), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("duration_min", sa.Integer(), nullable=False),
        sa.Column("max_start_delay_min", sa.Integer(), nullable=True),
        sa.Column("deadline_kind", sa.String(length=32), nullable=False),
        sa.Column("deadline_value", sa.Integer(), nullable=True),
        sa.Column("repeat_deadline_value", sa.Integer(), nullable=True),
        sa.Column("pgp_relevant", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
    )
    op.create_table(
        "travel_matrices",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("matrix_id", sa.String(length=128), nullable=False),
        sa.Column("points_count", sa.Integer(), nullable=False),
        sa.Column("compressed_blob", sa.LargeBinary(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "days",
        sa.Column("date", sa.String(length=16), primary_key=True),
        sa.Column("now_iso", sa.String(length=64), nullable=False),
        sa.Column("as_of_iso", sa.String(length=64), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("based_on_event_id", sa.String(length=128), nullable=True),
        sa.Column("absent_staff_ids", sa.JSON(), nullable=False),
        sa.Column("staff_unavailability", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "orders",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_date", sa.String(length=16), sa.ForeignKey("days.date", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", sa.String(length=64), nullable=False),
        sa.Column("access_node_id", sa.String(length=64), nullable=False),
        sa.Column("work_type_code", sa.String(length=64), nullable=False),
        sa.Column("is_cancelled", sa.Boolean(), nullable=False),
        sa.Column("cancelled_at", sa.String(length=64), nullable=True),
        sa.Column("cancel_event_id", sa.String(length=128), nullable=True),
        sa.Column("override_end_iso", sa.String(length=64), nullable=True),
        sa.Column("is_transferred_on_site", sa.Boolean(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("day_date", "order_id", name="uq_day_order"),
    )
    op.create_index("ix_orders_day_date", "orders", ["day_date"])
    op.create_index("ix_orders_order_id", "orders", ["order_id"])
    op.create_index("ix_orders_access_node_id", "orders", ["access_node_id"])

    op.create_table(
        "plan_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_date", sa.String(length=16), sa.ForeignKey("days.date", ondelete="CASCADE"), nullable=False),
        sa.Column("plan_version", sa.Integer(), nullable=False),
        sa.Column("based_on_event_id", sa.String(length=128), nullable=True),
        sa.Column("as_of_iso", sa.String(length=64), nullable=False),
        sa.Column("plan_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("day_date", "plan_version", name="uq_day_plan_version"),
    )
    op.create_index("ix_plan_snapshots_day_date", "plan_snapshots", ["day_date"])

    op.create_table(
        "event_logs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_date", sa.String(length=16), sa.ForeignKey("days.date", ondelete="CASCADE"), nullable=False),
        sa.Column("event_id", sa.String(length=128), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("timestamp_iso", sa.String(length=64), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("result_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("day_date", "event_id", name="uq_day_event_id"),
    )
    op.create_index("ix_event_logs_day_date", "event_logs", ["day_date"])
    op.create_index("ix_event_logs_event_id", "event_logs", ["event_id"])

    op.create_table(
        "alerts",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_date", sa.String(length=16), sa.ForeignKey("days.date", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_id", sa.String(length=128), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.UniqueConstraint("day_date", "alert_id", name="uq_day_alert_id"),
    )
    op.create_index("ix_alerts_day_date", "alerts", ["day_date"])

    op.create_table(
        "pgp_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("day_date", sa.String(length=16), sa.ForeignKey("days.date", ondelete="CASCADE"), nullable=False),
        sa.Column("group_id", sa.String(length=128), nullable=False),
        sa.Column("access_node_id", sa.String(length=64), nullable=False),
        sa.Column("detected_at_iso", sa.String(length=64), nullable=False),
        sa.Column("order_ids", sa.JSON(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.UniqueConstraint("day_date", "group_id", name="uq_day_pgp_group"),
    )
    op.create_index("ix_pgp_groups_day_date", "pgp_groups", ["day_date"])


def downgrade() -> None:
    op.drop_table("pgp_groups")
    op.drop_table("alerts")
    op.drop_table("event_logs")
    op.drop_table("plan_snapshots")
    op.drop_table("orders")
    op.drop_table("days")
    op.drop_table("travel_matrices")
    op.drop_table("work_types")
    op.drop_table("access_node_buildings")
    op.drop_table("buildings")
    op.drop_table("access_nodes")
    op.drop_table("staff")
    op.drop_table("service_centers")
