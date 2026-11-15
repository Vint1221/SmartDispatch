import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  CircleMarker, MapContainer, Popup, Polyline, TileLayer, Tooltip, useMap,
} from 'react-leaflet';
import type { LatLngBoundsExpression, LatLngExpression } from 'leaflet';
import type { OrderRecord, Route, ServiceCenter, StaffMember } from '../types/dispatch';

interface RouteMapProps {
  routes: Route[];
  serviceCenters: ServiceCenter[];
  orders: Record<string, OrderRecord>;
  staffById: Record<string, StaffMember>;
  selectedStaffId: string | null;
  onSelectStaff: (staffId: string) => void;
  routePalette: Record<string, string>;
  onExpand: () => void;
  expanded?: boolean;
}

type GeoPoint = { id: string; lat: number; lon: number };
type RoadLine = Array<[number, number]>;
type RouteState =
  | { key: string; status: 'loading' }
  | { key: string; status: 'ready'; points: RoadLine; distanceM: number; durationSec: number }
  | { key: string; status: 'error'; message: string }
  | { key: string; status: 'empty' };
type OsrmResponse = {
  code?: string; message?: string;
  routes?: Array<{ geometry?: { coordinates?: Array<[number, number]> }; distance?: number; duration?: number }>;
};

const EKATERINBURG_CENTER: LatLngExpression = [56.8389, 60.6057];
const ROUTER_URL = 'https://router.project-osrm.org/route/v1/driving';
const LIGHT_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const routeCache = new Map<string, { points: RoadLine; distanceM: number; durationSec: number }>();
let lastOsrmRequestAt = 0;

function formatDistance(meters: number): string {
  return meters >= 1000 ? `${(meters / 1000).toFixed(1)} км` : `${Math.round(meters)} м`;
}
function fmtTime(iso: string): string {
  const match = iso.match(/T(\d{2}:\d{2})/); return match ? match[1] : iso;
}

function MapViewport({ points }: { points: GeoPoint[] }) {
  const map = useMap();
  const boundsKey = points.map((point) => `${point.lat},${point.lon}`).join('|');
  useEffect(() => {
    if (points.length >= 2) {
      const bounds: LatLngBoundsExpression = points.map((point): [number, number] => [point.lat, point.lon]);
      map.fitBounds(bounds, { padding: [32, 32], maxZoom: 14 });
    } else if (points.length === 1) map.setView([points[0].lat, points[0].lon], 13);
    else map.setView(EKATERINBURG_CENTER, 12);
  }, [map, boundsKey]);
  return null;
}

function MapResizeWatcher({ expanded }: { expanded: boolean }) {
  const map = useMap();
  useEffect(() => {
    const timer = window.setTimeout(() => map.invalidateSize({ animate: true }), expanded ? 220 : 0);
    return () => window.clearTimeout(timer);
  }, [expanded, map]);
  return null;
}

