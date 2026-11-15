from __future__ import annotations

import math
import time
from datetime import date as date_type
from datetime import datetime, tzinfo
from typing import Optional

from ortools.constraint_solver import pywrapcp, routing_enums_pb2

from app.optimizer.route_simulator import compute_frozen_prefix, is_staff_qualified, simulate_route
from app.routing.matrix import TravelMatrixIndex
from app.schemas.common import TimeWindow
from app.schemas.day import Order
from app.schemas.plan import (
    Route,
    RouteStatus,
    StopType,
    UnassignedOrder,
    UnassignedReasonCode,
    UnassignedSuggestedAction,
)
from app.schemas.reference import ServiceCenter, Staff, WorkType
from app.services.time_utils import dt_to_sec, local_hhmm_to_dt, norm_dt


class VrptwSolver:
    """
    Google OR-Tools VRPTW solver + Exact Route Simulator + Best-Insertion Rescue
    + Utilization-CV Workload Rebalancer.
    """

    @classmethod
    def solve(
        cls,
        staff_list: list[Staff],
        absent_staff_ids: set[str],
        service_centers: list[ServiceCenter],
        work_types: dict[str, WorkType],
        orders_to_schedule: list[Order],
        matrix: TravelMatrixIndex,
        day_date: date_type,
        day_tz: tzinfo,
        model_time: datetime,
        time_limit_sec: float = 15.0,
        prev_routes_by_staff: Optional[dict[str, Route]] = None,
        staff_unavailability: Optional[dict[str, tuple[datetime, Optional[datetime]]]] = None,
        new_order_min_start: Optional[dict[str, datetime]] = None,
        override_visit_end: Optional[dict[str, datetime]] = None,
        force_started_order_ids: Optional[set[str]] = None,
    ) -> tuple[list[Route], list[UnassignedOrder]]:
        t0 = time.monotonic()
        deadline_monotonic = t0 + max(0.5, time_limit_sec)
        prev_routes_by_staff = prev_routes_by_staff or {}
        staff_unavailability = staff_unavailability or {}
        new_order_min_start = new_order_min_start or {}
        override_visit_end = override_visit_end or {}
        force_started_order_ids = force_started_order_ids or set()

        t = norm_dt(model_time, day_tz)
        origin = local_hhmm_to_dt(day_date, "00:00", day_tz)

        active_staff = [s for s in staff_list if s.staff_id not in absent_staff_ids]
        frozen_by_staff: dict[str, list] = {}
        frozen_order_ids: set[str] = set()

        for st in active_staff:
            fr_stops, fr_orders = compute_frozen_prefix(
                prev_routes_by_staff.get(st.staff_id),
                model_time=t,
                day_tz=day_tz,
                override_visit_end=override_visit_end,
                force_started_order_ids=force_started_order_ids,
            )
            frozen_by_staff[st.staff_id] = fr_stops
            frozen_order_ids.update(fr_orders)

        # Exclude orders already frozen (DONE or IN_PROGRESS) from future scheduling
        future_pool = [o for o in orders_to_schedule if o.order_id not in frozen_order_ids]

        # Pre-filter qualified staff and time feasibility for each order
        schedulable_orders: list[Order] = []
        pre_unassigned: list[UnassignedOrder] = []
        eligible_staff_indices: list[list[int]] = []

        # Vehicles eligible for future orders (exclude permanently unavailable or already DEPOT_END-frozen)
        sched_staff: list[Staff] = []
        fixed_routes: dict[str, Route] = {}

        for st in active_staff:
            fr = frozen_by_staff[st.staff_id]
            unavail = staff_unavailability.get(st.staff_id)
            if (unavail is not None and unavail[1] is None) or (fr and fr[-1].type == StopType.DEPOT_END):
                fixed_route = simulate_route(
                    staff=st,
                    frozen_stops=fr,
                    future_orders=[],
                    day_date=day_date,
                    day_tz=day_tz,
                    model_time=t,
                    service_centers=service_centers,
                    work_types=work_types,
                    matrix=matrix,
                    unavail=unavail,
                    prev_route_stops=prev_routes_by_staff[st.staff_id].stops if st.staff_id in prev_routes_by_staff else None,
                    new_order_min_start=new_order_min_start,
                    override_visit_end=override_visit_end,
                )
                assert fixed_route is not None
                fixed_routes[st.staff_id] = fixed_route
            else:
                sched_staff.append(st)

        for order in future_pool:
            wt = work_types[order.work_type_code.value]
            slot_s = norm_dt(order.slot.start, day_tz)
            latest_s = norm_dt(order.latest_start, day_tz)
            min_new = norm_dt(new_order_min_start[order.order_id], day_tz) if order.order_id in new_order_min_start else slot_s
            eff_start = max(slot_s, min_new)

            if eff_start > latest_s:
                pre_unassigned.append(
                    cls._make_unassigned(
                        order,
                        UnassignedReasonCode.SLOT_UNREACHABLE,
                        f"Слот {order.order_id} уже невыполним на момент {t.isoformat()}",
                        t,
                        day_tz,
                    )
                )
                continue

            qual_all = [st for st in active_staff if is_staff_qualified(st, order, wt)]
            if not qual_all:
                pre_unassigned.append(
                    cls._make_unassigned(
                        order,
                        UnassignedReasonCode.NO_QUALIFIED_STAFF,
                        f"На смене нет сотрудника с профилем {'/'.join(p.value for p in wt.profiles)}, технологией {order.technology.value}"
                        + (" и допуском на высоту" if order.requires_height else ""),
                        t,
                        day_tz,
                    )
                )
                continue

            target_sid = getattr(order, "target_staff_id", None)
            qual_sched = [
                v_idx
                for v_idx, st in enumerate(sched_staff)
                if (target_sid is None or st.staff_id == target_sid)
                and is_staff_qualified(st, order, wt)
                and eff_start + timedelta_min(wt.duration_min) <= local_hhmm_to_dt(day_date, st.shift.end, day_tz)
            ]
            if not qual_sched:
                reason_code = (
                    UnassignedReasonCode.STAFF_UNAVAILABLE
                    if not sched_staff
                    else UnassignedReasonCode.NO_SHIFT_TIME
                )
                pre_unassigned.append(
                    cls._make_unassigned(
                        order,
                        reason_code,
                        f"Подходящие сотрудники недоступны или смена заканчивается раньше завершения работ по {order.order_id}",
                        t,
                        day_tz,
                    )
                )
                continue

            schedulable_orders.append(order)
            eligible_staff_indices.append(qual_sched)

        routes_by_staff: dict[str, Route] = dict(fixed_routes)
        vehicle_sequences: dict[str, list[Order]] = {st.staff_id: [] for st in sched_staff}
        unscheduled_orders: list[Order] = []

        if sched_staff and schedulable_orders:
            ortools_budget = min(max(1.0, (deadline_monotonic - time.monotonic()) * 0.65), time_limit_sec)
            vehicle_sequences, unscheduled_orders = cls._run_ortools_vrptw(
                sched_staff=sched_staff,
                frozen_by_staff=frozen_by_staff,
                orders=schedulable_orders,
                eligible_staff_indices=eligible_staff_indices,
                work_types=work_types,
                matrix=matrix,
                day_date=day_date,
                day_tz=day_tz,
                origin=origin,
                model_time=t,
                prev_routes_by_staff=prev_routes_by_staff,
                staff_unavailability=staff_unavailability,
                new_order_min_start=new_order_min_start,
                override_visit_end=override_visit_end,
                time_limit_sec=ortools_budget,
            )

        # Stage 2: Exact Route Simulation & Repair
        rescue_pool: list[Order] = list(unscheduled_orders)

        for st in sched_staff:
            seq = vehicle_sequences.get(st.staff_id, [])
            unavail = staff_unavailability.get(st.staff_id)
            prev_stops = prev_routes_by_staff[st.staff_id].stops if st.staff_id in prev_routes_by_staff else None

            route = simulate_route(
                staff=st,
                frozen_stops=frozen_by_staff[st.staff_id],
                future_orders=seq,
                day_date=day_date,
                day_tz=day_tz,
                model_time=t,
                service_centers=service_centers,
                work_types=work_types,
                matrix=matrix,
                unavail=unavail,
                prev_route_stops=prev_stops,
                new_order_min_start=new_order_min_start,
                override_visit_end=override_visit_end,
            )

            if route is None:
                # Incrementally build maximal feasible subset from seq
                accepted: list[Order] = []
                for cand in seq:
                    trial = accepted + [cand]
                    r_trial = simulate_route(
                        staff=st,
                        frozen_stops=frozen_by_staff[st.staff_id],
                        future_orders=trial,
                        day_date=day_date,
                        day_tz=day_tz,
                        model_time=t,
                        service_centers=service_centers,
                        work_types=work_types,
                        matrix=matrix,
                        unavail=unavail,
                        prev_route_stops=prev_stops,
                        new_order_min_start=new_order_min_start,
                        override_visit_end=override_visit_end,
                    )
                    if r_trial is not None:
                        accepted = trial
                    else:
                        rescue_pool.append(cand)
                vehicle_sequences[st.staff_id] = accepted
                route = simulate_route(
                    staff=st,
                    frozen_stops=frozen_by_staff[st.staff_id],
                    future_orders=accepted,
                    day_date=day_date,
                    day_tz=day_tz,
                    model_time=t,
                    service_centers=service_centers,
                    work_types=work_types,
                    matrix=matrix,
                    unavail=unavail,
                    prev_route_stops=prev_stops,
                    new_order_min_start=new_order_min_start,
                    override_visit_end=override_visit_end,
                )
                assert route is not None

            routes_by_staff[st.staff_id] = route

        # Stage 3: Best-Insertion Rescue for dropped/repaired orders (prioritize repeat orders)
        rescue_pool.sort(key=lambda o: (0 if o.is_repeat else 1, o.latest_start, o.order_id))
        still_unassigned: list[Order] = []

        for order in rescue_pool:
            if time.monotonic() > deadline_monotonic - 0.15:
                still_unassigned.append(order)
                continue

            wt = work_types[order.work_type_code.value]
            best_choice: Optional[tuple[float, Staff, list[Order], Route]] = None

            target_sid = getattr(order, "target_staff_id", None)
            for st in sched_staff:
                if target_sid is not None and st.staff_id != target_sid:
                    continue
                if not is_staff_qualified(st, order, wt):
                    continue
                curr_seq = vehicle_sequences[st.staff_id]
                curr_route = routes_by_staff[st.staff_id]
                curr_travel = sum(s.travel_sec or 0 for s in curr_route.stops)
                unavail = staff_unavailability.get(st.staff_id)
                prev_stops = prev_routes_by_staff[st.staff_id].stops if st.staff_id in prev_routes_by_staff else None

                for pos in range(len(curr_seq) + 1):
                    cand_seq = curr_seq[:pos] + [order] + curr_seq[pos:]
                    cand_route = simulate_route(
                        staff=st,
                        frozen_stops=frozen_by_staff[st.staff_id],
                        future_orders=cand_seq,
                        day_date=day_date,
                        day_tz=day_tz,
                        model_time=t,
                        service_centers=service_centers,
                        work_types=work_types,
                        matrix=matrix,
                        unavail=unavail,
                        prev_route_stops=prev_stops,
                        new_order_min_start=new_order_min_start,
                        override_visit_end=override_visit_end,
                    )
                    if cand_route is not None:
                        new_travel = sum(s.travel_sec or 0 for s in cand_route.stops)
                        added_travel = new_travel - curr_travel
                        util_penalty = cls._route_util(cand_route, st, day_date, day_tz) * 600.0
                        score = added_travel + util_penalty
                        if best_choice is None or score < best_choice[0]:
                            best_choice = (score, st, cand_seq, cand_route)

            if best_choice is not None:
                _, st_win, new_seq, new_route = best_choice
                vehicle_sequences[st_win.staff_id] = new_seq
                routes_by_staff[st_win.staff_id] = new_route
            else:
                still_unassigned.append(order)

        # Stage 4: Utilization-CV Workload Balancing Pass
        cls._rebalance_workload(
            sched_staff=sched_staff,
            vehicle_sequences=vehicle_sequences,
            routes_by_staff=routes_by_staff,
            frozen_by_staff=frozen_by_staff,
            day_date=day_date,
            day_tz=day_tz,
            model_time=t,
            service_centers=service_centers,
            work_types=work_types,
            matrix=matrix,
            staff_unavailability=staff_unavailability,
            prev_routes_by_staff=prev_routes_by_staff,
            new_order_min_start=new_order_min_start,
            override_visit_end=override_visit_end,
            deadline_monotonic=deadline_monotonic,
        )

        # Build detailed UnassignedOrder entries for remaining orders
        final_unassigned = list(pre_unassigned)
        for order in still_unassigned:
            final_unassigned.append(
                cls._diagnose_unassigned(
                    order=order,
                    sched_staff=sched_staff,
                    work_types=work_types,
                    routes_by_staff=routes_by_staff,
                    day_date=day_date,
                    day_tz=day_tz,
                    model_time=t,
                )
            )

        ordered_routes = [routes_by_staff[st.staff_id] for st in active_staff]
        return ordered_routes, final_unassigned

    @classmethod
    def _run_ortools_vrptw(
        cls,
        sched_staff: list[Staff],
        frozen_by_staff: dict[str, list],
        orders: list[Order],
        eligible_staff_indices: list[list[int]],
        work_types: dict[str, WorkType],
        matrix: TravelMatrixIndex,
        day_date: date_type,
        day_tz: tzinfo,
        origin: datetime,
        model_time: datetime,
        prev_routes_by_staff: dict[str, Route],
        staff_unavailability: dict[str, tuple[datetime, Optional[datetime]]],
        new_order_min_start: dict[str, datetime],
        override_visit_end: dict[str, datetime],
        time_limit_sec: float,
    ) -> tuple[dict[str, list[Order]], list[Order]]:
        num_vehicles = len(sched_staff)
        num_orders = len(orders)

        # Node indexing:
        # 0 .. num_orders - 1 : order nodes
        # num_orders .. num_orders + num_vehicles - 1 : vehicle start nodes
        # num_orders + num_vehicles .. num_orders + 2*num_vehicles - 1 : vehicle end nodes
        start_offset = num_orders
        end_offset = num_orders + num_vehicles
        num_nodes = num_orders + 2 * num_vehicles

        starts = [start_offset + v for v in range(num_vehicles)]
        ends = [end_offset + v for v in range(num_vehicles)]

        node_points: list[str] = [o.building_id for o in orders]
        node_service_sec: list[int] = [work_types[o.work_type_code.value].duration_min * 60 for o in orders]

        t_sec = dt_to_sec(model_time, origin)
        vehicle_ready_sec: list[int] = []
        vehicle_end_sec: list[int] = []

        for v, st in enumerate(sched_staff):
            fr = frozen_by_staff[st.staff_id]
            shift_s = dt_to_sec(local_hhmm_to_dt(day_date, st.shift.start, day_tz), origin)
            shift_e = dt_to_sec(local_hhmm_to_dt(day_date, st.shift.end, day_tz), origin)
            has_brk = any(s.type == StopType.BREAK for s in fr)
            brk_reserve = 0 if has_brk else st.shift.break_duration_min * 60

            if fr:
                start_loc = fr[-1].location_id
                ready = max(dt_to_sec(fr[-1].end, origin), t_sec)
            else:
                start_loc = st.service_center_id
                ready = max(shift_s, t_sec)

            unavail = staff_unavailability.get(st.staff_id)
            if unavail is not None and unavail[1] is not None:
                u_from_s = dt_to_sec(norm_dt(unavail[0], day_tz), origin)
                u_until_s = dt_to_sec(norm_dt(unavail[1], day_tz), origin)
                if u_from_s <= ready < u_until_s:
                    ready = u_until_s
                    start_loc = st.service_center_id

            ready = min(ready, shift_e)
            node_points.append(start_loc)
            node_service_sec.append(0)
            vehicle_ready_sec.append(ready)
            # Reserve break duration inside shift end bound for OR-Tools feasibility.
            vehicle_end_sec.append(max(ready, shift_e - brk_reserve))

        for st in sched_staff:
            node_points.append(st.service_center_id)
            node_service_sec.append(0)

        mgr = pywrapcp.RoutingIndexManager(num_nodes, num_vehicles, starts, ends)
        routing = pywrapcp.RoutingModel(mgr)

        # Precompute point indices in TravelMatrixIndex for fast C++/Python callback
        point_idx = [matrix.point_to_idx[p] for p in node_points]
        durations = matrix.durations_sec

        def travel_cb(fi: int, ti: int) -> int:
            fn = mgr.IndexToNode(fi)
            tn = mgr.IndexToNode(ti)
            pi = point_idx[fn]
            pj = point_idx[tn]
            return 0 if pi == pj else durations[pi][pj]

        def time_cb(fi: int, ti: int) -> int:
            fn = mgr.IndexToNode(fi)
            tn = mgr.IndexToNode(ti)
            pi = point_idx[fn]
            pj = point_idx[tn]
            tr = 0 if pi == pj else durations[pi][pj]
            return node_service_sec[fn] + tr

        travel_cb_idx = routing.RegisterTransitCallback(travel_cb)
        time_cb_idx = routing.RegisterTransitCallback(time_cb)

        routing.SetArcCostEvaluatorOfAllVehicles(travel_cb_idx)

        max_horizon = 86400 * 2
        routing.AddDimension(
            time_cb_idx,
            max_horizon,  # allow waiting before slot.start
            max_horizon,
            False,
            "Time",
        )
        time_dim = routing.GetDimensionOrDie("Time")

        # Time windows are constrained here. Workload balancing is applied in a separate
        # post-optimization pass grouped by staff profile (INSTALL vs LTP3), so that
        # installation and service workloads are never balanced against each other.
        for v in range(num_vehicles):
            s_idx = routing.Start(v)
            e_idx = routing.End(v)
            time_dim.CumulVar(s_idx).SetRange(vehicle_ready_sec[v], vehicle_end_sec[v])
            time_dim.CumulVar(e_idx).SetRange(vehicle_ready_sec[v], vehicle_end_sec[v])

        # Configure order time windows, vehicle eligibility, and weighted drop penalties
        order_id_to_node = {o.order_id: i for i, o in enumerate(orders)}
        for i, order in enumerate(orders):
            o_idx = mgr.NodeToIndex(i)
            slot_s = dt_to_sec(norm_dt(order.slot.start, day_tz), origin)
            latest_s = dt_to_sec(norm_dt(order.latest_start, day_tz), origin)
            if order.order_id in new_order_min_start:
                slot_s = max(slot_s, dt_to_sec(norm_dt(new_order_min_start[order.order_id], day_tz), origin))
            time_dim.CumulVar(o_idx).SetRange(slot_s, latest_s)
            routing.VehicleVar(o_idx).SetValues([-1] + eligible_staff_indices[i])

            penalty = 2_000_000 if order.is_repeat else 1_000_000
            routing.AddDisjunction([o_idx], penalty)

        # Search parameters
        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        search_params.local_search_metaheuristic = routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        search_params.time_limit.FromMilliseconds(max(200, int(time_limit_sec * 1000)))

        # Warm-start from previous plan during replanning (fast convergence & minimal churn)
        solution = None
        if prev_routes_by_staff:
            init_routes: list[list[int]] = []
            for v, st in enumerate(sched_staff):
                pr = prev_routes_by_staff.get(st.staff_id)
                r_nodes: list[int] = []
                if pr is not None:
                    for stop in pr.stops:
                        if stop.type == StopType.VISIT and stop.order_id in order_id_to_node:
                            n_idx = order_id_to_node[stop.order_id]
                            if v in eligible_staff_indices[n_idx]:
                                r_nodes.append(n_idx)
                init_routes.append(r_nodes)
            routing.CloseModelWithParameters(search_params)
            initial_sol = routing.ReadAssignmentFromRoutes(init_routes, True)
            if initial_sol is not None:
                solution = routing.SolveFromAssignmentWithParameters(initial_sol, search_params)

        if solution is None:
            solution = routing.SolveWithParameters(search_params)

        sequences: dict[str, list[Order]] = {st.staff_id: [] for st in sched_staff}
        assigned_nodes: set[int] = set()

        if solution is not None:
            for v, st in enumerate(sched_staff):
                index = routing.Start(v)
                seq: list[Order] = []
                while not routing.IsEnd(index):
                    node = mgr.IndexToNode(index)
                    if node < num_orders:
                        seq.append(orders[node])
                        assigned_nodes.add(node)
                    index = solution.Value(routing.NextVar(index))
                sequences[st.staff_id] = seq

        unscheduled = [orders[i] for i in range(num_orders) if i not in assigned_nodes]
        return sequences, unscheduled

    @staticmethod
    def _route_util(route: Route, staff: Staff, day_date: date_type, day_tz: tzinfo) -> float:
        work_sec = sum(
            max(0, int((s.end - s.start).total_seconds()))
            for s in route.stops
            if s.type == StopType.VISIT
        )
        trav_sec = sum(s.travel_sec or 0 for s in route.stops)
        shift_s = local_hhmm_to_dt(day_date, staff.shift.start, day_tz)
        shift_e = local_hhmm_to_dt(day_date, staff.shift.end, day_tz)
        avail = max(1, int((shift_e - shift_s).total_seconds()) - staff.shift.break_duration_min * 60)
        return (work_sec + trav_sec) / avail

    @classmethod
    def _rebalance_workload(
        cls,
        sched_staff: list[Staff],
        **kwargs,
    ) -> None:
        """Balance routes only among workers with the same profile set."""
        groups: dict[tuple[str, ...], list[Staff]] = {}
        for staff in sched_staff:
            profile_key = tuple(sorted(profile.value for profile in staff.profiles))
            groups.setdefault(profile_key, []).append(staff)

        for group_staff in groups.values():
            if len(group_staff) > 1:
                cls._rebalance_workload_group(sched_staff=group_staff, **kwargs)

    @classmethod
    def _rebalance_workload_group(
        cls,
        sched_staff: list[Staff],
        vehicle_sequences: dict[str, list[Order]],
        routes_by_staff: dict[str, Route],
        frozen_by_staff: dict[str, list],
        day_date: date_type,
        day_tz: tzinfo,
        model_time: datetime,
        service_centers: list[ServiceCenter],
        work_types: dict[str, WorkType],
        matrix: TravelMatrixIndex,
        staff_unavailability: dict[str, tuple[datetime, Optional[datetime]]],
        prev_routes_by_staff: dict[str, Route],
        new_order_min_start: dict[str, datetime],
        override_visit_end: dict[str, datetime],
        deadline_monotonic: float,
    ) -> None:
        if len(sched_staff) < 2:
            return

        staff_map = {st.staff_id: st for st in sched_staff}

        def compute_cv(utils: dict[str, float]) -> float:
            vals = list(utils.values())
            mean = sum(vals) / len(vals)
            if mean <= 1e-9:
                return 0.0
            return math.sqrt(sum((x - mean) ** 2 for x in vals) / len(vals)) / mean

        utils = {
            st.staff_id: cls._route_util(routes_by_staff[st.staff_id], st, day_date, day_tz)
            for st in sched_staff
        }

        for _ in range(40):
            if time.monotonic() > deadline_monotonic - 0.1:
                break
            curr_cv = compute_cv(utils)
            if curr_cv < 0.06:
                break

            donors = sorted(
                [st.staff_id for st in sched_staff if len(vehicle_sequences[st.staff_id]) >= 1],
                key=lambda sid: utils[sid],
                reverse=True,
            )
            receivers = sorted([st.staff_id for st in sched_staff], key=lambda sid: utils[sid])

            moved = False
            for d_sid in donors[:6]:
                if time.monotonic() > deadline_monotonic - 0.1:
                    break
                d_seq = vehicle_sequences[d_sid]
                d_staff = staff_map[d_sid]

                for r_sid in receivers[:8]:
                    if r_sid == d_sid or utils[r_sid] >= utils[d_sid] - 0.08:
                        continue
                    r_staff = staff_map[r_sid]
                    r_seq = vehicle_sequences[r_sid]

                    for idx_o, order in enumerate(d_seq):
                        if getattr(order, "target_staff_id", None) is not None:
                            continue
                        wt = work_types[order.work_type_code.value]
                        if not is_staff_qualified(r_staff, order, wt):
                            continue
                        new_d_seq = d_seq[:idx_o] + d_seq[idx_o + 1 :]
                        new_d_route = simulate_route(
                            staff=d_staff,
                            frozen_stops=frozen_by_staff[d_sid],
                            future_orders=new_d_seq,
                            day_date=day_date,
                            day_tz=day_tz,
                            model_time=model_time,
                            service_centers=service_centers,
                            work_types=work_types,
                            matrix=matrix,
                            unavail=staff_unavailability.get(d_sid),
                            prev_route_stops=prev_routes_by_staff[d_sid].stops if d_sid in prev_routes_by_staff else None,
                            new_order_min_start=new_order_min_start,
                            override_visit_end=override_visit_end,
                        )
                        if new_d_route is None:
                            continue

                        old_travel = sum(s.travel_sec or 0 for s in routes_by_staff[d_sid].stops) + sum(
                            s.travel_sec or 0 for s in routes_by_staff[r_sid].stops
                        )
                        new_d_travel = sum(s.travel_sec or 0 for s in new_d_route.stops)

                        for pos in range(len(r_seq) + 1):
                            new_r_seq = r_seq[:pos] + [order] + r_seq[pos:]
                            new_r_route = simulate_route(
                                staff=r_staff,
                                frozen_stops=frozen_by_staff[r_sid],
                                future_orders=new_r_seq,
                                day_date=day_date,
                                day_tz=day_tz,
                                model_time=model_time,
                                service_centers=service_centers,
                                work_types=work_types,
                                matrix=matrix,
                                unavail=staff_unavailability.get(r_sid),
                                prev_route_stops=prev_routes_by_staff[r_sid].stops if r_sid in prev_routes_by_staff else None,
                                new_order_min_start=new_order_min_start,
                                override_visit_end=override_visit_end,
                            )
                            if new_r_route is None:
                                continue

                            new_travel = new_d_travel + sum(s.travel_sec or 0 for s in new_r_route.stops)
                            if new_travel - old_travel > 900:  # do not add > 15 min detour for minor balance
                                continue

                            cand_utils = dict(utils)
                            cand_utils[d_sid] = cls._route_util(new_d_route, d_staff, day_date, day_tz)
                            cand_utils[r_sid] = cls._route_util(new_r_route, r_staff, day_date, day_tz)
                            new_cv = compute_cv(cand_utils)
                            if new_cv + 0.003 < curr_cv:
                                vehicle_sequences[d_sid] = new_d_seq
                                vehicle_sequences[r_sid] = new_r_seq
                                routes_by_staff[d_sid] = new_d_route
                                routes_by_staff[r_sid] = new_r_route
                                utils = cand_utils
                                moved = True
                                break
                        if moved:
                            break
                    if moved:
                        break
                if moved:
                    break
            if not moved:
                break

    @classmethod
    def _diagnose_unassigned(
        cls,
        order: Order,
        sched_staff: list[Staff],
        work_types: dict[str, WorkType],
        routes_by_staff: dict[str, Route],
        day_date: date_type,
        day_tz: tzinfo,
        model_time: datetime,
    ) -> UnassignedOrder:
        wt = work_types[order.work_type_code.value]
        qual = [st for st in sched_staff if is_staff_qualified(st, order, wt)]
        if not qual:
            return cls._make_unassigned(
                order,
                UnassignedReasonCode.NO_QUALIFIED_STAFF,
                f"Нет доступного сотрудника с допуском/технологией {order.technology.value} для {order.order_id}",
                model_time,
                day_tz,
            )

        # If no qualified worker can ever carry the required equipment, classify it
        # explicitly instead of incorrectly reporting a slot/shift problem.
        if not any(st.equipment_capacity.can_supply(order.required_equipment) for st in qual):
            return cls._make_unassigned(
                order,
                UnassignedReasonCode.NO_EQUIPMENT,
                f"Ни у одного подходящего сотрудника нет требуемого оборудования даже после пополнения в СЦ для {order.order_id}",
                model_time,
                day_tz,
            )

        # Check whether qualified staff have remaining shift time.
        has_free_shift = False
        for st in qual:
            r = routes_by_staff.get(st.staff_id)
            if r is None or not r.stops:
                has_free_shift = True
                break
            if len(r.stops) >= 2:
                last_visit_end = max((s.end for s in r.stops if s.type == StopType.VISIT), default=local_hhmm_to_dt(day_date, st.shift.start, day_tz))
                if last_visit_end + timedelta_min(wt.duration_min) <= local_hhmm_to_dt(day_date, st.shift.end, day_tz):
                    has_free_shift = True
                    break

        if not has_free_shift:
            return cls._make_unassigned(
                order,
                UnassignedReasonCode.NO_SHIFT_TIME,
                f"У подходящих сотрудников исчерпано время смены для выполнения {order.order_id}",
                model_time,
                day_tz,
            )

        return cls._make_unassigned(
            order,
            UnassignedReasonCode.SLOT_UNREACHABLE,
            f"Ни один подходящий сотрудник не успевает прибыть в слот до {norm_dt(order.latest_start, day_tz).strftime('%H:%M')}",
            model_time,
            day_tz,
        )

    @staticmethod
    def _make_unassigned(
        order: Order,
        reason_code: UnassignedReasonCode,
        reason_text: str,
        model_time: datetime,
        day_tz: tzinfo,
    ) -> UnassignedOrder:
        from datetime import timedelta

        action = (
            UnassignedSuggestedAction.ESCALATE
            if reason_code == UnassignedReasonCode.NO_QUALIFIED_STAFF
            else UnassignedSuggestedAction.RESCHEDULE
        )
        proposed_slot = (
            TimeWindow(
                start=norm_dt(order.slot.start + timedelta(days=1), day_tz),
                end=norm_dt(order.slot.end + timedelta(days=1), day_tz),
            )
            if action == UnassignedSuggestedAction.RESCHEDULE
            else None
        )
        return UnassignedOrder(
            order_id=order.order_id,
            reason_code=reason_code,
            reason_text=reason_text,
            suggested_action=action,
            proposed_slot=proposed_slot,
            since=norm_dt(model_time, day_tz),
        )


def timedelta_min(minutes: int):
    from datetime import timedelta

    return timedelta(minutes=minutes)
