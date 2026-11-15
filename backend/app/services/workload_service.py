from __future__ import annotations

import math
from datetime import date as date_type
from datetime import tzinfo

from app.schemas.plan import (
    CancelledOrder,
    PgpGroup,
    PlanSummary,
    Route,
    RouteStatus,
    RouteTotals,
    StopType,
    UnassignedOrder,
)
from app.schemas.reference import Staff
from app.services.time_utils import local_hhmm_to_dt


class WorkloadService:
    """Computes route totals, staff utilization in minutes, and coefficient of variation (CV)."""

    @staticmethod
    def compute_route_totals(
        route: Route,
        staff: Staff,
        day_date: date_type,
        day_tz: tzinfo,
    ) -> RouteTotals:
        visits = 0
        travel_sec = 0
        distance_m = 0
        work_sec = 0

        for stop in route.stops:
            if stop.travel_sec:
                travel_sec += stop.travel_sec
            if stop.distance_m:
                distance_m += stop.distance_m
            if stop.type == StopType.VISIT:
                visits += 1
                work_sec += max(0, int((stop.end - stop.start).total_seconds()))

        shift_start = local_hhmm_to_dt(day_date, staff.shift.start, day_tz)
        shift_end = local_hhmm_to_dt(day_date, staff.shift.end, day_tz)
        avail_sec = max(1, int((shift_end - shift_start).total_seconds()) - staff.shift.break_duration_min * 60)
        utilization = round((work_sec + travel_sec) / avail_sec, 4)

        return RouteTotals(
            visits=visits,
            travel_sec=travel_sec,
            distance_m=distance_m,
            work_min=int(round(work_sec / 60.0)),
            utilization=utilization,
        )

    @staticmethod
    def compute_utilization_cv(routes: list[Route]) -> float:
        utils = [
            r.totals.utilization
            for r in routes
            if r.totals is not None and r.status == RouteStatus.ACTIVE
        ]
        if not utils:
            return 0.0
        mean_u = sum(utils) / len(utils)
        if mean_u <= 1e-9:
            return 0.0
        variance = sum((u - mean_u) ** 2 for u in utils) / len(utils)
        return round(math.sqrt(variance) / mean_u, 4)

    @classmethod
    def compute_summary(
        cls,
        routes: list[Route],
        unassigned: list[UnassignedOrder],
        pgp_groups: list[PgpGroup],
        cancelled: list[CancelledOrder],
        staff_by_id: dict[str, Staff],
        day_date: date_type,
        day_tz: tzinfo,
    ) -> PlanSummary:
        visits_planned = 0
        travel_sec_total = 0

        for route in routes:
            st = staff_by_id[route.staff_id]
            route.totals = cls.compute_route_totals(route, st, day_date, day_tz)
            visits_planned += route.totals.visits
            travel_sec_total += route.totals.travel_sec

        pgp_orders = sum(len(g.order_ids) for g in pgp_groups)
        orders_total = visits_planned + len(unassigned) + pgp_orders + len(cancelled)
        utilization_cv = cls.compute_utilization_cv(routes)

        return PlanSummary(
            orders_total=orders_total,
            visits_planned=visits_planned,
            unassigned=len(unassigned),
            pgp_orders=pgp_orders,
            cancelled=len(cancelled),
            travel_sec_total=travel_sec_total,
            utilization_cv=utilization_cv,
        )