export const RouteMap: React.FC<RouteMapProps> = ({
  routes, serviceCenters, orders, staffById, selectedStaffId, onSelectStaff,
  routePalette, onExpand, expanded = false,
}) => {
  const points = useMemo<GeoPoint[]>(() => {
    const unique = new Map<string, GeoPoint>();
    for (const center of serviceCenters) unique.set(center.service_center_id, { id: center.service_center_id, lat: center.lat, lon: center.lon });
    for (const order of Object.values(orders)) unique.set(order.building_id, { id: order.building_id, lat: order.lat, lon: order.lon });
    return [...unique.values()].filter((point) => Number.isFinite(point.lat) && Number.isFinite(point.lon));
  }, [serviceCenters, orders]);
  const pointById = useMemo(() => Object.fromEntries(points.map((point) => [point.id, point])) as Record<string, GeoPoint>, [points]);
  const activeRoutes = useMemo(() => routes.filter((route) => route.stops.length > 0), [routes]);
  const selectedRoute = useMemo(() => routes.find((route) => route.staff_id === selectedStaffId) ?? activeRoutes[0] ?? null, [routes, activeRoutes, selectedStaffId]);
  const selectedRoutePoints = useMemo(() => {
    if (!selectedRoute) return [];
    const result: GeoPoint[] = [];
    for (const stop of selectedRoute.stops) {
      const point = pointById[stop.location_id];
      if (point && result[result.length - 1]?.id !== point.id) result.push(point);
    }
    return result;
  }, [selectedRoute, pointById]);
  const routeKey = useMemo(() => selectedRoutePoints.map((point) => `${point.lon.toFixed(6)},${point.lat.toFixed(6)}`).join(';'), [selectedRoutePoints]);
  const [routeState, setRouteState] = useState<RouteState>({ key: '', status: 'empty' });
  const activeRequest = useRef<AbortController | null>(null);

  useEffect(() => {
    activeRequest.current?.abort();
    if (selectedRoutePoints.length < 2) { setRouteState({ key: routeKey, status: 'empty' }); return; }
    const cached = routeCache.get(routeKey);
    if (cached) { setRouteState({ key: routeKey, status: 'ready', ...cached }); return; }
    const controller = new AbortController(); activeRequest.current = controller;
    let cancelled = false; let timer: number | undefined;
    setRouteState({ key: routeKey, status: 'loading' });
    const load = async () => {
      const waitMs = Math.max(0, 1100 - (Date.now() - lastOsrmRequestAt));
      if (waitMs > 0) await new Promise<void>((resolve) => { timer = window.setTimeout(resolve, waitMs); });
      if (cancelled) return;
      lastOsrmRequestAt = Date.now();
      const coordinates = selectedRoutePoints.map((point) => `${point.lon},${point.lat}`).join(';');
      try {
        const response = await fetch(`${ROUTER_URL}/${coordinates}?overview=full&geometries=geojson&steps=false`, { signal: controller.signal });
        if (!response.ok) throw new Error(`OSRM HTTP ${response.status}`);
        const data = await response.json() as OsrmResponse;
        const route = data.routes?.[0]; const geometry = route?.geometry?.coordinates;
        if (data.code !== 'Ok' || !geometry || geometry.length < 2) throw new Error(data.message || data.code || 'Маршрут не найден');
        const result = { points: geometry.map(([lon, lat]) => [lat, lon] as [number, number]), distanceM: route.distance ?? 0, durationSec: route.duration ?? 0 };
        routeCache.set(routeKey, result);
        if (!cancelled) setRouteState({ key: routeKey, status: 'ready', ...result });
      } catch (error) {
        if (cancelled || (error instanceof Error && error.name === 'AbortError')) return;
        if (!cancelled) setRouteState({ key: routeKey, status: 'error', message: error instanceof Error ? error.message : 'Ошибка маршрутизации' });
      }
    };
    void load();
    return () => { cancelled = true; if (timer) window.clearTimeout(timer); controller.abort(); };
  }, [routeKey, selectedRoutePoints]);

  const plannedByOrder = useMemo(() => {
    const map: Record<string, string> = {};
    for (const route of routes) for (const stop of route.stops) if (stop.order_id) map[stop.order_id] = route.staff_id;
    return map;
  }, [routes]);
  const selectedOrderIds = useMemo(() => new Set(selectedRoute?.stops.flatMap((stop) => stop.order_id ? [stop.order_id] : []) ?? []), [selectedRoute]);
  const displayed = routeState.key === routeKey ? routeState : { key: routeKey, status: 'loading' as const };

  return (
    <section className={`map-card-content ${expanded ? 'map-expanded' : ''}`}>
      <div className="panel-heading map-heading">
        <div className="panel-heading-copy"><div className="panel-title-row"><h2>Карта маршрутов · Екатеринбург</h2><span className="count-pill">{activeRoutes.length} маршрутов</span></div><p>Реальные улицы OpenStreetMap · дорожная геометрия выбранного маршрута OSRM</p></div>
        <div className="panel-heading-actions">{selectedRoute && <select className="compact-select" value={selectedRoute.staff_id} onChange={(event) => onSelectStaff(event.target.value)} aria-label="Выбрать маршрут">{routes.map((route) => <option key={route.staff_id} value={route.staff_id}>{route.staff_id} · {staffById[route.staff_id]?.display_name ?? ''}</option>)}</select>}<button className="icon-button" type="button" onClick={onExpand} title={expanded ? 'Свернуть карту' : 'Развернуть карту'}>{expanded ? '↙' : '⤢'}</button></div>
      </div>
      <div className="map-frame" data-map-theme="light" style={{ colorScheme: 'light', backgroundColor: '#e6ecef' }}>
        <MapContainer center={EKATERINBURG_CENTER} zoom={12} scrollWheelZoom className="leaflet-map" preferCanvas style={{ colorScheme: 'light', backgroundColor: '#e6ecef', filter: 'none' }}>
          <TileLayer
            key="openstreetmap-standard"
            className="map-base-tiles map-base-tiles-light"
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noreferrer">OpenStreetMap contributors</a>'
            url={LIGHT_TILES}
            maxZoom={19}
          />
          <MapViewport points={points} /><MapResizeWatcher expanded={expanded} />
          {displayed.status === 'ready' && <Polyline positions={displayed.points} pathOptions={{ color: routePalette[selectedRoute?.staff_id ?? ''] ?? '#7200e8', weight: expanded ? 7 : 6, opacity: 0.96, lineCap: 'round', lineJoin: 'round' }} />}
          {serviceCenters.map((center) => <CircleMarker key={center.service_center_id} center={[center.lat, center.lon]} radius={expanded ? 10 : 8} pathOptions={{ color: '#fff', weight: 2, fillColor: '#23365d', fillOpacity: 1 }}><Tooltip direction="top">{center.name}</Tooltip><Popup><strong>{center.name}</strong><br />{center.address}<br />{center.service_center_id}</Popup></CircleMarker>)}
          {Object.values(orders).map((order) => {
            const staffId = plannedByOrder[order.order_id]; const isSelected = selectedOrderIds.has(order.order_id);
            const color = staffId ? routePalette[staffId] ?? '#718096' : '#d68a2e';
            return <CircleMarker key={order.order_id} center={[order.lat, order.lon]} radius={isSelected ? 7 : staffId ? 5 : 4} pathOptions={{ color: '#fff', weight: isSelected ? 2 : 1, fillColor: color, fillOpacity: isSelected ? 1 : 0.86 }}><Tooltip direction="top">{order.order_id}{staffId ? ` · ${staffId}` : ' · не назначен'}</Tooltip><Popup><strong>{order.order_id}</strong><br />{order.address}<br />{order.work_type_code} · {order.technology}{staffId && <><br />Назначен: {staffId}</>}</Popup></CircleMarker>;
          })}
        </MapContainer>
        <div className="map-legend"><span><i className="legend-dot depot" />Сервисные центры</span><span><i className="legend-dot selected" />Выбранный маршрут</span><span><i className="legend-dot assigned" />Назначенные заявки</span><span><i className="legend-dot open" />Без назначения</span></div>
        <div className="map-zoom-hint">+ / − · масштаб карты</div>
      </div>
      <div className="map-footer"><span>{displayed.status === 'loading' ? 'Строим дорожную геометрию…' : displayed.status === 'ready' ? `По дорогам: ${formatDistance(displayed.distanceM)} · около ${Math.round(displayed.durationSec / 60)} мин по OSRM` : displayed.status === 'error' ? `Маршрут OSRM недоступен: ${displayed.message}` : 'Выберите сотрудника с остановками'}</span><span>Маршруты других сотрудников доступны через список справа</span></div>
      <div className="map-disclaimer">Линия на карте — геометрия дорожного маршрута OSRM для выбранного сотрудника. Для конкурсной оценки время поездок берётся из матрицы организаторов.</div>
    </section>
  );
};
