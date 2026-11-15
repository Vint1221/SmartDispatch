from __future__ import annotations

from datetime import date as date_type
from datetime import datetime, timedelta, tzinfo
from typing import Optional

from app.routing.matrix import TravelMatrixIndex
from app.schemas.common import Equipment
from app.schemas.day import Order
from app.schemas.plan import Route, RouteStatus, Stop, StopStatus, StopType
from app.schemas.reference import ServiceCenter, Staff, WorkType
from app.services.time_utils import local_hhmm_to_dt, norm_dt


def is_staff_qualified(staff: Staff, order: Order, work_type: WorkType) -> bool:
    if not (set(staff.profiles) & set(work_type.profiles)):
        return False
    if order.technology not in staff.technologies:
        return False
    if order.requires_height and not staff.height_permit:
        return False
    # Equipment is H7, not a qualification (H1) check. A worker may still be
    # eligible when the route can insert a RESTOCK stop; route simulation decides this.
    return True


def compute_frozen_prefix(
    prev_route: Optional[Route],
    model_time: datetime,
    day_tz: tzinfo,
    override_visit_end: dict[str, datetime],
    force_started_order_ids: set[str],
) -> tuple[list[Stop], set[str]]:
    """
    Returns (frozen_stops, frozen_order_ids) where every stop with start < model_time
    (or in force_started_order_ids) is frozen per H10.
    """
    if prev_route is None or not prev_route.stops:
        return [], set()

    t = norm_dt(model_time, day_tz)
    frozen: list[Stop] = []
    frozen_orders: set[str] = set()

    for stop in prev_route.stops:
        s_start = norm_dt(stop.start, day_tz)
        is_forced = stop.order_id is not None and stop.order_id in force_started_order_ids
        if s_start < t or is_forced:
            new_end = norm_dt(stop.end, day_tz)
            if stop.order_id and stop.order_id in override_visit_end:
                new_end = norm_dt(override_visit_end[stop.order_id], day_tz)
            status = StopStatus.DONE if new_end <= t else StopStatus.IN_PROGRESS
            cloned = stop.model_copy(
                update={
                    "arrival": norm_dt(stop.arrival, day_tz),
                    "start": s_start,
                    "end": new_end,
                    "status": status,
                }
            )
            frozen.append(cloned)
            if stop.order_id:
                frozen_orders.add(stop.order_id)
        else:
            break

    return frozen, frozen_orders


def _find_best_restock_sc(
    prev_loc: str,
    prev_end: datetime,
    next_loc: str,
    model_time: datetime,
    day_date: date_type,
    day_tz: tzinfo,
    shift_end: datetime,
    service_centers: list[ServiceCenter],
    matrix: TravelMatrixIndex,
    unavail: tuple[datetime, Optional[datetime]] | None,
    staff_sc_id: str,
) -> Optional[tuple[ServiceCenter, datetime, datetime, datetime, int, int]]:
    best: Optional[tuple[int, ServiceCenter, datetime, datetime, datetime, int, int]] = None

    for sc in service_centers:
        sc_open = local_hhmm_to_dt(day_date, sc.opening_hours.open, day_tz)
        sc_close = local_hhmm_to_dt(day_date, sc.opening_hours.close, day_tz)
        tr_to = matrix.duration_sec(prev_loc, sc.service_center_id)
        dist_to = matrix.distance_m(prev_loc, sc.service_center_id)
        arr = max(prev_end, model_time) + timedelta(seconds=tr_to)

        if unavail is not None:
            u_from, u_until = unavail
            if u_until is None:
                if arr >= u_from:
                    continue
            elif u_from <= arr < u_until or (prev_end < u_until and arr >= u_from):
                tr_home = matrix.duration_sec(prev_loc, staff_sc_id)
                tr_sc = matrix.duration_sec(staff_sc_id, sc.service_center_id)
                arr = max(arr, max(u_until, prev_end + timedelta(seconds=tr_home)) + timedelta(seconds=tr_sc))

        start = max(arr, sc_open)
        if unavail is not None:
            u_from, u_until = unavail
            if u_until is not None and u_from <= start < u_until:
                start = max(start, u_until)

        end = start + timedelta(minutes=sc.restock_duration_min)
        if end > sc_close or end > shift_end:
            continue

        tr_after = matrix.duration_sec(sc.service_center_id, next_loc)
        score = int((end - prev_end).total_seconds()) + tr_after
        if best is None or score < best[0]:
            best = (score, sc, arr, start, end, tr_to, dist_to)

    if best is None:
        return None
    return best[1:]


