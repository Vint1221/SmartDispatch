from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.demo_data import build_demo_dataset
from app.routing.matrix import TravelMatrixIndex
from app.schemas.common import BuildingType, Equipment, Profile, Technology, TimeWindow, WorkTypeCode
from app.schemas.day import DayInput, Order
from app.schemas.plan import Plan, StopType, UnassignedReasonCode
from app.schemas.reference import (
    AccessNode,
    BreakWindow,
    Building,
    DeadlineKind,
    NodeType,
    OpeningHours,
    ReferenceData,
    ServiceCenter,
    Shift,
    Staff,
    TravelMatrix,
    WorkType,
)
from app.services.validation_service import PlanValidator

TZ = timezone(timedelta(hours=5))


def test_full_constraints_h1_to_h9_and_restock_and_asymmetry(client):
    """
    Tests:
    - H1: height_permit, technology, profile filtering
    - H3: BREAK inside break_window at previous location with travel=0
    - H6: asymmetric travel matrix (SC->B1 != B1->SC)
    - H7/H8: equipment_start=1 ONT forces RESTOCK at open SC to serve 2 ONT orders
    - H9: every order in exactly one place
    """
    sc1 = ServiceCenter(
        service_center_id="SC-01",
        name="SC1",
        address="Addr 1",
        lat=56.85,
        lon=60.60,
        opening_hours=OpeningHours(open="08:00", close="20:00"),
        restock_duration_min=15,
    )
    st_height = Staff(
        staff_id="ST-001",
        service_center_id="SC-01",
        profiles=[Profile.LTP3],
        technologies=[Technology.PON],
        height_permit=True,
        shift=Shift(
            start="09:00",
            end="18:00",
            break_duration_min=60,
            break_window=BreakWindow(from_="12:00", to="15:00"),
        ),
        equipment_start=Equipment(ONT=1, ROUTER=1, STB=0),
        equipment_capacity=Equipment(ONT=3, ROUTER=3, STB=2),
    )
    st_no_height = Staff(
        staff_id="ST-002",
        service_center_id="SC-01",
        profiles=[Profile.LTP3],
        technologies=[Technology.PON],
        height_permit=False,
        shift=Shift(
            start="09:00",
            end="18:00",
            break_duration_min=60,
            break_window=BreakWindow(from_="12:00", to="15:00"),
        ),
        equipment_start=Equipment(ONT=1, ROUTER=1, STB=0),
        equipment_capacity=Equipment(ONT=3, ROUTER=3, STB=2),
    )

    b1 = Building(
        building_id="B-00001",
        address="B1",
        lat=56.86,
        lon=60.61,
        building_type=BuildingType.PRIVATE,
        overhead_line=True,
    )
    b2 = Building(
        building_id="B-00002",
        address="B2",
        lat=56.87,
        lon=60.62,
        building_type=BuildingType.PRIVATE,
        overhead_line=True,
    )
    b3 = Building(
        building_id="B-00003",
        address="B3",
        lat=56.88,
        lon=60.63,
        building_type=BuildingType.MKD,
        overhead_line=False,
    )

    an = AccessNode(
        access_node_id="AN-0001",
        node_type=NodeType.OLT,
        technology=Technology.PON,
        name="OLT-1",
        lat=56.86,
        lon=60.61,
        buildings=[b1, b2, b3],
    )
    wt_repair = WorkType(
        code=WorkTypeCode.REPAIR,
        name="Repair",
        profiles=[Profile.LTP3],
        duration_min=60,
        max_start_delay_min=None,
        deadline_kind=DeadlineKind.HOURS,
        deadline_value=24,
        repeat_deadline_value=12,
        pgp_relevant=True,
    )
    wt_inst = WorkType(
        code=WorkTypeCode.INST_PON_MKD,
        name="Install",
        profiles=[Profile.INSTALL],
        duration_min=90,
        max_start_delay_min=10,
        deadline_kind=DeadlineKind.WORKING_DAYS,
        deadline_value=3,
        repeat_deadline_value=None,
        pgp_relevant=False,
    )

    ref = ReferenceData(
        service_centers=[sc1],
        staff=[st_height, st_no_height],
        access_nodes=[an],
        work_types=[wt_repair, wt_inst],
    )

    # Asymmetric travel durations (in seconds)
    matrix = TravelMatrix(
        matrix_id="test-asym",
        points=["SC-01", "B-00001", "B-00002", "B-00003"],
        durations_sec=[
            [0, 600, 900, 1200],
            [750, 0, 300, 600],
            [1100, 450, 0, 300],
            [1400, 700, 400, 0],
        ],
        distances_m=[
            [0, 3000, 4000, 5000],
            [3500, 0, 1500, 2500],
            [4500, 2000, 0, 1500],
            [5500, 3000, 2000, 0],
        ],
    )

    orders = [
        # Requires height + 1 ONT (morning) -> must go to ST-001
        Order(
            order_id="ORD-20261026-0001",
            work_type_code=WorkTypeCode.REPAIR,
            technology=Technology.PON,
            building_id="B-00001",
            address="B1",
            lat=56.86,
            lon=60.61,
            building_type=BuildingType.PRIVATE,
            requires_height=True,
            access_node_id="AN-0001",
            registered_at=datetime(2026, 10, 26, 8, 0, tzinfo=TZ),
            slot=TimeWindow(
                start=datetime(2026, 10, 26, 9, 0, tzinfo=TZ),
                end=datetime(2026, 10, 26, 11, 0, tzinfo=TZ),
            ),
            latest_start=datetime(2026, 10, 26, 11, 0, tzinfo=TZ),
            deadline=datetime(2026, 10, 26, 18, 0, tzinfo=TZ),
            required_equipment=Equipment(ONT=1, ROUTER=0, STB=0),
            is_repeat=False,
        ),
        # Requires height + 1 ONT (afternoon) -> must ALSO go to ST-001, forcing RESTOCK!
        Order(
            order_id="ORD-20261026-0002",
            work_type_code=WorkTypeCode.REPAIR,
            technology=Technology.PON,
            building_id="B-00002",
            address="B2",
            lat=56.87,
            lon=60.62,
            building_type=BuildingType.PRIVATE,
            requires_height=True,
            access_node_id="AN-0001",
            registered_at=datetime(2026, 10, 26, 8, 5, tzinfo=TZ),
            slot=TimeWindow(
                start=datetime(2026, 10, 26, 13, 30, tzinfo=TZ),
                end=datetime(2026, 10, 26, 15, 30, tzinfo=TZ),
            ),
            latest_start=datetime(2026, 10, 26, 15, 30, tzinfo=TZ),
            deadline=datetime(2026, 10, 26, 18, 0, tzinfo=TZ),
            required_equipment=Equipment(ONT=1, ROUTER=0, STB=0),
            is_repeat=True,
        ),
        # INSTALL order, no INSTALL staff on shift -> unassigned NO_QUALIFIED_STAFF
        Order(
            order_id="ORD-20261026-0003",
            work_type_code=WorkTypeCode.INST_PON_MKD,
            technology=Technology.PON,
            building_id="B-00003",
            address="B3",
            lat=56.88,
            lon=60.63,
            building_type=BuildingType.MKD,
            requires_height=False,
            access_node_id="AN-0001",
            registered_at=datetime(2026, 10, 26, 8, 10, tzinfo=TZ),
            slot=TimeWindow(
                start=datetime(2026, 10, 26, 10, 0, tzinfo=TZ),
                end=datetime(2026, 10, 26, 12, 0, tzinfo=TZ),
            ),
            latest_start=datetime(2026, 10, 26, 10, 10, tzinfo=TZ),
            deadline=datetime(2026, 10, 27, 10, 0, tzinfo=TZ),
            required_equipment=Equipment(ONT=1, ROUTER=1, STB=0),
            is_repeat=False,
        ),
    ]

    day = DayInput(
        date=datetime(2026, 10, 26, tzinfo=TZ).date(),
        now=datetime(2026, 10, 26, 8, 30, tzinfo=TZ),
        orders=orders,
    )

    assert client.put("/api/v1/reference", json=ref.model_dump(mode="json", by_alias=True)).status_code == 200
    assert client.put("/api/v1/reference/travel-matrix", json=matrix.model_dump(mode="json")).status_code == 200
    assert client.put("/api/v1/days/2026-10-26", json=day.model_dump(mode="json")).status_code == 200

    res = client.post("/api/v1/days/2026-10-26/plan")
    assert res.status_code == 200
    plan = Plan.model_validate(res.json())

    # Validate all H1-H9 constraints
    violations = PlanValidator.validate(
        plan=plan,
        staff_by_id={s.staff_id: s for s in ref.staff},
        absent_staff_ids=set(),
        service_centers_by_id={"SC-01": sc1},
        work_types_by_code={w.code.value: w for w in ref.work_types},
        orders_by_id={o.order_id: o for o in orders},
        matrix=TravelMatrixIndex(matrix),
        day_tz=TZ,
    )
    assert violations == []

    r1 = next(r for r in plan.routes if r.staff_id == "ST-001")
    r2 = next(r for r in plan.routes if r.staff_id == "ST-002")

    # ST-001 must serve both height orders and perform RESTOCK + BREAK
    visit_ids_1 = [s.order_id for s in r1.stops if s.type == StopType.VISIT]
    assert set(visit_ids_1) == {"ORD-20261026-0001", "ORD-20261026-0002"}
    assert any(s.type == StopType.RESTOCK for s in r1.stops)
    assert sum(1 for s in r1.stops if s.type == StopType.BREAK) == 1
    # ST-002 unused -> empty stops
    assert r2.stops == []

    # ORD-0003 must be unassigned with NO_QUALIFIED_STAFF
    assert len(plan.unassigned) == 1
    assert plan.unassigned[0].order_id == "ORD-20261026-0003"
    assert plan.unassigned[0].reason_code.value == "NO_QUALIFIED_STAFF"


