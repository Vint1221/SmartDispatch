from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

from app.demo_data import TZ_EKB, build_demo_dataset
from app.routing.matrix import TravelMatrixIndex
from app.schemas.plan import Plan, RouteStatus, StopType
from app.services.validation_service import PlanValidator


def test_alembic_upgrade_head(tmp_path):
    db_file = tmp_path / "alembic_test.db"
    backend_dir = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{db_file.as_posix()}"
    res = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend_dir,
        env=env,
        capture_output=True,
        text=True,
    )
    assert res.returncode == 0, res.stderr


def test_validator_catches_h1_through_h9_violations(client):
    ref, matrix, day_input, _ = build_demo_dataset(num_orders=30, seed=99)
    assert client.put("/api/v1/reference", json=ref.model_dump(mode="json", by_alias=True)).status_code == 200
    assert client.put("/api/v1/reference/travel-matrix", json=matrix.model_dump(mode="json")).status_code == 200
    assert client.put("/api/v1/days/2026-10-26", json=day_input.model_dump(mode="json")).status_code == 200

    plan = Plan.model_validate(client.post("/api/v1/days/2026-10-26/plan", json={"time_limit_sec": 15}).json())
    staff_map = {s.staff_id: s for s in ref.staff}
    sc_map = {sc.service_center_id: sc for sc in ref.service_centers}
    wt_map = {w.code.value: w for w in ref.work_types}
    ord_map = {o.order_id: o for o in day_input.orders}
    tm = TravelMatrixIndex(matrix)

    # Baseline clean
    assert (
        PlanValidator.validate(
            plan=plan,
            staff_by_id=staff_map,
            absent_staff_ids={"ST-017"},
            service_centers_by_id=sc_map,
            work_types_by_code=wt_map,
            orders_by_id=ord_map,
            matrix=tm,
            day_tz=TZ_EKB,
        )
        == []
    )

    # Corrupt H9 by dropping an unassigned or visited order
    corrupt = plan.model_copy(deep=True)
    if corrupt.unassigned:
        corrupt.unassigned.pop()
    else:
        for r in corrupt.routes:
            v_idx = next((i for i, s in enumerate(r.stops) if s.type == StopType.VISIT), None)
            if v_idx is not None:
                r.stops.pop(v_idx)
                break
    errs = PlanValidator.validate(
        plan=corrupt,
        staff_by_id=staff_map,
        absent_staff_ids={"ST-017"},
        service_centers_by_id=sc_map,
        work_types_by_code=wt_map,
        orders_by_id=ord_map,
        matrix=tm,
        day_tz=TZ_EKB,
    )
    assert any("H9" in e for e in errs)


def test_temporary_staff_unavailability_resume(client):
    ref, matrix, day_input, _ = build_demo_dataset(num_orders=45, seed=21)
    assert client.put("/api/v1/reference", json=ref.model_dump(mode="json", by_alias=True)).status_code == 200
    assert client.put("/api/v1/reference/travel-matrix", json=matrix.model_dump(mode="json")).status_code == 200
    assert client.put("/api/v1/days/2026-10-26", json=day_input.model_dump(mode="json")).status_code == 200

    plan_v1 = Plan.model_validate(client.post("/api/v1/days/2026-10-26/plan", json={"time_limit_sec": 15}).json())
    busy = next(r for r in plan_v1.routes if sum(1 for s in r.stops if s.type == StopType.VISIT) >= 2)

    ev = {
        "event_id": "EV-TEMP-UNAVAIL",
        "type": "STAFF_UNAVAILABLE",
        "timestamp": "2026-10-26T10:00:00+05:00",
        "staff_id": busy.staff_id,
        "until": "2026-10-26T12:00:00+05:00",
        "reason": "OTHER",
    }
    res = client.post("/api/v1/days/2026-10-26/events", json=ev)
    assert res.status_code == 200
    plan_v2 = Plan.model_validate(client.get("/api/v1/days/2026-10-26/plan").json())
    r_after = next(r for r in plan_v2.routes if r.staff_id == busy.staff_id)
    assert r_after.status == RouteStatus.UNAVAILABLE
    assert r_after.unavailable_until == datetime(2026, 10, 26, 12, 0, tzinfo=TZ_EKB)
    # No stop may start inside [10:00, 12:00)
    for s in r_after.stops:
        assert not (
            datetime(2026, 10, 26, 10, 0, tzinfo=TZ_EKB)
            <= s.start
            < datetime(2026, 10, 26, 12, 0, tzinfo=TZ_EKB)
        )
