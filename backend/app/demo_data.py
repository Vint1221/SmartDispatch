from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from app.schemas.common import BuildingType, Equipment, Profile, Technology, TimeWindow, WorkTypeCode
from app.schemas.day import DayInput, Order
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

TZ_EKB = timezone(timedelta(hours=5))


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> int:
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return int(round(2 * r * math.atan2(math.sqrt(a), math.sqrt(1 - a))))


def build_demo_dataset(
    date_str: str = "2026-10-26",
    num_orders: int = 120,
    seed: int = 42,
) -> tuple[ReferenceData, TravelMatrix, DayInput, list[dict]]:
    """
    DEMO synthetic dataset matching organizer scale and Yekaterinburg coordinates.
    Clearly marked as DEMO for local testing and UI preview.
    """
    rng = random.Random(seed)
    day_date = datetime.fromisoformat(f"{date_str}T00:00:00+05:00").date()

    service_centers = [
        ServiceCenter(
            service_center_id="SC-01",
            name="СЦ «Север»",
            address="г. Екатеринбург, ул. Победы, 30",
            lat=56.8941,
            lon=60.6105,
            opening_hours=OpeningHours(open="08:00", close="21:00"),
            restock_duration_min=15,
        ),
        ServiceCenter(
            service_center_id="SC-02",
            name="СЦ «Центр»",
            address="г. Екатеринбург, ул. Малышева, 51",
            lat=56.8355,
            lon=60.6130,
            opening_hours=OpeningHours(open="08:00", close="21:00"),
            restock_duration_min=15,
        ),
        ServiceCenter(
            service_center_id="SC-03",
            name="СЦ «Юг»",
            address="г. Екатеринбург, ул. Щорса, 74",
            lat=56.8090,
            lon=60.6080,
            opening_hours=OpeningHours(open="08:00", close="21:00"),
            restock_duration_min=15,
        ),
        ServiceCenter(
            service_center_id="SC-04",
            name="СЦ «Запад»",
            address="г. Екатеринбург, ул. Крауля, 44",
            lat=56.8382,
            lon=60.5565,
            opening_hours=OpeningHours(open="08:00", close="21:00"),
            restock_duration_min=15,
        ),
        ServiceCenter(
            service_center_id="SC-05",
            name="СЦ «Восток»",
            address="г. Екатеринбург, ул. Малышева, 128",
            lat=56.8425,
            lon=60.6690,
            opening_hours=OpeningHours(open="08:00", close="21:00"),
            restock_duration_min=15,
        ),
    ]

    # 40 staff: 28 LTP3 + 12 INSTALL
    staff_list: list[Staff] = []
    for i in range(1, 41):
        sc = service_centers[(i - 1) % len(service_centers)]
        is_install = i > 28
        early_shift = (i % 3 != 0)
        shift = (
            Shift(
                start="09:00",
                end="18:00",
                break_duration_min=60,
                break_window=BreakWindow(from_="12:00", to="15:00"),
            )
            if early_shift
            else Shift(
                start="12:00",
                end="21:00",
                break_duration_min=60,
                break_window=BreakWindow(from_="15:00", to="18:00"),
            )
        )
        techs = [Technology.PON, Technology.FTTB, Technology.XDSL]
        if i % 4 == 0:
            techs.append(Technology.DOCSIS)
        staff_list.append(
            Staff(
                staff_id=f"ST-{i:03d}",
                display_name=f"{'Инсталлятор' if is_install else 'Монтажник 3ЛТП'} {i:03d}",
                service_center_id=sc.service_center_id,
                profiles=[Profile.INSTALL] if is_install else [Profile.LTP3],
                technologies=techs,
                height_permit=(i % 3 == 0 or i <= 6 or i >= 36),
                shift=shift,
                equipment_start=Equipment(ONT=3, ROUTER=4, STB=2),
                equipment_capacity=Equipment(ONT=6, ROUTER=6, STB=4),
                experience_years=round(1.5 + (i % 8) * 0.7, 1),
            )
        )

    work_types = [
        WorkType(
            code=WorkTypeCode.INST_PON_MKD,
            name="Инсталляция ШПД/IPTV, МКД, PON",
            profiles=[Profile.INSTALL],
            duration_min=90,
            max_start_delay_min=10,
            deadline_kind=DeadlineKind.WORKING_DAYS,
            deadline_value=3,
            repeat_deadline_value=None,
            pgp_relevant=False,
        ),
        WorkType(
            code=WorkTypeCode.INST_FTTB_MKD,
            name="Инсталляция ШПД/IPTV, МКД, FTTB",
            profiles=[Profile.INSTALL],
            duration_min=60,
            max_start_delay_min=10,
            deadline_kind=DeadlineKind.WORKING_DAYS,
            deadline_value=3,
            repeat_deadline_value=None,
            pgp_relevant=False,
        ),
        WorkType(
            code=WorkTypeCode.INST_PRIVATE_VLS,
            name="Инсталляция, частный сектор, с ВЛС",
            profiles=[Profile.INSTALL],
            duration_min=180,
            max_start_delay_min=10,
            deadline_kind=DeadlineKind.WORKING_DAYS,
            deadline_value=5,
            repeat_deadline_value=None,
            pgp_relevant=False,
        ),
        WorkType(
            code=WorkTypeCode.ADD_SERVICE,
            name="Доподключение услуги (IPTV, Wi-Fi-роутер)",
            profiles=[Profile.INSTALL],
            duration_min=40,
            max_start_delay_min=10,
            deadline_kind=DeadlineKind.SLOT,
            deadline_value=None,
            repeat_deadline_value=None,
            pgp_relevant=False,
        ),
        WorkType(
            code=WorkTypeCode.SURVEY_PRIVATE,
            name="Обследование (частный сектор)",
            profiles=[Profile.INSTALL, Profile.LTP3],
            duration_min=45,
            max_start_delay_min=None,
            deadline_kind=DeadlineKind.WORKING_DAYS,
            deadline_value=2,
            repeat_deadline_value=None,
            pgp_relevant=False,
        ),
        WorkType(
            code=WorkTypeCode.REPAIR,
            name="Устранение неисправности (обращение абонента)",
            profiles=[Profile.LTP3],
            duration_min=60,
            max_start_delay_min=None,
            deadline_kind=DeadlineKind.HOURS,
            deadline_value=24,
            repeat_deadline_value=12,
            pgp_relevant=True,
        ),
        WorkType(
            code=WorkTypeCode.DEGRADATION,
            name="Устранение деградации, выявленной системой мониторинга качества",
            profiles=[Profile.LTP3],
            duration_min=45,
            max_start_delay_min=None,
            deadline_kind=DeadlineKind.HOURS,
            deadline_value=48,
            repeat_deadline_value=None,
            pgp_relevant=True,
        ),
        WorkType(
            code=WorkTypeCode.DISMANTLE,
            name="Демонтаж АО",
            profiles=[Profile.LTP3],
            duration_min=30,
            max_start_delay_min=None,
            deadline_kind=DeadlineKind.WORKING_DAYS,
            deadline_value=5,
            repeat_deadline_value=None,
            pgp_relevant=False,
        ),
    ]
    wt_map = {w.code: w for w in work_types}

    # 15 Access Nodes, 60 Buildings around Yekaterinburg
    access_nodes: list[AccessNode] = []
    buildings: list[Building] = []
    node_techs = [
        (NodeType.OLT, Technology.PON),
        (NodeType.SWITCH, Technology.FTTB),
        (NodeType.DSLAM, Technology.XDSL),
        (NodeType.CMTS, Technology.DOCSIS),
    ]
    b_counter = 1
    for n_idx in range(1, 16):
        sc = service_centers[(n_idx - 1) % len(service_centers)]
        nt, tech = node_techs[(n_idx - 1) % len(node_techs)]
        n_lat = sc.lat + rng.uniform(-0.02, 0.02)
        n_lon = sc.lon + rng.uniform(-0.03, 0.03)
        node_buildings: list[Building] = []
        for _ in range(4):
            b_lat = n_lat + rng.uniform(-0.008, 0.008)
            b_lon = n_lon + rng.uniform(-0.012, 0.012)
            is_priv = (b_counter % 6 == 0)
            b = Building(
                building_id=f"B-{b_counter:05d}",
                address=f"г. Екатеринбург, ул. Демо-{n_idx}, д. {b_counter}",
                lat=round(b_lat, 5),
                lon=round(b_lon, 5),
                building_type=BuildingType.PRIVATE if is_priv else BuildingType.MKD,
                overhead_line=is_priv,
                zone_service_center_id=sc.service_center_id,
            )
            node_buildings.append(b)
            buildings.append(b)
            b_counter += 1
        access_nodes.append(
            AccessNode(
                access_node_id=f"AN-{n_idx:04d}",
                node_type=nt,
                technology=tech,
                name=f"{nt.value} Узел-{n_idx}",
                address=f"г. Екатеринбург, узел {n_idx}",
                lat=round(n_lat, 5),
                lon=round(n_lon, 5),
                buildings=node_buildings,
            )
        )

    ref = ReferenceData(
        service_centers=service_centers,
        staff=staff_list,
        access_nodes=access_nodes,
        work_types=work_types,
    )

    # Travel matrix covering all SC + Buildings (slightly asymmetric road network)
    points_meta: list[tuple[str, float, float]] = [
        (sc.service_center_id, sc.lat, sc.lon) for sc in service_centers
    ] + [(b.building_id, b.lat, b.lon) for b in buildings]
    points = [p[0] for p in points_meta]
    n_pts = len(points)
    durations_sec = [[0] * n_pts for _ in range(n_pts)]
    distances_m = [[0] * n_pts for _ in range(n_pts)]
    for i in range(n_pts):
        for j in range(n_pts):
            if i == j:
                continue
            d_air = _haversine_m(points_meta[i][1], points_meta[i][2], points_meta[j][1], points_meta[j][2])
            dist = int(round(d_air * 1.32)) + 150
            asym = 1.0 + (0.06 if (i + j) % 2 == 0 else -0.04)
            dur = max(120, int(round((dist / 8.5) * asym)) + 120)
            distances_m[i][j] = dist
            durations_sec[i][j] = dur

    matrix = TravelMatrix(
        matrix_id=f"demo-ekb-{date_str}",
        points=points,
        durations_sec=durations_sec,
        distances_m=distances_m,
    )

    # Generate orders including 1 PGP cluster on AN-0001
    now_dt = datetime(day_date.year, day_date.month, day_date.day, 8, 30, 0, tzinfo=TZ_EKB)
    orders: list[Order] = []
    compact = date_str.replace("-", "")

    for k in range(1, num_orders + 1):
        if k <= 3:
            # Intentional DEMO PGP cluster on AN-0001
            an = access_nodes[0]
            b = an.buildings[(k - 1) % len(an.buildings)]
            wt = wt_map[WorkTypeCode.REPAIR]
            reg_at = now_dt - timedelta(minutes=40 - k * 10)
            slot_hour = 10
        else:
            an = access_nodes[(k - 1) % len(access_nodes)]
            b = rng.choice(an.buildings)
            if k % 4 == 0:
                wt_code = WorkTypeCode.INST_PON_MKD if an.technology == Technology.PON else WorkTypeCode.INST_FTTB_MKD
            elif k % 7 == 0:
                wt_code = WorkTypeCode.ADD_SERVICE
            elif k % 9 == 0:
                wt_code = WorkTypeCode.DEGRADATION
            else:
                wt_code = WorkTypeCode.REPAIR
            wt = wt_map[wt_code]
            node_rank = (k - 1) // len(access_nodes)
            reg_at = now_dt - timedelta(minutes=90 * (node_rank + 1))
            slot_hour = rng.choice([9, 10, 11, 13, 14, 15, 16, 17])

        slot_start = datetime(day_date.year, day_date.month, day_date.day, slot_hour, 0, 0, tzinfo=TZ_EKB)
        slot_end = slot_start + timedelta(hours=2)
        if wt.max_start_delay_min is not None:
            latest_start = min(slot_end, slot_start + timedelta(minutes=wt.max_start_delay_min))
        else:
            latest_start = slot_end
        deadline = max(latest_start + timedelta(minutes=wt.duration_min), reg_at + timedelta(hours=24))
        req_eq = Equipment(
            ONT=1 if (an.technology == Technology.PON and wt.code in (WorkTypeCode.INST_PON_MKD, WorkTypeCode.REPAIR)) else 0,
            ROUTER=1 if wt.code in (WorkTypeCode.INST_PON_MKD, WorkTypeCode.INST_FTTB_MKD, WorkTypeCode.ADD_SERVICE) else 0,
            STB=1 if (k % 5 == 0 and wt.code == WorkTypeCode.INST_PON_MKD) else 0,
        )
        orders.append(
            Order(
                order_id=f"ORD-{compact}-{k:04d}",
                work_type_code=wt.code,
                technology=an.technology,
                building_id=b.building_id,
                address=b.address,
                lat=b.lat,
                lon=b.lon,
                building_type=b.building_type,
                requires_height=b.overhead_line,
                access_node_id=an.access_node_id,
                registered_at=reg_at,
                slot=TimeWindow(start=slot_start, end=slot_end),
                latest_start=latest_start,
                deadline=deadline,
                required_equipment=req_eq,
                is_repeat=(k % 11 == 0),
                previous_order_id=None,
            )
        )

    day_input = DayInput(
        date=day_date,
        now=now_dt,
        orders=orders,
        absent_staff_ids=["ST-017"],
    )

    demo_events = [
        {
            "event_id": f"EV-{compact}-0001",
            "type": "NEW_ORDER",
            "timestamp": f"{date_str}T10:05:00+05:00",
            "order": {
                "order_id": f"ORD-{compact}-9001",
                "work_type_code": "REPAIR",
                "technology": access_nodes[1].technology.value,
                "building_id": buildings[4].building_id,
                "address": buildings[4].address,
                "lat": buildings[4].lat,
                "lon": buildings[4].lon,
                "building_type": buildings[4].building_type.value,
                "requires_height": buildings[4].overhead_line,
                "access_node_id": access_nodes[1].access_node_id,
                "registered_at": f"{date_str}T10:05:00+05:00",
                "slot": {"start": f"{date_str}T13:00:00+05:00", "end": f"{date_str}T15:00:00+05:00"},
                "latest_start": f"{date_str}T15:00:00+05:00",
                "deadline": f"{date_str}T22:05:00+05:00",
                "required_equipment": {"ONT": 0, "ROUTER": 1, "STB": 0},
                "is_repeat": True,
                "previous_order_id": None,
            },
        },
        {
            "event_id": f"EV-{compact}-0002",
            "type": "STAFF_UNAVAILABLE",
            "timestamp": f"{date_str}T11:10:00+05:00",
            "staff_id": "ST-001",
            "until": None,
            "reason": "VEHICLE_BREAKDOWN",
        },
        {
            "event_id": f"EV-{compact}-0003",
            "type": "TIME_TICK",
            "timestamp": f"{date_str}T11:30:00+05:00",
        },
    ]

    return ref, matrix, day_input, demo_events
