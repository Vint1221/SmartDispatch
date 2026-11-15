from __future__ import annotations

from app.demo_data import TZ_EKB, build_demo_dataset
from app.routing.matrix import TravelMatrixIndex
from app.schemas.plan import Plan, RouteStatus, StopType
from app.services.validation_service import PlanValidator


def test_pgp_detection_events_freeze_and_idempotency(client):
    ref, matrix, day_input, _ = build_demo_dataset(num_orders=60, seed=11)
    assert client.put("/api/v1/reference", json=ref.model_dump(mode="json", by_alias=True)).status_code == 200
    assert client.put("/api/v1/reference/travel-matrix", json=matrix.model_dump(mode="json")).status_code == 200
    assert client.put("/api/v1/days/2026-10-26", json=day_input.model_dump(mode="json")).status_code == 200

    res_p1 = client.post("/api/v1/days/2026-10-26/plan", json={"time_limit_sec": 20})
    assert res_p1.status_code == 200
    plan_v1 = Plan.model_validate(res_p1.json())
    assert plan_v1.plan_version == 1
    assert len(plan_v1.pgp_groups) == 1
    assert set(plan_v1.pgp_groups[0].order_ids) == {
        "ORD-20261026-0001",
        "ORD-20261026-0002",
        "ORD-20261026-0003",
    }
    initial_detected_at = plan_v1.pgp_groups[0].detected_at

    # Pick an active staff with at least 2 visits to test VISIT_DELAYED, ORDER_TRANSFERRED, STAFF_UNAVAILABLE
    busy_routes = [
        r for r in plan_v1.routes if sum(1 for s in r.stops if s.type == StopType.VISIT) >= 2
    ]
    assert len(busy_routes) >= 2
    route_a = busy_routes[0]
    visits_a = [s for s in route_a.stops if s.type == StopType.VISIT]
    first_visit_a = visits_a[0]
    second_visit_a = visits_a[1]

    # 1. NEW_ORDER (repeat) joining PGP access node AN-0001 -> detected_at preserved!
    b_an1 = ref.access_nodes[0].buildings[0]
    ev_new_pgp = {
        "event_id": "EV-001",
        "type": "NEW_ORDER",
        "timestamp": "2026-10-26T08:45:00+05:00",
        "order": {
            "order_id": "ORD-20261026-9001",
            "work_type_code": "REPAIR",
            "technology": ref.access_nodes[0].technology.value,
            "building_id": b_an1.building_id,
            "address": b_an1.address,
            "lat": b_an1.lat,
            "lon": b_an1.lon,
            "building_type": b_an1.building_type.value,
            "requires_height": b_an1.overhead_line,
            "access_node_id": ref.access_nodes[0].access_node_id,
            "registered_at": "2026-10-26T08:45:00+05:00",
            "slot": {"start": "2026-10-26T10:00:00+05:00", "end": "2026-10-26T12:00:00+05:00"},
            "latest_start": "2026-10-26T12:00:00+05:00",
            "deadline": "2026-10-26T20:45:00+05:00",
            "required_equipment": {"ONT": 1, "ROUTER": 0, "STB": 0},
            "is_repeat": True,
            "previous_order_id": None,
        },
    }
    r1 = client.post("/api/v1/days/2026-10-26/events", json=ev_new_pgp)
    assert r1.status_code == 200
    assert r1.json()["plan_version"] == 2
    assert r1.json()["duplicate"] is False
    plan_v2 = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())
    assert "ORD-20261026-9001" in plan_v2.pgp_groups[0].order_ids
    assert plan_v2.pgp_groups[0].detected_at == initial_detected_at

    # Idempotency replay of EV-001
    r1_dup = client.post("/api/v1/days/2026-10-26/events", json=ev_new_pgp)
    assert r1_dup.status_code == 200
    assert r1_dup.json()["duplicate"] is True
    assert r1_dup.json()["plan_version"] == 2

    # Out-of-order timestamp -> 409
    r_ooo = client.post(
        "/api/v1/days/2026-10-26/events",
        json={"event_id": "EV-OOO", "type": "TIME_TICK", "timestamp": "2026-10-26T08:40:00+05:00"},
    )
    assert r_ooo.status_code == 409
    assert r_ooo.json()["error"]["code"] == "EVENT_OUT_OF_ORDER"

    # 2. NEW_ORDER regular schedulable order
    b_an2 = ref.access_nodes[1].buildings[0]
    ev_new_sched = {
        "event_id": "EV-002",
        "type": "NEW_ORDER",
        "timestamp": "2026-10-26T09:00:00+05:00",
        "order": {
            "order_id": "ORD-20261026-9002",
            "work_type_code": "REPAIR",
            "technology": ref.access_nodes[1].technology.value,
            "building_id": b_an2.building_id,
            "address": b_an2.address,
            "lat": b_an2.lat,
            "lon": b_an2.lon,
            "building_type": b_an2.building_type.value,
            "requires_height": b_an2.overhead_line,
            "access_node_id": ref.access_nodes[1].access_node_id,
            "registered_at": "2026-10-26T09:00:00+05:00",
            "slot": {"start": "2026-10-26T14:00:00+05:00", "end": "2026-10-26T16:00:00+05:00"},
            "latest_start": "2026-10-26T16:00:00+05:00",
            "deadline": "2026-10-26T21:00:00+05:00",
            "required_equipment": {"ONT": 0, "ROUTER": 1, "STB": 0},
            "is_repeat": False,
            "previous_order_id": None,
        },
    }
    r2 = client.post("/api/v1/days/2026-10-26/events", json=ev_new_sched)
    assert r2.status_code == 200
    assert r2.json()["plan_version"] == 3

    # 3. VISIT_DELAYED on route_a's first visit (after its start)
    plan_v3 = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())
    r_a_v3 = next(r for r in plan_v3.routes if r.staff_id == route_a.staff_id)
    v1_a = next(s for s in r_a_v3.stops if s.type == StopType.VISIT)
    from datetime import timedelta

    delay_ts = (v1_a.start + timedelta(minutes=10)).isoformat(timespec="seconds")
    delay_exp = (v1_a.end + timedelta(minutes=30)).isoformat(timespec="seconds")
    r3 = client.post(
        "/api/v1/days/2026-10-26/events",
        json={
            "event_id": "EV-003",
            "type": "VISIT_DELAYED",
            "timestamp": delay_ts,
            "staff_id": route_a.staff_id,
            "order_id": v1_a.order_id,
            "expected_end": delay_exp,
        },
    )
    assert r3.status_code == 200
    assert r3.json()["plan_version"] == 4
    plan_v4 = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())
    r_a_v4 = next(r for r in plan_v4.routes if r.staff_id == route_a.staff_id)
    v1_a_after = next(s for s in r_a_v4.stops if s.order_id == v1_a.order_id)
    assert v1_a_after.end.isoformat(timespec="seconds") == delay_exp
    assert v1_a_after.start == v1_a.start

    # 4. ORDER_CANCELLED on an unstarted future visit
    future_visit = None
    for r in plan_v4.routes:
        for s in r.stops:
            if s.type == StopType.VISIT and s.start > v1_a.start + timedelta(minutes=90):
                future_visit = s
                break
        if future_visit:
            break
    assert future_visit is not None
    cancel_ts = (v1_a.start + timedelta(minutes=20)).isoformat(timespec="seconds")
    r4 = client.post(
        "/api/v1/days/2026-10-26/events",
        json={
            "event_id": "EV-004",
            "type": "ORDER_CANCELLED",
            "timestamp": cancel_ts,
            "order_id": future_visit.order_id,
            "reason": "NOT_CONFIRMED",
        },
    )
    assert r4.status_code == 200
    assert r4.json()["plan_version"] == 5
    plan_v5 = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())
    assert any(c.order_id == future_visit.order_id for c in plan_v5.cancelled)

    # 5. STAFF_UNAVAILABLE on another busy route
    route_b = next(
        r for r in plan_v5.routes if r.staff_id != route_a.staff_id and sum(1 for s in r.stops if s.type == StopType.VISIT) >= 1
    )
    unavail_ts = (v1_a.start + timedelta(minutes=25)).isoformat(timespec="seconds")
    r5 = client.post(
        "/api/v1/days/2026-10-26/events",
        json={
            "event_id": "EV-005",
            "type": "STAFF_UNAVAILABLE",
            "timestamp": unavail_ts,
            "staff_id": route_b.staff_id,
            "until": None,
            "reason": "VEHICLE_BREAKDOWN",
        },
    )
    assert r5.status_code == 200
    assert r5.json()["processing_ms"] < 10000
    plan_v6 = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())
    r_b_after = next(r for r in plan_v6.routes if r.staff_id == route_b.staff_id)
    assert r_b_after.status == RouteStatus.UNAVAILABLE

    # 6. TIME_TICK
    tick_ts = (v1_a.start + timedelta(minutes=30)).isoformat(timespec="seconds")
    r6 = client.post(
        "/api/v1/days/2026-10-26/events",
        json={"event_id": "EV-006", "type": "TIME_TICK", "timestamp": tick_ts},
    )
    assert r6.status_code == 200
    assert r6.json()["plan_version"] == 7

    # 7. ORDER_TRANSFERRED on an in-progress visit at tick_ts
    plan_v7 = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())
    in_prog_visit = None
    in_prog_staff = None
    tick_dt = plan_v7.as_of
    for r in plan_v7.routes:
        for s in r.stops:
            if s.type == StopType.VISIT and s.start <= tick_dt <= s.end and s.order_id != v1_a.order_id:
                in_prog_visit = s
                in_prog_staff = r.staff_id
                break
        if in_prog_visit:
            break
    if in_prog_visit is None:
        in_prog_visit = v1_a_after
        in_prog_staff = route_a.staff_id

    trans_ts = (tick_dt + timedelta(minutes=5)).isoformat(timespec="seconds")
    r7 = client.post(
        "/api/v1/days/2026-10-26/events",
        json={
            "event_id": "EV-007",
            "type": "ORDER_TRANSFERRED",
            "timestamp": trans_ts,
            "staff_id": in_prog_staff,
            "order_id": in_prog_visit.order_id,
            "actual_end": trans_ts,
            "transferred_to": "STATION_EQUIPMENT",
        },
    )
    assert r7.status_code == 200
    assert r7.json()["plan_version"] == 8
    plan_v8 = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())

    # Alerts list must never shrink across versions
    assert len(plan_v8.alerts) >= len(plan_v5.alerts) >= len(plan_v1.alerts)

    # Final H1-H10 check between v7 and v8
    all_orders = {o.order_id: o for o in day_input.orders}
    from app.schemas.day import Order

    all_orders["ORD-20261026-9001"] = Order.model_validate(ev_new_pgp["order"])
    all_orders["ORD-20261026-9002"] = Order.model_validate(ev_new_sched["order"])
    violations = PlanValidator.validate(
        plan=plan_v8,
        staff_by_id={s.staff_id: s for s in ref.staff},
        absent_staff_ids={"ST-017"},
        service_centers_by_id={sc.service_center_id: sc for sc in ref.service_centers},
        work_types_by_code={w.code.value: w for w in ref.work_types},
        orders_by_id=all_orders,
        matrix=TravelMatrixIndex(matrix),
        day_tz=TZ_EKB,
        prev_plan=plan_v7,
        model_time=plan_v8.as_of,
        override_visit_end={
            v1_a.order_id: v1_a_after.end,
            in_prog_visit.order_id: plan_v8.as_of,
        },
        force_started_order_ids={v1_a.order_id, in_prog_visit.order_id},
        cancelled_order_ids={future_visit.order_id},
    )
    assert violations == []