def simulate_route(
    staff: Staff,
    frozen_stops: list[Stop],
    future_orders: list[Order],
    day_date: date_type,
    day_tz: tzinfo,
    model_time: datetime,
    service_centers: list[ServiceCenter],
    work_types: dict[str, WorkType],
    matrix: TravelMatrixIndex,
    unavail: tuple[datetime, Optional[datetime]] | None = None,
    prev_route_stops: Optional[list[Stop]] = None,
    new_order_min_start: Optional[dict[str, datetime]] = None,
    override_visit_end: Optional[dict[str, datetime]] = None,
) -> Optional[Route]:
    """
    Simulates a complete H1-H10 valid route for `staff` keeping `frozen_stops` intact
    and scheduling `future_orders`, inserting BREAK (H3) and RESTOCK (H7/H8) as required.
    Returns None if any constraint cannot be satisfied.
    """
    new_order_min_start = new_order_min_start or {}
    override_visit_end = override_visit_end or {}
    t = norm_dt(model_time, day_tz)

    shift_start = local_hhmm_to_dt(day_date, staff.shift.start, day_tz)
    shift_end = local_hhmm_to_dt(day_date, staff.shift.end, day_tz)
    break_from = local_hhmm_to_dt(day_date, staff.shift.break_window.from_, day_tz)
    break_to = local_hhmm_to_dt(day_date, staff.shift.break_window.to, day_tz)
    break_dur = timedelta(minutes=staff.shift.break_duration_min)

    route_status = RouteStatus.UNAVAILABLE if unavail is not None else RouteStatus.ACTIVE
    u_from = norm_dt(unavail[0], day_tz) if unavail is not None else None
    u_until = norm_dt(unavail[1], day_tz) if (unavail is not None and unavail[1] is not None) else None

    if unavail is not None and u_until is None:
        if future_orders:
            return None
        reseq = [s.model_copy(update={"seq": i}) for i, s in enumerate(frozen_stops, start=1)]
        return Route(
            staff_id=staff.staff_id,
            service_center_id=staff.service_center_id,
            status=RouteStatus.UNAVAILABLE,
            unavailable_from=u_from,
            unavailable_until=None,
            stops=reseq,
        )

    if not frozen_stops and not future_orders:
        return Route(
            staff_id=staff.staff_id,
            service_center_id=staff.service_center_id,
            status=route_status,
            unavailable_from=u_from,
            unavailable_until=u_until,
            stops=[],
        )

    if frozen_stops and frozen_stops[-1].type == StopType.DEPOT_END:
        if future_orders:
            return None
        reseq = [s.model_copy(update={"seq": i}) for i, s in enumerate(frozen_stops, start=1)]
        return Route(
            staff_id=staff.staff_id,
            service_center_id=staff.service_center_id,
            status=route_status,
            unavailable_from=u_from,
            unavailable_until=u_until,
            stops=reseq,
        )

    # Check equipment state after frozen_stops
    base_eq = Equipment(
        ONT=staff.equipment_start.ONT,
        ROUTER=staff.equipment_start.ROUTER,
        STB=staff.equipment_start.STB,
    )
    frozen_visits = 0
    has_frozen_break = False
    for s in frozen_stops:
        if s.type == StopType.BREAK:
            has_frozen_break = True
        elif s.type == StopType.RESTOCK:
            base_eq = Equipment(
                ONT=staff.equipment_capacity.ONT,
                ROUTER=staff.equipment_capacity.ROUTER,
                STB=staff.equipment_capacity.STB,
            )
        elif s.type == StopType.VISIT:
            frozen_visits += 1
            # Best-effort: equipment_after stored on frozen stop if available
            if s.equipment_after is not None:
                base_eq = Equipment(
                    ONT=s.equipment_after.ONT,
                    ROUTER=s.equipment_after.ROUTER,
                    STB=s.equipment_after.STB,
                )

    total_visits = frozen_visits + len(future_orders)
    need_break = total_visits > 0 and not has_frozen_break

    # Map previous stops by (type, order_id) -> prev_identity for H10 unchanged-predecessor optimization
    prev_preds: dict[tuple[str, Optional[str]], tuple[str, Optional[str], str] | None] = {}
    if prev_route_stops:
        for idx_p, ps in enumerate(prev_route_stops):
            pk = (ps.type.value, ps.order_id)
            p_prev = (
                (prev_route_stops[idx_p - 1].type.value, prev_route_stops[idx_p - 1].order_id, prev_route_stops[idx_p - 1].location_id)
                if idx_p > 0
                else None
            )
            prev_preds[pk] = p_prev

    candidate_break_positions: list[Optional[int]] = (
        list(range(len(future_orders) + 1)) if need_break else [None]
    )

    best_stops: Optional[list[Stop]] = None
    best_cost: Optional[tuple[int, int]] = None

    for b_pos in candidate_break_positions:
        stops: list[Stop] = [s.model_copy() for s in frozen_stops]
        eq = Equipment(ONT=base_eq.ONT, ROUTER=base_eq.ROUTER, STB=base_eq.STB)

        if not stops:
            depart = max(shift_start, t)
            if u_from is not None and u_until is not None and u_from <= depart < u_until:
                depart = max(depart, u_until)
            if depart > shift_end:
                continue
            stops.append(
                Stop(
                    seq=1,
                    type=StopType.DEPOT_START,
                    location_id=staff.service_center_id,
                    order_id=None,
                    arrival=depart,
                    start=depart,
                    end=depart,
                    travel_sec=0,
                    distance_m=0,
                    status=StopStatus.PLANNED,
                    equipment_after=Equipment(ONT=eq.ONT, ROUTER=eq.ROUTER, STB=eq.STB),
                )
            )

        prev_stop = stops[-1]
        total_travel_sec = sum(s.travel_sec or 0 for s in stops)
        feasible = True

        def try_insert_break() -> bool:
            nonlocal prev_stop
            brk_arr = prev_stop.end
            brk_start = max(brk_arr, break_from, t)
            if u_from is not None and u_until is not None and u_from <= brk_start < u_until:
                brk_start = max(brk_start, u_until)
            if brk_start > break_to:
                return False
            brk_end = brk_start + break_dur
            if brk_end > shift_end:
                return False
            if u_from is not None and u_until is not None and (u_from <= brk_start < u_until):
                return False
            brk = Stop(
                seq=len(stops) + 1,
                type=StopType.BREAK,
                location_id=prev_stop.location_id,
                order_id=None,
                arrival=brk_arr,
                start=brk_start,
                end=brk_end,
                travel_sec=0,
                distance_m=0,
                status=StopStatus.PLANNED,
                equipment_after=Equipment(ONT=eq.ONT, ROUTER=eq.ROUTER, STB=eq.STB),
            )
            stops.append(brk)
            prev_stop = brk
            return True

        for idx, order in enumerate(future_orders):
            if b_pos is not None and idx == b_pos:
                if not try_insert_break():
                    feasible = False
                    break

            wt = work_types[order.work_type_code.value]
            if not is_staff_qualified(staff, order, wt):
                feasible = False
                break

            if not eq.can_supply(order.required_equipment):
                rs = _find_best_restock_sc(
                    prev_loc=prev_stop.location_id,
                    prev_end=prev_stop.end,
                    next_loc=order.building_id,
                    model_time=t,
                    day_date=day_date,
                    day_tz=day_tz,
                    shift_end=shift_end,
                    service_centers=service_centers,
                    matrix=matrix,
                    unavail=(u_from, u_until) if u_from is not None else None,
                    staff_sc_id=staff.service_center_id,
                )
                if rs is None:
                    feasible = False
                    break
                sc, rs_arr, rs_start, rs_end, rs_tr, rs_dist = rs
                eq = Equipment(
                    ONT=staff.equipment_capacity.ONT,
                    ROUTER=staff.equipment_capacity.ROUTER,
                    STB=staff.equipment_capacity.STB,
                )
                rs_stop = Stop(
                    seq=len(stops) + 1,
                    type=StopType.RESTOCK,
                    location_id=sc.service_center_id,
                    order_id=None,
                    arrival=rs_arr,
                    start=rs_start,
                    end=rs_end,
                    travel_sec=rs_tr,
                    distance_m=rs_dist,
                    status=StopStatus.PLANNED,
                    equipment_after=Equipment(ONT=eq.ONT, ROUTER=eq.ROUTER, STB=eq.STB),
                )
                stops.append(rs_stop)
                prev_stop = rs_stop
                total_travel_sec += rs_tr
                if not eq.can_supply(order.required_equipment):
                    feasible = False
                    break

            tr_sec = matrix.duration_sec(prev_stop.location_id, order.building_id)
            dist_m = matrix.distance_m(prev_stop.location_id, order.building_id)

            curr_pred = (prev_stop.type.value, prev_stop.order_id, prev_stop.location_id)
            same_pred = (
                prev_route_stops is not None
                and (StopType.VISIT.value, order.order_id) in prev_preds
                and prev_preds[(StopType.VISIT.value, order.order_id)] == curr_pred
            )
            base_depart = prev_stop.end if same_pred else max(prev_stop.end, t)
            arr = base_depart + timedelta(seconds=tr_sec)

            if u_from is not None and u_until is not None:
                if (u_from <= arr < u_until) or (prev_stop.end < u_until and arr >= u_from):
                    tr_home = matrix.duration_sec(prev_stop.location_id, staff.service_center_id)
                    tr_from_sc = matrix.duration_sec(staff.service_center_id, order.building_id)
                    arr = max(
                        arr,
                        max(u_until, prev_stop.end + timedelta(seconds=tr_home)) + timedelta(seconds=tr_from_sc),
                    )

            slot_s = norm_dt(order.slot.start, day_tz)
            latest_s = norm_dt(order.latest_start, day_tz)
            min_new_s = norm_dt(new_order_min_start[order.order_id], day_tz) if order.order_id in new_order_min_start else arr
            start = max(arr, slot_s, min_new_s)

            if u_from is not None and u_until is not None and u_from <= start < u_until:
                tr_home = matrix.duration_sec(prev_stop.location_id, staff.service_center_id)
                tr_from_sc = matrix.duration_sec(staff.service_center_id, order.building_id)
                start = max(
                    start,
                    max(u_until, prev_stop.end + timedelta(seconds=tr_home)) + timedelta(seconds=tr_from_sc),
                )
                arr = max(arr, start)

            if start > latest_s:
                feasible = False
                break

            if order.order_id in override_visit_end:
                end = norm_dt(override_visit_end[order.order_id], day_tz)
                if end < start:
                    end = start
            else:
                end = start + timedelta(minutes=wt.duration_min)

            if end > shift_end:
                feasible = False
                break

            eq = eq.subtract(order.required_equipment)
            slack_min = max(0, int((latest_s - start).total_seconds() // 60))
            tech_str = order.technology.value
            explanation = (
                f"Назначен {staff.staff_id} ({'/'.join(p.value for p in staff.profiles)}, {tech_str}); "
                f"путь {round(tr_sec / 60)} мин, запас до крайнего старта {slack_min} мин"
            )
            v_stop = Stop(
                seq=len(stops) + 1,
                type=StopType.VISIT,
                location_id=order.building_id,
                order_id=order.order_id,
                arrival=arr,
                start=start,
                end=end,
                travel_sec=tr_sec,
                distance_m=dist_m,
                status=StopStatus.PLANNED,
                equipment_after=Equipment(ONT=eq.ONT, ROUTER=eq.ROUTER, STB=eq.STB),
                explanation=explanation,
            )
            stops.append(v_stop)
            prev_stop = v_stop
            total_travel_sec += tr_sec

        if not feasible:
            continue

        if b_pos is not None and b_pos == len(future_orders):
            if not try_insert_break():
                continue

        # Append DEPOT_END
        tr_dep = matrix.duration_sec(prev_stop.location_id, staff.service_center_id)
        dist_dep = matrix.distance_m(prev_stop.location_id, staff.service_center_id)
        dep_same_pred = (
            prev_route_stops is not None
            and (StopType.DEPOT_END.value, None) in prev_preds
            and prev_preds[(StopType.DEPOT_END.value, None)]
            == (prev_stop.type.value, prev_stop.order_id, prev_stop.location_id)
        )
        base_dep = prev_stop.end if dep_same_pred else max(prev_stop.end, t)
        dep_arr = base_dep + timedelta(seconds=tr_dep)
        if u_from is not None and u_until is not None and u_from <= dep_arr < u_until:
            dep_arr = max(dep_arr, u_until)
        if dep_arr > shift_end:
            continue

        stops.append(
            Stop(
                seq=len(stops) + 1,
                type=StopType.DEPOT_END,
                location_id=staff.service_center_id,
                order_id=None,
                arrival=dep_arr,
                start=dep_arr,
                end=dep_arr,
                travel_sec=tr_dep,
                distance_m=dist_dep,
                status=StopStatus.PLANNED,
                equipment_after=Equipment(ONT=eq.ONT, ROUTER=eq.ROUTER, STB=eq.STB),
            )
        )
        total_travel_sec += tr_dep
        cost = (total_travel_sec, int((dep_arr - shift_start).total_seconds()))
        if best_cost is None or cost < best_cost:
            best_cost = cost
            best_stops = stops

    if best_stops is None:
        return None

    reseq = [s.model_copy(update={"seq": i}) for i, s in enumerate(best_stops, start=1)]
    return Route(
        staff_id=staff.staff_id,
        service_center_id=staff.service_center_id,
        status=route_status,
        unavailable_from=u_from,
        unavailable_until=u_until,
        stops=reseq,
    )
