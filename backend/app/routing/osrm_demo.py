from __future__ import annotations

from typing import Any

import httpx

from app.schemas.reference import ReferenceData, TravelMatrix

OSRM_TABLE_URL = "https://router.project-osrm.org/table/v1/driving"


def build_osrm_demo_matrix(reference: ReferenceData, fallback: TravelMatrix) -> TravelMatrix:
    """Build a real-road DEMO duration/distance matrix from the public OSRM demo server.

    This is only for local DEMO. The official evaluator matrix must always be used as uploaded.
    The public OSRM demo server is best-effort and rate-limited; this function makes one request.
    """
    coordinates_by_id: dict[str, tuple[float, float]] = {}
    for center in reference.service_centers:
        coordinates_by_id[center.service_center_id] = (center.lon, center.lat)
    for node in reference.access_nodes:
        for building in node.buildings:
            coordinates_by_id[building.building_id] = (building.lon, building.lat)

    missing = [point_id for point_id in fallback.points if point_id not in coordinates_by_id]
    if missing:
        raise ValueError(f"OSRM DEMO matrix has unknown points: {', '.join(missing[:5])}")

    coordinate_path = ";".join(
        f"{coordinates_by_id[point_id][0]:.6f},{coordinates_by_id[point_id][1]:.6f}"
        for point_id in fallback.points
    )
    response = httpx.get(
        f"{OSRM_TABLE_URL}/{coordinate_path}",
        params={"annotations": "duration,distance"},
        headers={"User-Agent": "SmartDispatch-Demo/1.0 (educational local project)"},
        timeout=httpx.Timeout(35.0, connect=8.0),
    )
    response.raise_for_status()
    payload: dict[str, Any] = response.json()
    if payload.get("code") != "Ok":
        raise RuntimeError(f"OSRM Table returned {payload.get('code')}: {payload.get('message', '')}")

    raw_durations = payload.get("durations")
    raw_distances = payload.get("distances")
    n = len(fallback.points)
    if (
        not isinstance(raw_durations, list)
        or not isinstance(raw_distances, list)
        or len(raw_durations) != n
        or len(raw_distances) != n
    ):
        raise RuntimeError("OSRM Table returned a matrix with unexpected dimensions")

    durations: list[list[int]] = []
    distances: list[list[int]] = []
    for i in range(n):
        if len(raw_durations[i]) != n or len(raw_distances[i]) != n:
            raise RuntimeError("OSRM Table returned a non-square matrix")
        duration_row: list[int] = []
        distance_row: list[int] = []
        for j in range(n):
            # Disconnected / unsnappable points retain the DEMO fallback value only for that pair.
            duration = raw_durations[i][j]
            distance = raw_distances[i][j]
            if i == j:
                duration_row.append(0)
                distance_row.append(0)
            else:
                duration_row.append(
                    max(0, round(float(duration))) if duration is not None else fallback.durations_sec[i][j]
                )
                distance_row.append(
                    max(0, round(float(distance))) if distance is not None else fallback.distances_m[i][j]
                )
        durations.append(duration_row)
        distances.append(distance_row)

    return TravelMatrix(
        matrix_id=f"osrm-demo-{fallback.matrix_id}",
        points=fallback.points,
        durations_sec=durations,
        distances_m=distances,
        hourly_factors=fallback.hourly_factors,
    )