def test_started_visit_counts_toward_pgp_threshold_but_is_not_grouped():
    """A started visit is part of the incident threshold, but stays in its route."""
    from app.services.pgp_service import PgpService

    ref, _, day_input, _ = build_demo_dataset(num_orders=10, seed=11)
    pgp_orders = [o for o in day_input.orders if o.work_type_code.value == "REPAIR" and o.access_node_id == ref.access_nodes[0].access_node_id][:3]
    assert len(pgp_orders) == 3
    started_id = pgp_orders[0].order_id

    groups, created = PgpService.detect_groups(
        orders=pgp_orders,
        cancelled_order_ids=set(),
        started_order_ids={started_id},
        work_types={w.code.value: w for w in ref.work_types},
        access_nodes={a.access_node_id: a for a in ref.access_nodes},
        existing_groups=[],
        as_of=day_input.now,
        day_tz=TZ_EKB,
        date_str=day_input.date.isoformat(),
    )

    assert len(groups) == 1
    assert groups == created
    assert started_id not in groups[0].order_ids
    assert len(groups[0].order_ids) == 2


def test_manual_order_assignment_to_staff(client):
    ref, matrix, day_input, _ = build_demo_dataset(num_orders=25, seed=42)
    assert client.put("/api/v1/reference", json=ref.model_dump(mode="json", by_alias=True)).status_code == 200
    assert client.put("/api/v1/reference/travel-matrix", json=matrix.model_dump(mode="json")).status_code == 200
    assert client.put("/api/v1/days/2026-10-26", json=day_input.model_dump(mode="json")).status_code == 200
    assert client.post("/api/v1/days/2026-10-26/plan", json={"time_limit_sec": 15}).status_code == 200

    chosen_staff = ref.staff[0]
    b = ref.access_nodes[0].buildings[0]

    ev_targeted = {
        "event_id": "EV-MANUAL-001",
        "type": "NEW_ORDER",
        "timestamp": "2026-10-26T09:00:00+05:00",
        "order": {
            "order_id": "ORD-MANUAL-001",
            "work_type_code": "INST_PON_MKD" if "INSTALL" in [p.value for p in chosen_staff.profiles] else "REPAIR",
            "technology": ref.access_nodes[0].technology.value,
            "building_id": b.building_id,
            "address": b.address,
            "lat": b.lat,
            "lon": b.lon,
            "building_type": b.building_type.value,
            "requires_height": False,
            "access_node_id": ref.access_nodes[0].access_node_id,
            "registered_at": "2026-10-26T09:00:00+05:00",
            "slot": {"start": "2026-10-26T13:00:00+05:00", "end": "2026-10-26T15:00:00+05:00"},
            "latest_start": "2026-10-26T15:00:00+05:00",
            "deadline": "2026-10-26T22:00:00+05:00",
            "required_equipment": {"ONT": 1, "ROUTER": 1, "STB": 0},
            "is_repeat": False,
            "target_staff_id": chosen_staff.staff_id,
        },
    }
    r = client.post("/api/v1/days/2026-10-26/events", json=ev_targeted)
    assert r.status_code == 200
    assert r.json()["accepted"] is True

    plan = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())
    other_visit_orders = [
        s.order_id
        for route in plan.routes
        if route.staff_id != chosen_staff.staff_id
        for s in route.stops
        if s.type == StopType.VISIT
    ]
    assert "ORD-MANUAL-001" not in other_visit_orders
