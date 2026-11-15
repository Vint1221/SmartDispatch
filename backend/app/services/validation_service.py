from __future__ import annotations

from datetime import datetime, tzinfo

from app.routing.matrix import TravelMatrixIndex
from app.schemas.common import Equipment
from app.schemas.day import Order
from app.schemas.plan import Plan, RouteStatus, StopType
from app.schemas.reference import ServiceCenter, Staff, WorkType
from app.services.time_utils import local_hhmm_to_dt, norm_dt


class PlanValidator:
    """Exact validator for hard constraints H1–H10 from api_spec.yaml."""

    TOLERANCE_SEC = 1

    @classmethod
    def validate(
        cls,
        plan: Plan,
        staff_by_id: dict[str, Staff],
        absent_staff_ids: set[str],
        service_centers_by_id: dict[str, ServiceCenter],
        work_types_by_code: dict[str, WorkType],
        orders_by_id: dict[str, Order],
        matrix: TravelMatrixIndex,
        day_tz: tzinfo,
        prev_plan: Plan | None = None,
        model_time: datetime | None = None,
        new_order_min_start: dict[str, datetime] | None = None,
        override_visit_end: dict[str, datetime] | None = None,
        force_started_order_ids: set[str] | None = None,
        cancelled_order_ids: set[str] | None = None,
    ) -> list[str]:
        violations: list[str] = []
        new_order_min_start = new_order_min_start or {}
        override_visit_end = override_visit_end or {}
        force_started_order_ids = force_started_order_ids or set()
        cancelled_order_ids = cancelled_order_ids or set()

        expected_staff = set(staff_by_id.keys()) - absent_staff_ids
        plan_staff = {r.staff_id for r in plan.routes}
        if plan_staff != expected_staff:
            missing = sorted(expected_staff - plan_staff)
            extra = sorted(plan_staff - expected_staff)
            if missing:
                violations.append(f"H2: missing routes for active staff: {missing}")
            if extra:
                violations.append(f"H2: unexpected routes for absent/unknown staff: {extra}")

        visited_orders: list[str] = []

        for route in plan.routes:
            staff = staff_by_id.get(route.staff_id)
            if staff is None:
                violations.append(f"H1: unknown staff {route.staff_id}")
                continue
            if route.service_center_id != staff.service_center_id:
                violations.append(f"H8: route.service_center_id mismatch for {staff.staff_id}")

            stops = route.stops
            if not stops:
                continue

            # Seq must be 1, 2, 3...
            for idx, s in enumerate(stops, start=1):
                if s.seq != idx:
                    violations.append(f"Route {staff.staff_id}: stop seq {s.seq} != {idx}")

            # H8 / Stop type structure
            if stops[0].type != StopType.DEPOT_START:
                violations.append(f"H8: {staff.staff_id} first stop must be DEPOT_START")
            elif stops[0].location_id != staff.service_center_id:
                violations.append(f"H8: {staff.staff_id} DEPOT_START must be at {staff.service_center_id}")

            if route.status == RouteStatus.ACTIVE and stops[-1].type != StopType.DEPOT_END:
                violations.append(f"H8: {staff.staff_id} last stop must be DEPOT_END")
            if stops[-1].type == StopType.DEPOT_END and stops[-1].location_id != staff.service_center_id:
                violations.append(f"H8: {staff.staff_id} DEPOT_END must be at {staff.service_center_id}")

            shift_start = local_hhmm_to_dt(plan.date, staff.shift.start, day_tz)
            shift_end = local_hhmm_to_dt(plan.date, staff.shift.end, day_tz)
            break_from = local_hhmm_to_dt(plan.date, staff.shift.break_window.from_, day_tz)
            break_to = local_hhmm_to_dt(plan.date, staff.shift.break_window.to, day_tz)

            visit_count = sum(1 for s in stops if s.type == StopType.VISIT)
            break_stops = [s for s in stops if s.type == StopType.BREAK]

            # H3: Break check (skip if permanently unavailable before break_window ends)
            perm_unavail_before_break = (
                route.status == RouteStatus.UNAVAILABLE
                and route.unavailable_from is not None
                and route.unavailable_until is None
                and norm_dt(route.unavailable_from, day_tz) <= break_to
            )
            if visit_count > 0 and not perm_unavail_before_break:
                if len(break_stops) != 1:
                    violations.append(f"H3: {staff.staff_id} has {visit_count} visits and {len(break_stops)} BREAK stops")
                else:
                    brk = break_stops[0]
                    brk_dur = (brk.end - brk.start).total_seconds()
                    if brk_dur + cls.TOLERANCE_SEC < staff.shift.break_duration_min * 60:
                        violations.append(f"H3: {staff.staff_id} BREAK shorter than {staff.shift.break_duration_min} min")
                    if brk.start < break_from - cls._td(cls.TOLERANCE_SEC) or brk.start > break_to + cls._td(cls.TOLERANCE_SEC):
                        violations.append(f"H3: {staff.staff_id} BREAK start {brk.start} outside [{break_from}, {break_to}]")

            eq = Equipment(
                ONT=staff.equipment_start.ONT,
                ROUTER=staff.equipment_start.ROUTER,
                STB=staff.equipment_start.STB,
            )

            for idx, stop in enumerate(stops):
                # H2: inside shift
                if (
                    stop.arrival < shift_start - cls._td(cls.TOLERANCE_SEC)
                    or stop.end > shift_end + cls._td(cls.TOLERANCE_SEC)
                ):
                    violations.append(f"H2: {staff.staff_id} stop {stop.seq} outside shift [{shift_start}, {shift_end}]")

                if stop.start < stop.arrival - cls._td(cls.TOLERANCE_SEC):
                    violations.append(f"H6: {staff.staff_id} stop {stop.seq} start < arrival")
                if stop.end < stop.start - cls._td(cls.TOLERANCE_SEC):
                    violations.append(f"H6: {staff.staff_id} stop {stop.seq} end < start")

                # H6: travel from previous stop
                if idx > 0:
                    prev = stops[idx - 1]
                    if stop.type == StopType.BREAK:
                        if stop.location_id != prev.location_id:
                            violations.append(f"H3/H6: {staff.staff_id} BREAK location {stop.location_id} != prev {prev.location_id}")
                        if stop.arrival < prev.end - cls._td(cls.TOLERANCE_SEC):
                            violations.append(f"H3/H6: {staff.staff_id} BREAK arrival < prev.end")
                    else:
                        t_sec = matrix.duration_sec(prev.location_id, stop.location_id)
                        min_arr = prev.end + cls._td(t_sec - cls.TOLERANCE_SEC)
                        if stop.arrival < min_arr:
                            violations.append(
                                f"H6: {staff.staff_id} stop {stop.seq} arrival {stop.arrival} < prev.end + {t_sec}s"
                            )

                # Staff unavailability check
                if route.status == RouteStatus.UNAVAILABLE and route.unavailable_from is not None:
                    u_from = norm_dt(route.unavailable_from, day_tz)
                    u_until = norm_dt(route.unavailable_until, day_tz) if route.unavailable_until else None
                    if u_until is None:
                        if stop.start >= u_from:
                            violations.append(f"H10: unavailable {staff.staff_id} starts stop {stop.seq} at {stop.start} >= {u_from}")
                    else:
                        if u_from <= stop.start < u_until:
                            violations.append(f"H10: unavailable {staff.staff_id} starts stop {stop.seq} during [{u_from}, {u_until})")

                if stop.type == StopType.VISIT:
                    if not stop.order_id or stop.order_id not in orders_by_id:
                        violations.append(f"H9: unknown order_id {stop.order_id} on {staff.staff_id}")
                        continue
                    order = orders_by_id[stop.order_id]
                    visited_orders.append(order.order_id)

                    if stop.location_id != order.building_id:
                        violations.append(f"H6: stop location {stop.location_id} != building {order.building_id}")

                    wt = work_types_by_code[order.work_type_code.value]
                    # H1
                    if not (set(staff.profiles) & set(wt.profiles)):
                        violations.append(f"H1: {staff.staff_id} lacks profile for {order.order_id}")
                    if order.technology not in staff.technologies:
                        violations.append(f"H1: {staff.staff_id} lacks technology {order.technology} for {order.order_id}")
                    if order.requires_height and not staff.height_permit:
                        violations.append(f"H1: {staff.staff_id} lacks height_permit for {order.order_id}")

                    # H4
                    s_start = norm_dt(order.slot.start, day_tz)
                    s_latest = norm_dt(order.latest_start, day_tz)
                    if stop.start < s_start - cls._td(cls.TOLERANCE_SEC) or stop.start > s_latest + cls._td(cls.TOLERANCE_SEC):
                        violations.append(f"H4: {order.order_id} start {stop.start} outside [{s_start}, {s_latest}]")

                    # NEW_ORDER min start
                    if order.order_id in new_order_min_start:
                        min_s = norm_dt(new_order_min_start[order.order_id], day_tz)
                        if stop.start < min_s - cls._td(cls.TOLERANCE_SEC):
                            violations.append(f"H10: NEW_ORDER {order.order_id} start {stop.start} < event timestamp {min_s}")

                    # H5
                    if order.order_id in override_visit_end:
                        exp_end = norm_dt(override_visit_end[order.order_id], day_tz)
                        if abs((stop.end - exp_end).total_seconds()) > cls.TOLERANCE_SEC:
                            violations.append(f"H5: {order.order_id} end {stop.end} != override {exp_end}")
                    else:
                        dur_sec = int((stop.end - stop.start).total_seconds())
                        if abs(dur_sec - wt.duration_min * 60) > cls.TOLERANCE_SEC:
                            violations.append(f"H5: {order.order_id} duration {dur_sec}s != {wt.duration_min * 60}s")

                    # H7
                    eq = eq.subtract(order.required_equipment)
                    if eq.ONT < 0 or eq.ROUTER < 0 or eq.STB < 0:
                        violations.append(f"H7: {staff.staff_id} negative equipment at {order.order_id}: {eq}")

                elif stop.type == StopType.RESTOCK:
                    sc = service_centers_by_id.get(stop.location_id)
                    if sc is None:
                        violations.append(f"H8: unknown SC {stop.location_id} for RESTOCK")
                    else:
                        sc_open = local_hhmm_to_dt(plan.date, sc.opening_hours.open, day_tz)
                        sc_close = local_hhmm_to_dt(plan.date, sc.opening_hours.close, day_tz)
                        if stop.start < sc_open - cls._td(cls.TOLERANCE_SEC) or stop.end > sc_close + cls._td(cls.TOLERANCE_SEC):
                            violations.append(f"H8: RESTOCK at {sc.service_center_id} outside opening hours")
                        dur = (stop.end - stop.start).total_seconds()
                        if dur + cls.TOLERANCE_SEC < sc.restock_duration_min * 60:
                            violations.append(f"H8: RESTOCK duration {dur}s < {sc.restock_duration_min * 60}s")
                        eq = Equipment(
                            ONT=staff.equipment_capacity.ONT,
                            ROUTER=staff.equipment_capacity.ROUTER,
                            STB=staff.equipment_capacity.STB,
                        )

        # H9: Partition check
        unassigned_ids = [u.order_id for u in plan.unassigned]
        pgp_ids = [oid for g in plan.pgp_groups for oid in g.order_ids]
        cancelled_ids = [c.order_id for c in plan.cancelled]

        all_listed = visited_orders + unassigned_ids + pgp_ids + cancelled_ids
        expected_orders = set(orders_by_id.keys())
        if len(all_listed) != len(set(all_listed)):
            violations.append("H9: duplicate order assignment across plan sections")
        if set(all_listed) != expected_orders:
            missing_o = sorted(expected_orders - set(all_listed))
            extra_o = sorted(set(all_listed) - expected_orders)
            violations.append(f"H9: partition mismatch missing={missing_o} extra={extra_o}")

        # Cancelled order check (must not be visited unless already started)
        for oid in cancelled_order_ids:
            if oid in visited_orders and oid not in force_started_order_ids:
                # Check if it was started before model_time in prev_plan
                was_started = False
                if prev_plan and model_time:
                    t = norm_dt(model_time, day_tz)
                    for pr in prev_plan.routes:
                        for ps in pr.stops:
                            if ps.order_id == oid and norm_dt(ps.start, day_tz) < t:
                                was_started = True
                if not was_started:
                    violations.append(f"H10: cancelled order {oid} is visited in new plan")

        # H10: Freeze check against prev_plan
        if prev_plan is not None and model_time is not None:
            t = norm_dt(model_time, day_tz)
            prev_routes = {r.staff_id: r for r in prev_plan.routes}
            new_routes = {r.staff_id: r for r in plan.routes}

            for sid, pr in prev_routes.items():
                nr = new_routes.get(sid)
                if nr is None:
                    continue
                frozen_prev = [
                    s
                    for s in pr.stops
                    if norm_dt(s.start, day_tz) < t or (s.order_id is not None and s.order_id in force_started_order_ids)
                ]
                if len(nr.stops) < len(frozen_prev):
                    violations.append(f"H10: {sid} lost frozen stops ({len(nr.stops)} < {len(frozen_prev)})")
                    continue
                for idx, ps in enumerate(frozen_prev):
                    ns = nr.stops[idx]
                    if (
                        ns.type != ps.type
                        or ns.location_id != ps.location_id
                        or ns.order_id != ps.order_id
                        or abs((norm_dt(ns.arrival, day_tz) - norm_dt(ps.arrival, day_tz)).total_seconds()) > cls.TOLERANCE_SEC
                        or abs((norm_dt(ns.start, day_tz) - norm_dt(ps.start, day_tz)).total_seconds()) > cls.TOLERANCE_SEC
                    ):
                        violations.append(f"H10: {sid} mutated frozen stop {idx + 1} ({ps.type}/{ps.order_id})")
                    if ps.order_id not in override_visit_end:
                        if abs((norm_dt(ns.end, day_tz) - norm_dt(ps.end, day_tz)).total_seconds()) > cls.TOLERANCE_SEC:
                            violations.append(f"H10: {sid} mutated frozen stop end {idx + 1}")

                # Predecessor change or new stop arrival >= max(prev.end, t) + travel
                prev_stop_preds: dict[tuple[str, str | None], tuple[str, str | None, str] | None] = {}
                for k, ps in enumerate(pr.stops):
                    key = (ps.type.value, ps.order_id)
                    pred_key = (
                        (pr.stops[k - 1].type.value, pr.stops[k - 1].order_id, pr.stops[k - 1].location_id)
                        if k > 0
                        else None
                    )
                    prev_stop_preds[key] = pred_key

                for k, ns in enumerate(nr.stops):
                    if k < len(frozen_prev):
                        continue
                    if ns.type == StopType.BREAK:
                        continue
                    key = (ns.type.value, ns.order_id)
                    curr_pred = (
                        (nr.stops[k - 1].type.value, nr.stops[k - 1].order_id, nr.stops[k - 1].location_id)
                        if k > 0
                        else None
                    )
                    was_known_same_pred = (
                        key in prev_stop_preds
                        and prev_stop_preds[key] == curr_pred
                    )
                    if not was_known_same_pred:
                        if k == 0:
                            if norm_dt(ns.arrival, day_tz) < t - cls._td(cls.TOLERANCE_SEC):
                                violations.append(f"H10: {sid} new DEPOT_START arrival {ns.arrival} < t={t}")
                        else:
                            p_end = norm_dt(nr.stops[k - 1].end, day_tz)
                            base_t = max(p_end, t)
                            tr = matrix.duration_sec(nr.stops[k - 1].location_id, ns.location_id)
                            if norm_dt(ns.arrival, day_tz) < base_t + cls._td(tr - cls.TOLERANCE_SEC):
                                violations.append(
                                    f"H10: {sid} stop {ns.seq} ({ns.type}/{ns.order_id}) arrival {ns.arrival} < max(prev.end, t)+{tr}s"
                                )

        return violations

    @staticmethod
    def _td(sec: int):
        from datetime import timedelta

        return timedelta(seconds=sec)
