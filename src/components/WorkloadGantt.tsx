import React, { useEffect, useRef } from 'react';
import type { Route, StaffMember, Stop } from '../types/dispatch';

interface WorkloadGanttProps {
  routes: Route[];
  staffById: Record<string, StaffMember>;
  selectedStaffId: string | null;
  onSelectStaff: (staffId: string) => void;
  onExpand?: () => void;
  expanded?: boolean;
  highlightedOrderId?: string | null;
}

const DAY_START_MIN = 8 * 60 + 30;
const DAY_END_MIN = 21 * 60 + 30;
const DAY_SPAN = DAY_END_MIN - DAY_START_MIN;
const HOUR_MARKS = [9, 11, 13, 15, 17, 19, 21];

function toMin(iso: string): number {
  const match = iso.match(/T(\d{2}):(\d{2})/);
  return match ? Number(match[1]) * 60 + Number(match[2]) : DAY_START_MIN;
}
function clockToMin(value?: string): number {
  if (!value) return DAY_START_MIN;
  const match = value.match(/^(\d{2}):(\d{2})/);
  return match ? Number(match[1]) * 60 + Number(match[2]) : DAY_START_MIN;
}
function pct(minute: number): number {
  const clamped = Math.max(DAY_START_MIN, Math.min(DAY_END_MIN, minute));
  return ((clamped - DAY_START_MIN) / DAY_SPAN) * 100;
}
function stopClass(stop: Stop): string {
  if (stop.type === 'VISIT') return 'gantt-visit';
  if (stop.type === 'BREAK') return 'gantt-break';
  if (stop.type === 'RESTOCK') return 'gantt-restock';
  return 'gantt-other';
}

export const WorkloadGantt: React.FC<WorkloadGanttProps> = ({ routes, staffById, selectedStaffId, onSelectStaff, onExpand, expanded = false, highlightedOrderId = null }) => {
  const rowsRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!highlightedOrderId) return;
    const row = rowsRef.current?.querySelector<HTMLElement>('[data-highlighted-order=\"true\"]');
    row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [highlightedOrderId]);

  return (
  <section className={`gantt-content ${expanded ? 'gantt-expanded' : ''}`}>
    <div className="panel-heading">
      <div className="panel-heading-copy"><div className="panel-title-row"><h2>Загрузка сотрудников · диаграмма Ганта</h2><span className="count-pill">{routes.length} сотрудников</span></div><p>Работа, дорога, обед и пополнение оборудования по модельному времени смены</p></div>
      {onExpand && <button className="icon-button" type="button" onClick={onExpand} title="Развернуть диаграмму">⤢</button>}
    </div>
    <div className="gantt-legend"><span><i className="legend-swatch work" />Работа с клиентом</span><span><i className="legend-swatch travel" />Дорога</span><span><i className="legend-swatch break" />Обед</span><span><i className="legend-swatch restock" />Пополнение АО</span></div>
    <div className="gantt-scroll">
      <div className="gantt-table">
        <div className="gantt-axis"><span>Сотрудник</span><div className="gantt-time-axis">{HOUR_MARKS.map((hour) => <span key={hour} style={{ left: `${pct(hour * 60)}%` }}>{String(hour).padStart(2, '0')}:00</span>)}</div><span className="align-right">Загрузка</span></div>
        <div className="gantt-rows" ref={rowsRef}>
          {routes.map((route) => {
            const staff = staffById[route.staff_id]; const selected = selectedStaffId === route.staff_id;
            const utilization = Math.round((route.totals?.utilization ?? 0) * 100);
            return <button key={route.staff_id} type="button" onClick={() => onSelectStaff(route.staff_id)} className={`gantt-row ${selected ? 'is-selected' : ''}`} data-highlighted-order={route.stops.some((stop) => stop.type === 'VISIT' && stop.order_id === highlightedOrderId) ? 'true' : undefined}>
              <span className="gantt-staff"><strong>{staff?.display_name ?? route.staff_id}</strong><small>{route.staff_id} · {staff?.profiles[0] === 'INSTALL' ? 'Инсталляция' : '3ЛТП'} · {route.totals?.visits ?? 0} нар.</small></span>
              <span className="gantt-track">
                {staff?.shift && (() => {
                  const shiftLeft = pct(clockToMin(staff.shift.start));
                  const shiftRight = pct(clockToMin(staff.shift.end));
                  return <i className="gantt-shift-window" style={{ left: `${shiftLeft}%`, width: `${Math.max(0, shiftRight - shiftLeft)}%` }} title={`Смена ${staff.shift.start}–${staff.shift.end}`} />;
                })()}
                {route.stops.flatMap((stop, index) => {
                  const blocks: React.ReactNode[] = [];
                  const previous = route.stops[index - 1];
                  if (previous && stop.travel_sec && stop.travel_sec > 0) {
                    const travelLeft = pct(toMin(previous.end));
                    const travelRight = pct(toMin(stop.arrival));
                    const travelWidth = Math.max(0, travelRight - travelLeft);
                    if (travelWidth > 0) blocks.push(<i key={`${stop.seq}-travel`} className="gantt-block gantt-travel" style={{ left: `${travelLeft}%`, width: `${travelWidth}%` }} title={`Дорога · ${Math.round(stop.travel_sec / 60)} мин`} />);
                  }
                  if (!['DEPOT_START', 'DEPOT_END'].includes(stop.type)) {
                    const left = pct(toMin(stop.start)); const right = pct(toMin(stop.end)); const width = Math.max(0.7, right - left);
                    const highlighted = stop.type === 'VISIT' && stop.order_id === highlightedOrderId;
                    blocks.push(<i key={stop.seq} className={`gantt-block ${stopClass(stop)} ${highlighted ? 'is-highlighted' : ''}`} style={{ left: `${left}%`, width: `${width}%` }} title={`${stop.type} · ${stop.order_id ?? stop.location_id}`} />);
                  }
                  return blocks;
                })}
              </span>
              <span className={`gantt-load ${utilization >= 90 ? 'overload' : ''}`}>{route.status === 'UNAVAILABLE' ? 'Выбыл' : `${utilization}%`}</span>
            </button>;
          })}
        </div>
      </div>
    </div>
  </section>
  );
};
