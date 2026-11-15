from __future__ import annotations

from datetime import datetime, timedelta, tzinfo

from app.schemas.common import TimeWindow
from app.schemas.day import Order
from app.schemas.plan import (
    Alert,
    AlertStatus,
    AlertSuggestedAction,
    AlertType,
    PgpGroup,
)
from app.services.time_utils import norm_dt


class AlertService:
    """Manages append-only alerts per day (PGP_DETECTED, LATE_RISK, UNASSIGNED)."""

    def __init__(self, existing_alerts: list[Alert] | None = None) -> None:
        self.alerts: list[Alert] = list(existing_alerts or [])
        self._seq: int = len(self.alerts)

    def _next_id(self, date_str: str) -> str:
        self._seq += 1
        compact_date = date_str.replace("-", "")
        return f"ALR-{compact_date}-{self._seq:04d}"

    def add_pgp_alerts(
        self,
        new_groups: list[PgpGroup],
        as_of: datetime,
        day_tz: tzinfo,
        date_str: str,
    ) -> list[Alert]:
        created: list[Alert] = []
        now_dt = norm_dt(as_of, day_tz)
        for grp in new_groups:
            alr = Alert(
                alert_id=self._next_id(date_str),
                created_at=now_dt,
                type=AlertType.PGP_DETECTED,
                status=AlertStatus.ACTIVE,
                resolved_at=None,
                order_id=None,
                group_id=grp.group_id,
                staff_id=None,
                forecast_start=None,
                lateness_min=None,
                suggested_action=AlertSuggestedAction.TRANSFER_TO_STATION,
                suggested_staff_id=None,
                proposed_slot=None,
                applied=True,
                message=f"ПГП на {grp.access_node_id}, {len(grp.order_ids)} наряда переданы в станционное подразделение",
            )
            self.alerts.append(alr)
            created.append(alr)
        return created

    def add_late_risk_alert(
        self,
        order: Order,
        staff_id: str | None,
        forecast_start: datetime | None,
        lateness_min: int | None,
        suggested_action: AlertSuggestedAction,
        suggested_staff_id: str | None,
        proposed_slot: TimeWindow | None,
        applied: bool,
        resolved: bool,
        message: str,
        as_of: datetime,
        day_tz: tzinfo,
        date_str: str,
    ) -> Alert:
        now_dt = norm_dt(as_of, day_tz)
        # Avoid duplicate active LATE_RISK alert for same order & action at same timestamp
        for existing in self.alerts:
            if (
                existing.type == AlertType.LATE_RISK
                and existing.order_id == order.order_id
                and existing.suggested_staff_id == suggested_staff_id
                and existing.status == (AlertStatus.RESOLVED if resolved else AlertStatus.ACTIVE)
            ):
                return existing

        alr = Alert(
            alert_id=self._next_id(date_str),
            created_at=now_dt,
            type=AlertType.LATE_RISK,
            status=AlertStatus.RESOLVED if resolved else AlertStatus.ACTIVE,
            resolved_at=now_dt if resolved else None,
            order_id=order.order_id,
            group_id=None,
            staff_id=staff_id,
            forecast_start=norm_dt(forecast_start, day_tz) if forecast_start else None,
            lateness_min=lateness_min,
            suggested_action=suggested_action,
            suggested_staff_id=suggested_staff_id,
            proposed_slot=proposed_slot,
            applied=applied,
            message=message,
        )
        self.alerts.append(alr)
        return alr

    def sync_unassigned_alerts(
        self,
        unassigned_orders: dict[str, Order],
        assigned_order_ids: set[str],
        cancelled_order_ids: set[str],
        pgp_order_ids: set[str],
        as_of: datetime,
        day_tz: tzinfo,
        date_str: str,
    ) -> list[Alert]:
        now_dt = norm_dt(as_of, day_tz)
        created: list[Alert] = []

        # Resolve previously active UNASSIGNED alerts if order is now assigned/cancelled/PGP
        active_unassigned_orders: set[str] = set()
        for alr in self.alerts:
            if alr.type == AlertType.UNASSIGNED and alr.order_id:
                if alr.status == AlertStatus.ACTIVE:
                    if alr.order_id in assigned_order_ids or alr.order_id in cancelled_order_ids or alr.order_id in pgp_order_ids:
                        alr.status = AlertStatus.RESOLVED
                        alr.resolved_at = now_dt
                    else:
                        active_unassigned_orders.add(alr.order_id)

        for oid, order in sorted(unassigned_orders.items()):
            if oid in active_unassigned_orders:
                continue
            proposed = TimeWindow(
                start=norm_dt(order.slot.start + timedelta(days=1), day_tz),
                end=norm_dt(order.slot.end + timedelta(days=1), day_tz),
            )
            alr = Alert(
                alert_id=self._next_id(date_str),
                created_at=now_dt,
                type=AlertType.UNASSIGNED,
                status=AlertStatus.ACTIVE,
                resolved_at=None,
                order_id=oid,
                group_id=None,
                staff_id=None,
                forecast_start=None,
                lateness_min=None,
                suggested_action=AlertSuggestedAction.RESCHEDULE,
                suggested_staff_id=None,
                proposed_slot=proposed,
                applied=False,
                message=f"Наряд {oid} не распределён — рекомендуется перенос на следующий день",
            )
            self.alerts.append(alr)
            created.append(alr)

        return created
