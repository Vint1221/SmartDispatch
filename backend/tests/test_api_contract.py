from __future__ import annotations

from app.demo_data import build_demo_dataset
from app.schemas.reference import TravelMatrix


def test_health_endpoint(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert isinstance(body["team"], str)
    assert isinstance(body["version"], str)


def test_contract_load_build_and_error_handling(client):
    ref, matrix, day_input, _ = build_demo_dataset(num_orders=30)

    # Calling PUT /days before reference -> 409 ErrorResponse
    r_day_early = client.put(
        "/api/v1/days/2026-10-26",
        json=day_input.model_dump(mode="json"),
    )
    assert r_day_early.status_code == 409
    assert "error" in r_day_early.json()
    assert r_day_early.json()["error"]["code"] == "REFERENCE_NOT_LOADED"

    # Invalid JSON / schema error -> 400 ErrorResponse (not FastAPI's default 422)
    r_bad = client.put("/api/v1/reference", json={"service_centers": []})
    assert r_bad.status_code == 400
    err = r_bad.json()["error"]
    assert err["code"] == "BAD_REQUEST"
    assert isinstance(err["details"], list)

    # Load reference with unknown field (must be ignored per spec)
    ref_payload = ref.model_dump(mode="json", by_alias=True)
    ref_payload["extra_organizer_field"] = "ignored"
    r_ref = client.put("/api/v1/reference", json=ref_payload)
    assert r_ref.status_code == 200
    assert r_ref.json()["status"] == "loaded"
    assert r_ref.json()["counts"]["service_centers"] == 5
    assert r_ref.json()["counts"]["staff"] == 40
    assert r_ref.json()["counts"]["work_types"] == 8

    # Load travel matrix
    r_mat = client.put("/api/v1/reference/travel-matrix", json=matrix.model_dump(mode="json"))
    assert r_mat.status_code == 200
    assert r_mat.json()["counts"]["points"] == len(matrix.points)

    # Plan before day loaded -> 404
    r_plan_404 = client.get("/api/v1/days/2026-10-26/plan")
    assert r_plan_404.status_code == 404
    assert "error" in r_plan_404.json()

    # Load day with unknown 'fact' field on order (must be ignored)
    day_payload = day_input.model_dump(mode="json")
    day_payload["orders"][0]["fact"] = {"outcome": "COMPLETED", "actual_duration_min": 55}
    r_day = client.put("/api/v1/days/2026-10-26", json=day_payload)
    assert r_day.status_code == 200
    assert r_day.json()["counts"]["orders"] == 30

    # Build plan (empty body allowed)
    r_build = client.post("/api/v1/days/2026-10-26/plan")
    assert r_build.status_code == 200
    plan = r_build.json()
    assert plan["plan_version"] == 1
    assert plan["based_on_event_id"] is None
    assert plan["as_of"].endswith("+05:00")
    assert len(plan["routes"]) == 39  # 40 minus absent ST-017

    # Rebuild before first event is allowed
    r_rebuild = client.post("/api/v1/days/2026-10-26/plan", json={"time_limit_sec": 30})
    assert r_rebuild.status_code == 200
    assert r_rebuild.json()["plan_version"] == 1

    # Invalid event does not mutate state
    r_bad_ev = client.post(
        "/api/v1/days/2026-10-26/events",
        json={
            "event_id": "EV-BAD-1",
            "type": "ORDER_CANCELLED",
            "timestamp": "2026-10-26T09:30:00+05:00",
            "order_id": "ORD-20261026-9999",
            "reason": "NOT_CONFIRMED",
        },
    )
    assert r_bad_ev.status_code == 422
    assert r_bad_ev.json()["error"]["code"] == "UNKNOWN_ORDER"
    assert client.get("/api/v1/days/2026-10-26/plan").json()["plan_version"] == 1

    # Valid event increments plan_version; afterwards POST /plan returns 409
    r_tick = client.post(
        "/api/v1/days/2026-10-26/events",
        json={"event_id": "EV-1", "type": "TIME_TICK", "timestamp": "2026-10-26T09:15:00+05:00"},
    )
    assert r_tick.status_code == 200
    assert r_tick.json()["plan_version"] == 2
    assert client.post("/api/v1/days/2026-10-26/plan").status_code == 409

    # Repeated PUT /reference wipes day state
    assert client.put("/api/v1/reference", json=ref_payload).status_code == 200
    assert client.get("/api/v1/days/2026-10-26/plan").status_code == 404


def test_travel_matrix_must_cover_every_reference_building(client):
    ref, matrix, _, _ = build_demo_dataset(num_orders=20)
    assert client.put("/api/v1/reference", json=ref.model_dump(mode="json", by_alias=True)).status_code == 200

    # Remove one building point while keeping the matrix dimensions valid.
    building_index = next(i for i, point in enumerate(matrix.points) if point.startswith("B-"))
    keep = [i for i in range(len(matrix.points)) if i != building_index]
    incomplete = TravelMatrix(
        matrix_id="incomplete-test",
        points=[matrix.points[i] for i in keep],
        durations_sec=[[matrix.durations_sec[i][j] for j in keep] for i in keep],
        distances_m=[[matrix.distances_m[i][j] for j in keep] for i in keep],
    )
    response = client.put("/api/v1/reference/travel-matrix", json=incomplete.model_dump(mode="json"))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INCOMPLETE_TRAVEL_MATRIX"


def test_order_building_must_belong_to_selected_access_node(client):
    ref, matrix, day_input, _ = build_demo_dataset(num_orders=5, seed=23)
    assert client.put("/api/v1/reference", json=ref.model_dump(mode="json", by_alias=True)).status_code == 200
    assert client.put("/api/v1/reference/travel-matrix", json=matrix.model_dump(mode="json")).status_code == 200

    payload = day_input.model_dump(mode="json")
    # Keep a valid building and technology, but associate it with a different node.
    payload["orders"][0]["access_node_id"] = ref.access_nodes[1].access_node_id
    response = client.put("/api/v1/days/2026-10-26", json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "BUILDING_NOT_ON_ACCESS_NODE"