def test_workload_balancing_and_scale(client):
    """Tests 40 staff + 120 orders balancing (utilization_cv) and solver speed."""
    ref, matrix, day_input, _ = build_demo_dataset(num_orders=120, seed=7)
    assert client.put("/api/v1/reference", json=ref.model_dump(mode="json", by_alias=True)).status_code == 200
    assert client.put("/api/v1/reference/travel-matrix", json=matrix.model_dump(mode="json")).status_code == 200
    assert client.put("/api/v1/days/2026-10-26", json=day_input.model_dump(mode="json")).status_code == 200

    res = client.post("/api/v1/days/2026-10-26/plan", json={"time_limit_sec": 30})
    assert res.status_code == 200
    plan = Plan.model_validate(res.json())

    assert plan.computation_ms < 25000
    assert plan.summary is not None
    assert plan.summary.visits_planned >= 100
    assert plan.summary.pgp_orders == 3
    assert plan.summary.utilization_cv < 0.45

    violations = PlanValidator.validate(
        plan=plan,
        staff_by_id={s.staff_id: s for s in ref.staff},
        absent_staff_ids={"ST-017"},
        service_centers_by_id={sc.service_center_id: sc for sc in ref.service_centers},
        work_types_by_code={w.code.value: w for w in ref.work_types},
        orders_by_id={o.order_id: o for o in day_input.orders},
        matrix=TravelMatrixIndex(matrix),
        day_tz=TZ,
    )
    assert violations == []


