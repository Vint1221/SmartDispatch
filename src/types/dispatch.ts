export interface Equipment {
  ONT: number;
  ROUTER: number;
  STB: number;
}

export interface Stop {
  seq: number;
  type: 'DEPOT_START' | 'VISIT' | 'BREAK' | 'RESTOCK' | 'DEPOT_END';
  location_id: string;
  order_id: string | null;
  arrival: string;
  start: string;
  end: string;
  travel_sec?: number;
  distance_m?: number;
  status?: 'PLANNED' | 'IN_PROGRESS' | 'DONE';
  equipment_after?: Equipment;
  explanation?: string;
}

export interface RouteTotals {
  visits: number;
  travel_sec: number;
  distance_m: number;
  work_min: number;
  utilization: number;
}

export interface Route {
  staff_id: string;
  service_center_id: string;
  status: 'ACTIVE' | 'UNAVAILABLE';
  unavailable_from?: string | null;
  unavailable_until?: string | null;
  stops: Stop[];
  totals?: RouteTotals;
}

export interface UnassignedOrder {
  order_id: string;
  reason_code: string;
  reason_text: string;
  suggested_action: string;
  proposed_slot?: { start: string; end: string } | null;
  since?: string | null;
}

export interface PgpGroup {
  group_id: string;
  access_node_id: string;
  order_ids: string[];
  detected_at: string;
  action: string;
  comment?: string;
}

export interface CancelledOrder {
  order_id: string;
  cancelled_at: string;
  event_id?: string | null;
}

export interface AlertItem {
  alert_id: string;
  created_at: string;
  type: 'LATE_RISK' | 'PGP_DETECTED' | 'UNASSIGNED';
  status: 'ACTIVE' | 'RESOLVED';
  resolved_at?: string | null;
  order_id?: string | null;
  group_id?: string | null;
  staff_id?: string | null;
  forecast_start?: string | null;
  lateness_min?: number | null;
  suggested_action: string;
  suggested_staff_id?: string | null;
  proposed_slot?: { start: string; end: string } | null;
  applied: boolean;
  message: string;
}

export interface PlanSummary {
  orders_total: number;
  visits_planned: number;
  unassigned: number;
  pgp_orders: number;
  cancelled: number;
  travel_sec_total: number;
  utilization_cv: number;
}

export interface Plan {
  date: string;
  plan_version: number;
  based_on_event_id: string | null;
  as_of: string;
  computation_ms?: number;
  routes: Route[];
  unassigned: UnassignedOrder[];
  pgp_groups: PgpGroup[];
  cancelled: CancelledOrder[];
  alerts: AlertItem[];
  summary?: PlanSummary;
}

export interface ServiceCenter {
  service_center_id: string;
  name: string;
  address: string;
  lat: number;
  lon: number;
  opening_hours: { open: string; close: string };
  restock_duration_min: number;
}

export interface StaffMember {
  staff_id: string;
  display_name?: string;
  service_center_id: string;
  profiles: ('INSTALL' | 'LTP3')[];
  technologies: string[];
  height_permit: boolean;
  shift: {
    start: string;
    end: string;
    break_duration_min: number;
    break_window: { from: string; to: string };
  };
}

export interface OrderRecord {
  order_id: string;
  work_type_code: string;
  technology: string;
  building_id: string;
  address: string;
  lat: number;
  lon: number;
  building_type?: string;
  requires_height: boolean;
  access_node_id: string;
  slot: { start: string; end: string };
  latest_start: string;
  deadline?: string;
  required_equipment?: Equipment;
  is_repeat: boolean;
  target_staff_id?: string | null;
}

export interface WorkTypeItem {
  code: string;
  name: string;
  profiles: ('INSTALL' | 'LTP3')[];
  duration_min: number;
  max_start_delay_min?: number | null;
  deadline_kind?: 'SLOT' | 'HOURS' | 'WORKING_DAYS';
  deadline_value?: number | null;
  repeat_deadline_value?: number | null;
  pgp_relevant: boolean;
}

export interface BuildingItem {
  building_id: string;
  address: string;
  lat: number;
  lon: number;
  building_type: string;
  overhead_line: boolean;
  zone_service_center_id?: string | null;
}

export interface AccessNodeItem {
  access_node_id: string;
  technology: string;
  node_type: string;
  buildings: BuildingItem[];
}

export interface DayContextResponse {
  plan: Plan;
  service_centers: ServiceCenter[];
  staff: StaffMember[];
  orders: Record<string, OrderRecord>;
  events: Array<{
    event_id: string;
    plan_version: number;
    as_of: string;
    message?: string;
    changed_staff_ids: string[];
  }>;
  work_types?: WorkTypeItem[];
  access_nodes?: AccessNodeItem[];
}
