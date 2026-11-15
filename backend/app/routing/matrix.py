from __future__ import annotations

import json
import zlib
from typing import Any

from app.schemas.reference import TravelMatrix


class TravelMatrixIndex:
    """Fast O(1) lookup wrapper around the organizer's TravelMatrix."""

    def __init__(self, matrix: TravelMatrix) -> None:
        self.matrix_id: str = matrix.matrix_id
        self.points: list[str] = list(matrix.points)
        self.point_to_idx: dict[str, int] = {p: i for i, p in enumerate(self.points)}
        self.durations_sec: list[list[int]] = matrix.durations_sec
        self.distances_m: list[list[int]] = matrix.distances_m
        self.hourly_factors = matrix.hourly_factors

    def has_point(self, point_id: str) -> bool:
        return point_id in self.point_to_idx

    def duration_sec(self, from_id: str, to_id: str) -> int:
        if from_id == to_id:
            return 0
        i = self.point_to_idx[from_id]
        j = self.point_to_idx[to_id]
        return self.durations_sec[i][j]

    def distance_m(self, from_id: str, to_id: str) -> int:
        if from_id == to_id:
            return 0
        i = self.point_to_idx[from_id]
        j = self.point_to_idx[to_id]
        return self.distances_m[i][j]

    def to_compressed_blob(self) -> bytes:
        raw = json.dumps(
            {
                "matrix_id": self.matrix_id,
                "points": self.points,
                "durations_sec": self.durations_sec,
                "distances_m": self.distances_m,
                "hourly_factors": [hf.model_dump() for hf in self.hourly_factors] if self.hourly_factors else None,
            },
            separators=(",", ":"),
        ).encode("utf-8")
        return zlib.compress(raw, level=3)

    @classmethod
    def from_compressed_blob(cls, blob: bytes) -> "TravelMatrixIndex":
        data: dict[str, Any] = json.loads(zlib.decompress(blob).decode("utf-8"))
        return cls(TravelMatrix.model_validate(data))