def test_workload_rebalancing_is_separated_by_profile(monkeypatch):
    """INSTALL and LTP3 workloads must never be balanced against each other."""
    from app.optimizer.vrptw_solver import VrptwSolver

    ref, _, _, _ = build_demo_dataset(num_orders=20, seed=19)
    captured: list[tuple[str, ...]] = []

    def capture_group(cls, sched_staff, **kwargs):
        profile_key = tuple(sorted(p.value for p in sched_staff[0].profiles))
        assert all(tuple(sorted(p.value for p in st.profiles)) == profile_key for st in sched_staff)
        captured.append(profile_key)

    monkeypatch.setattr(VrptwSolver, "_rebalance_workload_group", classmethod(capture_group))
    VrptwSolver._rebalance_workload(sched_staff=ref.staff)

    assert ("INSTALL",) in captured
    assert ("LTP3",) in captured
    assert all(not ({"INSTALL", "LTP3"} <= set(group)) for group in captured)


def test_unassigned_reason_reports_no_equipment_even_after_restock():
    """The diagnostic must report NO_EQUIPMENT when no qualified worker can ever supply it."""
    from app.optimizer.vrptw_solver import VrptwSolver

    ref, _, day_input, _ = build_demo_dataset(num_orders=12, seed=31)
    work_types = {work_type.code.value: work_type for work_type in ref.work_types}
    order = next(
        item for item in day_input.orders
        if item.work_type_code.value == "REPAIR" and item.required_equipment.ONT > 0
    )
    qualified = next(
        staff for staff in ref.staff
        if staff.profiles and any(profile in work_types[order.work_type_code.value].profiles for profile in staff.profiles)
        and order.technology in staff.technologies
    )
    no_equipment_staff = qualified.model_copy(
        update={"equipment_capacity": Equipment(ONT=0, ROUTER=0, STB=0)}
    )

    result = VrptwSolver._diagnose_unassigned(
        order=order,
        sched_staff=[no_equipment_staff],
        work_types=work_types,
        routes_by_staff={},
        day_date=day_input.date,
        day_tz=TZ,
        model_time=day_input.now,
    )

    assert result.reason_code == UnassignedReasonCode.NO_EQUIPMENT
