from __future__ import annotations

from datetime import datetime, tzinfo

from app.schemas.day import Order
from app.schemas.plan import PgpAction, PgpGroup
from app.schemas.reference import AccessNode, WorkType
from app.services.time_utils import norm_dt

PGP_MIN_ORDERS = 3
PGP_WINDOW_SEC = 3600  # 60 minutes


class PgpService:
    """Detects Suspected Group Problems (ПГП) by access node within a 60-minute window."""

    @staticmethod
    def detect_groups(
        orders: list[Order],
        cancelled_order_ids: set[str],
        started_order_ids: set[str],
        work_types: dict[str, WorkType],
        access_nodes: dict[str, AccessNode],
        existing_groups: list[PgpGroup],
        as_of: datetime,
        day_tz: tzinfo,
        date_str: str,
    ) -> tuple[list[PgpGroup], list[PgpGroup]]:
        """
        Returns (all_pgp_groups, newly_created_groups).
        - Already-started visits stay in routes and are excluded from PGP groups.
        - If an existing group gets additional orders on the same access_node_id,
          its group_id and detected_at are preserved.
        """
        existing_by_node: dict[str, PgpGroup] = {g.access_node_id: g for g in existing_groups}
        candidates_by_node: dict[str, list[Order]] = {}

        for order in orders:
            if order.order_id in cancelled_order_ids:
                continue
            # Started visits still count when detecting a 3-in-60-minute incident,
            # but are removed from the group payload below and remain in their route.
            wt = work_types.get(order.work_type_code.value)
            if wt is None or not wt.pgp_relevant:
                continue
            candidates_by_node.setdefault(order.access_node_id, []).append(order)

        result_groups: list[PgpGroup] = []
        newly_created: list[PgpGroup] = []
        next_idx = len(existing_groups) + 1
        compact_date = date_str.replace("-", "")

        # Keep existing groups whose orders (non-cancelled, non-started) remain,
        # or expand them with newly arrived orders on the same node.
        processed_nodes: set[str] = set()

        for node_id in sorted(set(existing_by_node.keys()) | set(candidates_by_node.keys())):
            if node_id in processed_nodes:
                continue
            processed_nodes.add(node_id)

            existing = existing_by_node.get(node_id)
            node_orders = sorted(
                candidates_by_node.get(node_id, []),
                key=lambda o: (norm_dt(o.registered_at, day_tz), o.order_id),
            )

            # Find incident members using ALL orders, including visits already started.
            # The threshold is evaluated on the full incident; started visits are excluded
            # only from the output group so the validator keeps them in the route.
            qualifying_ids: set[str] = set()
            if existing is not None:
                valid_node_ids = {o.order_id for o in node_orders}
                for oid in existing.order_ids:
                    if oid in valid_node_ids:
                        qualifying_ids.add(oid)

            n = len(node_orders)
            for i in range(n):
                t_i = norm_dt(node_orders[i].registered_at, day_tz)
                window_orders = [node_orders[i]]
                for j in range(i + 1, n):
                    t_j = norm_dt(node_orders[j].registered_at, day_tz)
                    if (t_j - t_i).total_seconds() <= PGP_WINDOW_SEC:
                        window_orders.append(node_orders[j])
                    else:
                        break
                if len(window_orders) >= PGP_MIN_ORDERS:
                    for wo in window_orders:
                        qualifying_ids.add(wo.order_id)

            # Also if existing group exists, attach any later pgp_relevant order on same node within 60 min of any member
            if existing is not None and qualifying_ids:
                member_times = [
                    norm_dt(o.registered_at, day_tz) for o in node_orders if o.order_id in qualifying_ids
                ]
                for o in node_orders:
                    if o.order_id not in qualifying_ids and member_times:
                        ot = norm_dt(o.registered_at, day_tz)
                        if any(abs((ot - mt).total_seconds()) <= PGP_WINDOW_SEC for mt in member_times):
                            qualifying_ids.add(o.order_id)

            ordered_ids = [
                o.order_id for o in node_orders
                if o.order_id in qualifying_ids and o.order_id not in started_order_ids
            ]
            if len(ordered_ids) < 2:
                # Spec requires minItems=2 in PgpGroup
                continue
            if existing is None and len(qualifying_ids) < PGP_MIN_ORDERS:
                continue

            member_dts = [norm_dt(o.registered_at, day_tz) for o in node_orders if o.order_id in qualifying_ids]
            span_min = int(round((max(member_dts) - min(member_dts)).total_seconds() / 60.0))
            node_name = access_nodes[node_id].name if node_id in access_nodes else node_id
            comment = f"{len(ordered_ids)} обращения с {node_name} за {span_min} минут"

            if existing is not None:
                result_groups.append(
                    PgpGroup(
                        group_id=existing.group_id,
                        access_node_id=node_id,
                        order_ids=ordered_ids,
                        detected_at=norm_dt(existing.detected_at, day_tz),
                        action=PgpAction.TRANSFER_TO_STATION,
                        comment=comment,
                    )
                )
            else:
                grp = PgpGroup(
                    group_id=f"PGP-{compact_date}-{next_idx:02d}",
                    access_node_id=node_id,
                    order_ids=ordered_ids,
                    detected_at=norm_dt(as_of, day_tz),
                    action=PgpAction.TRANSFER_TO_STATION,
                    comment=comment,
                )
                next_idx += 1
                result_groups.append(grp)
                newly_created.append(grp)

        return result_groups, newly_created
