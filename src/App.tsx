import { createPortal } from 'react-dom';
import type { ReactNode } from 'react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { RouteMap } from './components/RouteMap';
import { WorkloadGantt } from './components/WorkloadGantt';
import type { AlertItem, DayContextResponse, OrderRecord, Route, StaffMember, Stop, WorkTypeItem } from './types/dispatch';

type ProfileFilter = 'ALL' | 'LTP3' | 'INSTALL';
type ExpandedPanel = 'map' | 'gantt' | 'staff' | 'orders' | null;
type EventKind = 'STAFF_UNAVAILABLE' | 'VISIT_DELAYED' | 'ORDER_TRANSFERRED' | 'ORDER_CANCELLED' | 'NEW_ORDER';

const ROUTE_COLORS = ['#7400e8', '#4388e6', '#db8a36', '#d45d7a', '#36a3b6', '#8b6bd1', '#79a64b'];

function portalRoot(): Element {
  return document.querySelector('.app-shell') ?? document.body;
}

function fmtTime(iso?: string | null): string {
  if (!iso) return '—';
  const match = iso.match(/T(\d{2}:\d{2})/);
  return match ? match[1] : iso;
}

function fmtMinutes(value: number): string {
  const mins = Math.max(0, Math.round(value));
  return mins >= 60 ? `${Math.floor(mins / 60)} ч ${mins % 60} мин` : `${mins} мин`;
}

function profileLabel(profile?: string): string {
  return profile === 'INSTALL' ? 'Инсталляция' : profile === 'LTP3' ? '3ЛТП' : profile ?? '—';
}

function workLabel(code: string): string {
  const labels: Record<string, string> = {
    INST_PON_MKD: 'Инсталляция PON', INST_FTTB_MKD: 'Инсталляция FTTB',
    INST_PRIVATE_VLS: 'Инсталляция ВЛС', ADD_SERVICE: 'Доподключение',
    SURVEY_PRIVATE: 'Обследование', REPAIR: 'Устранение неисправности',
    DEGRADATION: 'Устранение деградации', DISMANTLE: 'Демонтаж оборудования',
  };
  return labels[code] ?? code;
}

function orderStatus(orderId: string, ctx: DayContextResponse): { label: string; tone: string; staff?: string } {
  const unassigned = ctx.plan.unassigned.some((item) => item.order_id === orderId);
  if (unassigned) return { label: 'Не назначен', tone: 'warning' };
  const cancelled = ctx.plan.cancelled.some((item) => item.order_id === orderId);
  if (cancelled) return { label: 'Отменён', tone: 'muted' };
  const pgp = ctx.plan.pgp_groups.some((group) => group.order_ids.includes(orderId));
  if (pgp) return { label: 'Групповая проблема', tone: 'purple' };
  for (const route of ctx.plan.routes) {
    const stop = route.stops.find((item) => item.order_id === orderId);
    if (stop) {
      const label = stop.status === 'DONE' ? 'Выполнен' : stop.status === 'IN_PROGRESS' ? 'В работе' : 'Назначен';
      const tone = stop.status === 'DONE' ? 'success' : stop.status === 'IN_PROGRESS' ? 'info' : 'neutral';
      return { label, tone, staff: route.staff_id };
    }
  }
  return { label: 'Статус неизвестен', tone: 'muted' };
}

function toLocalInput(iso?: string | null): string {
  if (!iso) return '';
  return iso.slice(0, 16);
}

function withEkaterinburgOffset(local: string): string {
  if (!local) return '';
  return `${local.length === 16 ? `${local}:00` : local}+05:00`;
}

function StatCard({ label, value, hint, tone = 'default' }: { label: string; value: string; hint?: string; tone?: string }) {
  return (
    <div className={`stat-card stat-${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      {hint && <div className="stat-hint">{hint}</div>}
    </div>
  );
}

function PanelHeader({ title, subtitle, count, onExpand, expanded = false, action }: {
  title: string; subtitle?: string; count?: string; onExpand?: () => void; expanded?: boolean; action?: ReactNode;
}) {
  return (
    <div className="panel-heading">
      <div className="panel-heading-copy">
        <div className="panel-title-row"><h2>{title}</h2>{count && <span className="count-pill">{count}</span>}</div>
        {subtitle && <p>{subtitle}</p>}
      </div>
      <div className="panel-heading-actions">
        {action}
        {onExpand && <button className="icon-button" type="button" onClick={onExpand} title={expanded ? 'Свернуть' : 'Развернуть'}>{expanded ? '↙' : '⤢'}</button>}
      </div>
    </div>
  );
}

function StatusPill({ label, tone = 'neutral' }: { label: string; tone?: string }) {
  return <span className={`status-pill status-${tone}`}>{label}</span>;
}

interface AvailableBuilding {
  building_id: string;
  address: string;
  lat: number;
  lon: number;
  building_type: string;
  overhead_line: boolean;
  access_node_id: string;
  technology: string;
}

const STANDARD_SLOTS = [
  '09:00-11:00',
  '11:00-13:00',
  '13:00-15:00',
  '15:00-17:00',
  '17:00-19:00',
  '19:00-21:00',
];

const EQUIPMENT_DEFAULTS: Record<string, { ONT: number; ROUTER: number; STB: number }> = {
  INST_PON_MKD: { ONT: 1, ROUTER: 1, STB: 0 },
  INST_FTTB_MKD: { ONT: 0, ROUTER: 1, STB: 0 },
  INST_PRIVATE_VLS: { ONT: 1, ROUTER: 1, STB: 0 },
  ADD_SERVICE: { ONT: 0, ROUTER: 1, STB: 0 },
  SURVEY_PRIVATE: { ONT: 0, ROUTER: 0, STB: 0 },
  REPAIR: { ONT: 0, ROUTER: 0, STB: 0 },
  DEGRADATION: { ONT: 0, ROUTER: 0, STB: 0 },
  DISMANTLE: { ONT: 0, ROUTER: 0, STB: 0 },
};

function addMinutesToEkaterinburg(iso: string, minutes: number): string {
  const value = new Date(iso);
  value.setTime(value.getTime() + minutes * 60_000);
  const local = new Date(value.getTime() + 5 * 60 * 60_000);
  const pad = (n: number) => String(n).padStart(2, '0');
  return `${local.getUTCFullYear()}-${pad(local.getUTCMonth() + 1)}-${pad(local.getUTCDate())}T${pad(local.getUTCHours())}:${pad(local.getUTCMinutes())}:${pad(local.getUTCSeconds())}+05:00`;
}

function addWorkingDaysToEkaterinburg(iso: string, days: number): string {
  let result = iso;
  let remaining = Math.max(0, days);
  while (remaining > 0) {
    result = addMinutesToEkaterinburg(result, 24 * 60);
    const date = new Date(new Date(result).getTime() + 5 * 60 * 60_000);
    const weekday = date.getUTCDay();
    if (weekday !== 0 && weekday !== 6) remaining -= 1;
  }
  return result;
}

function getOrderDeadline(workType: WorkTypeItem, registeredAt: string, latestStart: string, isRepeat: boolean): string {
  if (workType.deadline_kind === 'SLOT') {
    return addMinutesToEkaterinburg(latestStart, workType.duration_min);
  }
  const duration = isRepeat && workType.repeat_deadline_value != null
    ? workType.repeat_deadline_value
    : workType.deadline_value ?? 1;
  if (workType.deadline_kind === 'HOURS') {
    return addMinutesToEkaterinburg(registeredAt, duration * 60);
  }
  return addWorkingDaysToEkaterinburg(registeredAt, duration);
}

function CreateOrderModal({
  ctx, initialStaffId, onClose, onSubmit, loading,
}: {
  ctx: DayContextResponse; initialStaffId: string | null; onClose: () => void;
  onSubmit: (event: Record<string, unknown>) => Promise<void>; loading: boolean;
}) {
  const modelTime = ctx.plan.as_of;
  const dateStr = ctx.plan.date;

  const [targetStaffId, setTargetStaffId] = useState<string>(initialStaffId ?? '');
  const [workTypeCode, setWorkTypeCode] = useState<string>(() => {
    const staff = ctx.staff.find((item) => item.staff_id === initialStaffId);
    const preferredCode = staff?.profiles.includes('INSTALL') && !staff.profiles.includes('LTP3') ? 'INST_PON_MKD' : 'REPAIR';
    return ctx.work_types?.some((item) => item.code === preferredCode)
      ? preferredCode
      : ctx.work_types?.find((item) => !staff || item.profiles.some((profile) => staff.profiles.includes(profile)))?.code ?? ctx.work_types?.[0]?.code ?? '';
  });
  const [buildingSearch, setBuildingSearch] = useState('');
  const [selectedBuildingId, setSelectedBuildingId] = useState<string>('');
  const [technology, setTechnology] = useState<string>('PON');
  const [selectedSlot, setSelectedSlot] = useState<string>('13:00-15:00');
  const [customSlot, setCustomSlot] = useState(false);
  const [customStart, setCustomStart] = useState('13:00');
  const [customEnd, setCustomEnd] = useState('15:00');
  const [requiresHeight, setRequiresHeight] = useState(false);
  const [isRepeat, setIsRepeat] = useState(false);
  const initialEquipment = EQUIPMENT_DEFAULTS[workTypeCode] ?? { ONT: 0, ROUTER: 0, STB: 0 };
  const [ont, setOnt] = useState(initialEquipment.ONT);
  const [router, setRouter] = useState(initialEquipment.ROUTER);
  const [stb, setStb] = useState(initialEquipment.STB);
  const [orderId, setOrderId] = useState(() => `ORD-${dateStr.replace(/-/g, '')}-${Math.floor(1000 + Math.random() * 9000)}`);

  const buildings = useMemo<AvailableBuilding[]>(() => {
    const result: AvailableBuilding[] = [];
    const seen = new Set<string>();

    if (ctx.access_nodes && ctx.access_nodes.length > 0) {
      for (const node of ctx.access_nodes) {
        for (const b of node.buildings) {
          if (!seen.has(b.building_id)) {
            seen.add(b.building_id);
            result.push({
              building_id: b.building_id,
              address: b.address,
              lat: b.lat,
              lon: b.lon,
              building_type: b.building_type,
              overhead_line: b.overhead_line,
              access_node_id: node.access_node_id,
              technology: node.technology,
            });
          }
        }
      }
    }

    if (ctx.orders) {
      for (const order of Object.values(ctx.orders)) {
        if (!seen.has(order.building_id)) {
          seen.add(order.building_id);
          result.push({
            building_id: order.building_id,
            address: order.address,
            lat: order.lat,
            lon: order.lon,
            building_type: order.building_type || 'MKD',
            overhead_line: order.requires_height,
            access_node_id: order.access_node_id,
            technology: order.technology,
          });
        }
      }
    }

    return result.sort((a, b) => a.address.localeCompare(b.address, 'ru'));
  }, [ctx]);

  useEffect(() => {
    if (buildings.length > 0 && !selectedBuildingId) {
      setSelectedBuildingId(buildings[0].building_id);
      setTechnology(buildings[0].technology);
      setRequiresHeight(buildings[0].overhead_line);
    }
  }, [buildings, selectedBuildingId]);

  const selectedWorkType = ctx.work_types?.find((item) => item.code === workTypeCode);

  const applyEquipmentDefaults = (code: string) => {
    const equipment = EQUIPMENT_DEFAULTS[code] ?? { ONT: 0, ROUTER: 0, STB: 0 };
    setOnt(equipment.ONT);
    setRouter(equipment.ROUTER);
    setStb(equipment.STB);
  };

  const handleSelectBuilding = (bId: string) => {
    setSelectedBuildingId(bId);
    const building = buildings.find((item) => item.building_id === bId);
    if (building) {
      setTechnology(building.technology);
      setRequiresHeight(building.overhead_line || workTypeCode === 'INST_PRIVATE_VLS');
    }
  };

  const handleSelectWorkType = (code: string) => {
    setWorkTypeCode(code);
    applyEquipmentDefaults(code);
    const building = buildings.find((item) => item.building_id === selectedBuildingId);
    if (code === 'INST_PON_MKD') setTechnology('PON');
    else if (code === 'INST_FTTB_MKD') setTechnology('FTTB');
    else if (building) setTechnology(building.technology);
    setRequiresHeight(code === 'INST_PRIVATE_VLS' || Boolean(building?.overhead_line));
  };

  const handleSelectTargetStaff = (staffId: string) => {
    setTargetStaffId(staffId);
    const staff = ctx.staff.find((item) => item.staff_id === staffId);
    if (!staff || !ctx.work_types?.length) return;
    const current = ctx.work_types.find((item) => item.code === workTypeCode);
    if (current?.profiles.some((profile) => staff.profiles.includes(profile))) return;
    const suitable = ctx.work_types.find((item) => item.profiles.some((profile) => staff.profiles.includes(profile)));
    if (suitable) handleSelectWorkType(suitable.code);
  };

  const filteredBuildings = useMemo(() => {
    if (!buildingSearch) return buildings.slice(0, 60);
    const q = buildingSearch.toLowerCase();
    return buildings.filter((b) =>
      b.address.toLowerCase().includes(q) ||
      b.building_id.toLowerCase().includes(q) ||
      b.access_node_id.toLowerCase().includes(q)
    ).slice(0, 60);
  }, [buildings, buildingSearch]);

  const targetStaff = targetStaffId ? ctx.staff.find((st) => st.staff_id === targetStaffId) : null;
  const staffValidation = useMemo(() => {
    if (!targetStaff) return null;
    const wt = ctx.work_types?.find((item) => item.code === workTypeCode);
    const issues: string[] = [];
    if (wt && !wt.profiles.some((profile) => targetStaff.profiles.includes(profile))) {
      issues.push(`Профиль сотрудника (${targetStaff.profiles.map(profileLabel).join(', ')}) не соответствует типу работы «${wt.name}»`);
    }
    if (!targetStaff.technologies.includes(technology)) {
      issues.push(`Сотрудник ${targetStaff.staff_id} не аттестован на технологию ${technology}`);
    }
    if (requiresHeight && !targetStaff.height_permit) {
      issues.push(`Требуется допуск на высоту (H4), у сотрудника ${targetStaff.staff_id} допуска нет`);
    }
    return { ok: issues.length === 0, issues };
  }, [targetStaff, ctx.work_types, workTypeCode, technology, requiresHeight]);
  const selectedBuilding = buildings.find((item) => item.building_id === selectedBuildingId);
  const orderValidationIssues: string[] = [];
  if (selectedBuilding && selectedBuilding.technology !== technology) orderValidationIssues.push(`Выбранный дом подключён по технологии ${selectedBuilding.technology}`);
  if (workTypeCode === 'INST_PON_MKD' && technology !== 'PON') orderValidationIssues.push('Инсталляция PON требует технологию PON');
  if (workTypeCode === 'INST_FTTB_MKD' && technology !== 'FTTB') orderValidationIssues.push('Инсталляция FTTB требует технологию FTTB');
  if (workTypeCode === 'INST_PRIVATE_VLS' && !requiresHeight) orderValidationIssues.push('Для ВЛС требуется допуск к высотным работам');

  const submit = async () => {
    const chosenBuilding = buildings.find((b) => b.building_id === selectedBuildingId) ?? buildings[0];
    if (!chosenBuilding) return;

    const sStart = customSlot ? customStart : selectedSlot.split('-')[0];
    const sEnd = customSlot ? customEnd : selectedSlot.split('-')[1];
    const slotStartIso = `${dateStr}T${sStart}:00+05:00`;
    const slotEndIso = `${dateStr}T${sEnd}:00+05:00`;
    const workType = ctx.work_types?.find((item) => item.code === workTypeCode);
    if (!workType) throw new Error('Тип работы отсутствует в загруженном справочнике.');
    if (new Date(slotEndIso).getTime() <= new Date(slotStartIso).getTime()) throw new Error('Окончание временного слота должно быть позже его начала.');
    if (staffValidation && !staffValidation.ok) throw new Error(staffValidation.issues.join('; '));
    const latestDelay = workType.max_start_delay_min;
    const latestByRule = latestDelay == null ? slotEndIso : addMinutesToEkaterinburg(slotStartIso, latestDelay);
    const latestStartIso = new Date(latestByRule).getTime() < new Date(slotEndIso).getTime() ? latestByRule : slotEndIso;
    const deadlineIso = getOrderDeadline(workType, modelTime, latestStartIso, isRepeat);

    const cleanOrderId = orderId.trim() || `ORD-${dateStr.replace(/-/g, '')}-${Math.floor(1000 + Math.random() * 9000)}`;

    const orderPayload: Record<string, unknown> = {
      order_id: cleanOrderId,
      work_type_code: workTypeCode,
      technology,
      building_id: chosenBuilding.building_id,
      address: chosenBuilding.address,
      lat: chosenBuilding.lat,
      lon: chosenBuilding.lon,
      building_type: chosenBuilding.building_type || 'MKD',
      requires_height: requiresHeight,
      access_node_id: chosenBuilding.access_node_id,
      registered_at: modelTime,
      slot: {
        start: slotStartIso,
        end: slotEndIso,
      },
      latest_start: latestStartIso,
      deadline: deadlineIso,
      required_equipment: {
        ONT: ont,
        ROUTER: router,
        STB: stb,
      },
      is_repeat: isRepeat,
    };

    if (targetStaffId) {
      orderPayload.target_staff_id = targetStaffId;
    }

    const eventPayload = {
      event_id: `EV-MANUAL-${Date.now()}`,
      timestamp: modelTime,
      type: 'NEW_ORDER',
      order: orderPayload,
    };

    await onSubmit(eventPayload);
  };

  return createPortal(
    <div className="overlay-root" role="presentation" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <section className="dialog-card new-order-dialog" role="dialog" aria-modal="true" aria-labelledby="create-order-title">
        <div className="dialog-heading">
          <div>
            <div className="eyebrow">Оперативное диспетчирование</div>
            <h2 id="create-order-title">Добавить наряд в график работников</h2>
            <p>Новая задача встраивается в график смены с соблюдением критериев H1–H10 (слоты, допуск, остаток АО, смена и перерывы).</p>
          </div>
          <button className="icon-button" onClick={onClose} type="button">✕</button>
        </div>

        <div className="form-grid">
          <label className="field-label" style={{ gridColumn: '1 / -1' }}>
            Назначение исполнителя
            <select value={targetStaffId} onChange={(e) => handleSelectTargetStaff(e.target.value)}>
              <option value="">⚡ Авто-распределение (VRPTW оптимизатор по ТЗ H1–H10)</option>
              {ctx.staff.map((st) => (
                <option key={st.staff_id} value={st.staff_id}>
                  {st.display_name ?? st.staff_id} ({st.staff_id}) · {profileLabel(st.profiles[0])} · Смена {st.shift.start}–{st.shift.end} · {st.service_center_id}
                </option>
              ))}
            </select>
          </label>

          {targetStaff ? (
            <div className="staff-qualification-badge" style={{ gridColumn: '1 / -1' }}>
              <div className="sq-info">
                <strong>{targetStaff.display_name ?? targetStaff.staff_id}</strong>
                <span>Профиль: {profileLabel(targetStaff.profiles[0])} · Технологии: {targetStaff.technologies.join(', ')} · Высота: {targetStaff.height_permit ? 'Есть' : 'Нет'}</span>
              </div>
              {staffValidation && !staffValidation.ok && (
                <div className="sq-warning">
                  {staffValidation.issues.map((issue, idx) => (
                    <div key={idx}>⚠️ {issue}</div>
                  ))}
                  <small>Если наряд не сможет быть назначен выбранному сотруднику без нарушения ТЗ, он будет помещён в нераспределённые с кодом причины.</small>
                </div>
              )}
              {staffValidation && staffValidation.ok && (
                <div className="sq-ok">✓ Квалификация сотрудника соответствует параметрам наряда.</div>
              )}
            </div>
          ) : (
            <div className="inline-info" style={{ gridColumn: '1 / -1' }}>
              ✓ Оптимизатор VRPTW автоматически подберет квалифицированного сотрудника с минимальным дополнительным пробегом и сбалансирует нагрузку.
            </div>
          )}

          <label className="field-label">
            Тип работы
            <select value={workTypeCode} onChange={(e) => handleSelectWorkType(e.target.value)}>
              {(ctx.work_types ?? []).map((wt) => (
                <option key={wt.code} value={wt.code}>
                  {wt.name} ({wt.duration_min} мин · {wt.profiles.map(profileLabel).join(' / ')})
                </option>
              ))}
            </select>
          </label>

          <label className="field-label">
            Технология
            <select value={technology} onChange={(e) => setTechnology(e.target.value)}>
              <option value="PON">PON</option>
              <option value="FTTB">FTTB</option>
              <option value="XDSL">xDSL</option>
              <option value="DOCSIS">DOCSIS</option>
            </select>
          </label>

          {orderValidationIssues.length > 0 && (
            <div className="sq-warning" style={{ gridColumn: '1 / -1' }}>
              {orderValidationIssues.map((issue) => <div key={issue}>⚠ {issue}</div>)}
            </div>
          )}

          <label className="field-label" style={{ gridColumn: '1 / -1' }}>
            Адрес / Дом в Екатеринбурге
            <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 2fr', gap: '8px', marginTop: '4px' }}>
              <input
                type="text"
                placeholder="Поиск по улице/дому..."
                value={buildingSearch}
                onChange={(e) => setBuildingSearch(e.target.value)}
              />
              <select value={selectedBuildingId} onChange={(e) => handleSelectBuilding(e.target.value)}>
                {filteredBuildings.map((b) => (
                  <option key={b.building_id} value={b.building_id}>
                    {b.address} ({b.building_id} · {b.building_type === 'MKD' ? 'МКД' : 'ЧС'} · {b.technology})
                  </option>
                ))}
              </select>
            </div>
          </label>

          <div className="field-label" style={{ gridColumn: '1 / -1' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
              <span>Временной слот визита (по ТЗ слоты по 2 часа)</span>
              <button
                type="button"
                className="text-button"
                onClick={() => setCustomSlot(!customSlot)}
              >
                {customSlot ? 'Выбрать стандартный слот' : 'Указать произвольное время'}
              </button>
            </div>
            {!customSlot ? (
              <div className="slot-chips">
                {STANDARD_SLOTS.map((s) => (
                  <button
                    key={s}
                    type="button"
                    className={`slot-chip ${selectedSlot === s ? 'is-selected' : ''}`}
                    onClick={() => setSelectedSlot(s)}
                  >
                    {s}
                  </button>
                ))}
              </div>
            ) : (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '8px', marginTop: '4px' }}>
                <label className="field-sublabel">
                  Начало слота
                  <input type="time" value={customStart} onChange={(e) => setCustomStart(e.target.value)} />
                </label>
                <label className="field-sublabel">
                  Окончание слота
                  <input type="time" value={customEnd} onChange={(e) => setCustomEnd(e.target.value)} />
                </label>
              </div>
            )}
          </div>

          <div className="field-label" style={{ gridColumn: '1 / -1' }}>
            <span>Необходимое оборудование клиенту (шт.)</span>
            <div className="equipment-grid">
              <div className="equipment-counter">
                <small>ONT (терминал PON)</small>
                <div>
                  <button type="button" onClick={() => setOnt(Math.max(0, ont - 1))}>−</button>
                  <span>{ont}</span>
                  <button type="button" onClick={() => setOnt(ont + 1)}>＋</button>
                </div>
              </div>
              <div className="equipment-counter">
                <small>ROUTER (роутер)</small>
                <div>
                  <button type="button" onClick={() => setRouter(Math.max(0, router - 1))}>−</button>
                  <span>{router}</span>
                  <button type="button" onClick={() => setRouter(router + 1)}>＋</button>
                </div>
              </div>
              <div className="equipment-counter">
                <small>STB (ТВ-приставка)</small>
                <div>
                  <button type="button" onClick={() => setStb(Math.max(0, stb - 1))}>−</button>
                  <span>{stb}</span>
                  <button type="button" onClick={() => setStb(stb + 1)}>＋</button>
                </div>
              </div>
            </div>
          </div>

          <div className="checkbox-row" style={{ gridColumn: '1 / -1', display: 'flex', gap: '18px', margin: '4px 0' }}>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={requiresHeight}
                onChange={(e) => setRequiresHeight(e.target.checked)}
              />
              <span>Требуется допуск на высоту (H4)</span>
            </label>
            <label className="checkbox-label">
              <input
                type="checkbox"
                checked={isRepeat}
                onChange={(e) => setIsRepeat(e.target.checked)}
              />
              <span>Повторный наряд (is_repeat, приоритет в очереди)</span>
            </label>
          </div>

          <label className="field-label" style={{ gridColumn: '1 / -1' }}>
            Номер наряда (order_id)
            <input
              type="text"
              value={orderId}
              onChange={(e) => setOrderId(e.target.value)}
              placeholder="ORD-YYYYMMDD-XXXX"
            />
          </label>
        </div>

        <div className="event-time-note">
          Модельное время регистрации: <strong>{fmtTime(modelTime)}</strong> (актуальное время плана смены).
        </div>

        <div className="dialog-actions">
          <button className="button button-secondary" type="button" onClick={onClose}>
            Отмена
          </button>
          <button
            className="button button-primary"
            type="button"
            disabled={loading || !selectedBuildingId || !selectedWorkType || orderValidationIssues.length > 0 || Boolean(staffValidation && !staffValidation.ok) || new Date(`${dateStr}T${customSlot ? customEnd : selectedSlot.split('-')[1]}:00+05:00`).getTime() <= new Date(`${dateStr}T${customSlot ? customStart : selectedSlot.split('-')[0]}:00+05:00`).getTime()}
            onClick={() => void submit()}
          >
            {loading ? 'Назначение в график…' : '＋ Добавить наряд в план'}
          </button>
        </div>
      </section>
    </div>,
    portalRoot(),
  );
}

function EventModal({
  ctx, selectedStaffId, onClose, onSubmit, onOpenCreateOrder, loading,
}: {
  ctx: DayContextResponse; selectedStaffId: string | null; onClose: () => void;
  onSubmit: (event: Record<string, unknown>) => Promise<void>; onOpenCreateOrder: (staffId?: string | null) => void; loading: boolean;
}) {
  const [kind, setKind] = useState<EventKind>('STAFF_UNAVAILABLE');
  const [staffId, setStaffId] = useState(selectedStaffId ?? ctx.staff[0]?.staff_id ?? '');
  const [orderId, setOrderId] = useState('');
  const [reason, setReason] = useState('VEHICLE_BREAKDOWN');
  const [until, setUntil] = useState('');
  const [expectedEnd, setExpectedEnd] = useState('');
  const [transferTo, setTransferTo] = useState('STATION_EQUIPMENT');
  const modelTime = ctx.plan.as_of;
  const startedVisits = useMemo(() => ctx.plan.routes.flatMap((route) => route.stops
    .filter((stop) => stop.type === 'VISIT' && stop.order_id && stop.start <= modelTime && stop.end > modelTime)
    .map((stop) => ({ ...stop, staff_id: route.staff_id }))), [ctx, modelTime]);
  const cancellableVisits = useMemo(() => ctx.plan.routes.flatMap((route) => route.stops
    .filter((stop) => stop.type === 'VISIT' && stop.order_id && stop.start > modelTime)
    .map((stop) => ({ ...stop, staff_id: route.staff_id }))), [ctx, modelTime]);
  const eligible = kind === 'VISIT_DELAYED' || kind === 'ORDER_TRANSFERRED' ? startedVisits : cancellableVisits;
  useEffect(() => { if (eligible.length && !eligible.some((item) => item.order_id === orderId)) setOrderId(eligible[0].order_id ?? ''); }, [eligible, orderId]);

  const submit = async () => {
    if (kind === 'NEW_ORDER') {
      onClose();
      onOpenCreateOrder(staffId);
      return;
    }
    const eventId = `EV-UI-${Date.now()}`;
    const base: Record<string, unknown> = { event_id: eventId, timestamp: modelTime, type: kind };
    if (kind === 'STAFF_UNAVAILABLE') {
      base.staff_id = staffId;
      base.reason = reason;
      base.until = until ? withEkaterinburgOffset(until) : null;
    } else if (kind === 'ORDER_CANCELLED') {
      base.order_id = orderId;
      base.reason = reason;
    } else if (kind === 'VISIT_DELAYED') {
      const visit = startedVisits.find((item) => item.order_id === orderId);
      base.staff_id = visit?.staff_id ?? staffId;
      base.order_id = orderId;
      base.expected_end = withEkaterinburgOffset(expectedEnd);
    } else {
      const visit = startedVisits.find((item) => item.order_id === orderId);
      base.staff_id = visit?.staff_id ?? staffId;
      base.order_id = orderId;
      base.actual_end = modelTime;
      base.transferred_to = transferTo;
    }
    await onSubmit(base);
  };

  return createPortal(
    <div className="overlay-root" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <section className="dialog-card event-dialog" role="dialog" aria-modal="true" aria-labelledby="event-title">
        <div className="dialog-heading"><div><div className="eyebrow">Ручная регистрация</div><h2 id="event-title">Зафиксировать событие</h2><p>Система не видит звонки и GPS сама. Укажите факт, полученный от сотрудника или клиента.</p></div><button className="icon-button" onClick={onClose} type="button">✕</button></div>
        <div className="form-grid">
          <label className="field-label">Тип события
            <select value={kind} onChange={(e) => { setKind(e.target.value as EventKind); setOrderId(''); setReason(e.target.value === 'ORDER_CANCELLED' ? 'NOT_CONFIRMED' : 'VEHICLE_BREAKDOWN'); }}>
              <option value="STAFF_UNAVAILABLE">Сотрудник недоступен</option>
              <option value="VISIT_DELAYED">Задержка текущей работы</option>
              <option value="ORDER_TRANSFERRED">Передача в станционное подразделение</option>
              <option value="ORDER_CANCELLED">Отмена визита клиентом</option>
              <option value="NEW_ORDER">＋ Новый наряд в график (NEW_ORDER)</option>
            </select>
          </label>
          {kind === 'NEW_ORDER' && (
            <div className="inline-info" style={{ gridColumn: '1 / -1' }}>
              Для добавления нового наряда в график используется интерактивная форма создания задачи с выбором адресов, оборудования и слотов.
              <div style={{ marginTop: '10px' }}>
                <button type="button" className="button button-primary" onClick={() => { onClose(); onOpenCreateOrder(staffId); }}>
                  Открыть форму создания наряда →
                </button>
              </div>
            </div>
          )}
          {kind === 'STAFF_UNAVAILABLE' && <>
            <label className="field-label">Сотрудник<select value={staffId} onChange={(e) => setStaffId(e.target.value)}>{ctx.staff.map((staff) => <option key={staff.staff_id} value={staff.staff_id}>{staff.staff_id} · {staff.display_name ?? profileLabel(staff.profiles[0])}</option>)}</select></label>
            <label className="field-label">Причина<select value={reason} onChange={(e) => setReason(e.target.value)}><option value="VEHICLE_BREAKDOWN">Поломка автомобиля</option><option value="ILLNESS">Болезнь</option><option value="OTHER">Другая причина</option></select></label>
            <label className="field-label">Недоступен до (необязательно)<input type="datetime-local" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
          </>}
          {kind !== 'STAFF_UNAVAILABLE' && kind !== 'NEW_ORDER' && <>
            <label className="field-label">Наряд<select value={orderId} onChange={(e) => setOrderId(e.target.value)}>{eligible.map((visit) => <option key={visit.order_id ?? ''} value={visit.order_id ?? ''}>{visit.order_id} · {visit.staff_id}</option>)}</select></label>
            {kind === 'ORDER_CANCELLED' && <label className="field-label">Причина<select value={reason} onChange={(e) => setReason(e.target.value)}><option value="NOT_CONFIRMED">Клиент не подтвердил визит</option><option value="CUSTOMER_REQUEST">Отказ клиента</option></select></label>}
            {kind === 'VISIT_DELAYED' && <label className="field-label">Ожидаемое окончание<input type="datetime-local" value={expectedEnd} onChange={(e) => setExpectedEnd(e.target.value)} /></label>}
            {kind === 'ORDER_TRANSFERRED' && <label className="field-label">Куда передать<select value={transferTo} onChange={(e) => setTransferTo(e.target.value)}><option value="STATION_EQUIPMENT">Станционное оборудование</option><option value="TRUNK_CABLE">Магистральный кабель</option></select></label>}
          </>}
        </div>
        {kind !== 'STAFF_UNAVAILABLE' && kind !== 'NEW_ORDER' && eligible.length === 0 && <div className="inline-warning">Сейчас нет визитов, подходящих для выбранного типа события. Для задержки или передачи визит должен уже начаться; отменить можно только ещё не начатый визит.</div>}
        <div className="event-time-note">Модельное время события: <strong>{fmtTime(modelTime)}</strong>. Используется время из плана, а не часы компьютера.</div>
        <div className="dialog-actions"><button className="button button-secondary" type="button" onClick={onClose}>Отмена</button>{kind !== 'NEW_ORDER' && <button className="button button-primary" type="button" disabled={loading || (kind !== 'STAFF_UNAVAILABLE' && !orderId) || (kind === 'VISIT_DELAYED' && !expectedEnd)} onClick={() => void submit()}>{loading ? 'Отправка…' : 'Отправить событие'}</button>}</div>
      </section>
    </div>, portalRoot(),
  );
}

function ExpandedLayer({ title, onClose, children }: { title: string; onClose: () => void; children: ReactNode }) {
  return createPortal(
    <div className="overlay-root focus-overlay" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose(); }}>
      <div className="focus-dialog">
        <div className="focus-dialog-bar"><strong>{title}</strong><button className="icon-button" type="button" onClick={onClose}>✕</button></div>
        <div className="focus-dialog-content">{children}</div>
      </div>
    </div>, portalRoot(),
  );
}

export default function App() {
  const [ctx, setCtx] = useState<DayContextResponse | null>(null);
  const [demoEvents, setDemoEvents] = useState<Array<Record<string, unknown>>>([]);
  const [eventIdx, setEventIdx] = useState(0);
  const [profileFilter, setProfileFilter] = useState<ProfileFilter>('ALL');
  const [selectedStaffId, setSelectedStaffId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);
  const [statusNote, setStatusNote] = useState<string | null>(null);
  const [expandedPanel, setExpandedPanel] = useState<ExpandedPanel>(null);
  const [eventDialog, setEventDialog] = useState(false);
  const [createOrderDialog, setCreateOrderDialog] = useState(false);
  const [createOrderStaffId, setCreateOrderStaffId] = useState<string | null>(null);
  const [highlightedOrderId, setHighlightedOrderId] = useState<string | null>(null);

  const openCreateOrder = useCallback((staffId?: string | null) => {
    setCreateOrderStaffId(staffId ?? null);
    setCreateOrderDialog(true);
  }, []);
  const [staffSearch, setStaffSearch] = useState('');
  const [orderSearch, setOrderSearch] = useState('');
  const [orderFilter, setOrderFilter] = useState('ALL');
  const [theme, setTheme] = useState<'light' | 'dark'>(() => {
    try { return (localStorage.getItem('smart-dispatch-theme') as 'light' | 'dark') || 'light'; } catch { return 'light'; }
  });

  const loadContext = useCallback(async (dateStr: string) => {
    const res = await fetch(`/api/v1/ui/days/${dateStr}/context`);
    if (!res.ok) throw new Error(`Ошибка загрузки контекста дня (${res.status})`);
    const data: DayContextResponse = await res.json();
    setCtx(data);
    setSelectedStaffId((current) => current && data.plan.routes.some((route) => route.staff_id === current) ? current : data.plan.routes.find((route) => route.stops.length > 0)?.staff_id ?? data.staff[0]?.staff_id ?? null);
    return data;
  }, []);

  const handleBootstrap = useCallback(async () => {
    setLoading(true); setErrorMsg(null); setStatusNote(null);
    try {
      const res = await fetch('/api/v1/ui/demo/bootstrap?num_orders=120', { method: 'POST' });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(data?.error?.message ?? `HTTP ${res.status}`);
      setDemoEvents(data.demo_events ?? []); setEventIdx(0);
      await loadContext(data.date);
      setStatusNote(`План построен · ${data.plan?.computation_ms ?? 0} мс · ${data.matrix_source === 'OSRM_DRIVING' ? 'дорожная матрица OSRM' : 'резервная матрица'}`);
    } catch (error) {
      setErrorMsg(error instanceof Error ? error.message : 'Не удалось построить план');
    } finally { setLoading(false); }
  }, [loadContext]);

  const handleNextEvent = useCallback(async () => {
    if (!ctx || eventIdx >= demoEvents.length) return;
    setLoading(true); setErrorMsg(null);
    try {
      const event = demoEvents[eventIdx];
      const res = await fetch(`/api/v1/days/${ctx.plan.date}/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event) });
      const body = await res.json();
      if (!res.ok) throw new Error(body?.error?.message ?? `HTTP ${res.status}`);
      setEventIdx((value) => value + 1);
      await loadContext(ctx.plan.date);
      setStatusNote(`Событие принято · план v${body.plan_version} · ${body.processing_ms ?? 0} мс`);
    } catch (error) { setErrorMsg(error instanceof Error ? error.message : 'Ошибка события'); }
    finally { setLoading(false); }
  }, [ctx, demoEvents, eventIdx, loadContext]);

  const handleManualEvent = useCallback(async (event: Record<string, unknown>) => {
    if (!ctx) return;
    setLoading(true); setErrorMsg(null);
    try {
      const response = await fetch(`/api/v1/days/${ctx.plan.date}/events`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(event) });
      const body = await response.json();
      if (!response.ok) throw new Error(body?.error?.message ?? `HTTP ${response.status}`);
      const updatedContext = await loadContext(ctx.plan.date);
      const isNewOrder = event.type === 'NEW_ORDER';
      const orderId = isNewOrder && typeof (event.order as any)?.order_id === 'string' ? (event.order as any).order_id : null;
      if (orderId) {
        const result = orderStatus(orderId, updatedContext);
        if (result.staff) {
          const assignedStaff = updatedContext.staff.find((staff) => staff.staff_id === result.staff);
          if (assignedStaff) setProfileFilter(assignedStaff.profiles.includes('INSTALL') && !assignedStaff.profiles.includes('LTP3') ? 'INSTALL' : 'LTP3');
          setSelectedStaffId(result.staff);
          setHighlightedOrderId(orderId);
          window.setTimeout(() => setHighlightedOrderId((current) => current === orderId ? null : current), 7000);
          setOrderSearch('');
          setOrderFilter('ALL');
          setStatusNote(`Наряд ${orderId} включён в маршрут ${result.staff} · план v${body.plan_version}`);
        } else {
          const unassigned = updatedContext.plan.unassigned.find((item) => item.order_id === orderId);
          setOrderSearch(orderId);
          setOrderFilter('UNASSIGNED');
          setStatusNote(unassigned
            ? `Наряд ${orderId} зарегистрирован, но не назначен: ${unassigned.reason_text}`
            : `Наряд ${orderId} зарегистрирован. Проверьте его статус в реестре.`);
        }
      } else {
        setStatusNote(`Событие зарегистрировано · план v${body.plan_version} · ${body.processing_ms ?? 0} мс`);
      }
      setEventDialog(false);
      setCreateOrderDialog(false);
    } catch (error) { setErrorMsg(error instanceof Error ? error.message : 'Не удалось зарегистрировать событие'); }
    finally { setLoading(false); }
  }, [ctx, loadContext]);

  useEffect(() => {
    try { localStorage.setItem('smart-dispatch-theme', theme); } catch { /* local storage can be unavailable */ }
  }, [theme]);

  useEffect(() => {
    fetch('/api/v1/ui/state').then((response) => response.ok ? response.json() : null)
      .then((state: { has_plan?: boolean; date?: string | null } | null) => {
        if (state?.has_plan && state.date) return loadContext(state.date);
        return undefined;
      }).catch(() => undefined);
  }, [loadContext]);

  useEffect(() => {
    if (!expandedPanel && !eventDialog && !createOrderDialog) return;
    const onKeyDown = (event: KeyboardEvent) => { if (event.key === 'Escape') { setExpandedPanel(null); setEventDialog(false); setCreateOrderDialog(false); } };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [expandedPanel, eventDialog, createOrderDialog]);

  const staffById = useMemo(() => Object.fromEntries((ctx?.staff ?? []).map((staff) => [staff.staff_id, staff])) as Record<string, StaffMember>, [ctx]);
  const routeByStaff = useMemo(() => Object.fromEntries((ctx?.plan.routes ?? []).map((route) => [route.staff_id, route])) as Record<string, Route>, [ctx]);
  const selectedRoute = selectedStaffId ? routeByStaff[selectedStaffId] : undefined;
  const routePalette = useMemo(() => Object.fromEntries((ctx?.plan.routes ?? []).map((route, index) => [route.staff_id, ROUTE_COLORS[index % ROUTE_COLORS.length]])) as Record<string, string>, [ctx]);
  const summary = ctx?.plan.summary;

  const filteredRoutes = useMemo(() => (ctx?.plan.routes ?? []).filter((route) => profileFilter === 'ALL' || staffById[route.staff_id]?.profiles.includes(profileFilter)).sort((a, b) => { const pa = staffById[a.staff_id]?.profiles[0] === 'INSTALL' ? 1 : 0; const pb = staffById[b.staff_id]?.profiles[0] === 'INSTALL' ? 1 : 0; return pa - pb || a.staff_id.localeCompare(b.staff_id); }), [ctx, profileFilter, staffById]);
  useEffect(() => {
    if (!filteredRoutes.length) return;
    if (!selectedStaffId || !filteredRoutes.some((route) => route.staff_id === selectedStaffId)) {
      setSelectedStaffId(filteredRoutes.find((route) => route.stops.length > 0)?.staff_id ?? filteredRoutes[0].staff_id);
    }
  }, [filteredRoutes, selectedStaffId]);

  const filteredStaff = useMemo(() => (ctx?.staff ?? []).filter((staff) => {
    const profileOk = profileFilter === 'ALL' || staff.profiles.includes(profileFilter);
    const searchOk = `${staff.staff_id} ${staff.display_name ?? ''} ${staff.service_center_id}`.toLowerCase().includes(staffSearch.toLowerCase());
    return profileOk && searchOk;
  }).sort((a, b) => { const pa = a.profiles[0] === 'INSTALL' ? 1 : 0; const pb = b.profiles[0] === 'INSTALL' ? 1 : 0; return pa - pb || a.staff_id.localeCompare(b.staff_id); }), [ctx, profileFilter, staffSearch]);
  const allOrders = useMemo(() => Object.values(ctx?.orders ?? {}).sort((a, b) => a.slot.start.localeCompare(b.slot.start)), [ctx]);
  const filteredOrders = useMemo(() => allOrders.filter((order) => {
    const status = ctx ? orderStatus(order.order_id, ctx).label : '';
    const profile = order.work_type_code.startsWith('INST_') || order.work_type_code === 'ADD_SERVICE' ? 'INSTALL' : order.work_type_code === 'SURVEY_PRIVATE' ? 'BOTH' : 'LTP3';
    const profileOk = profileFilter === 'ALL' || profile === 'BOTH' || profile === profileFilter;
    const statusOk = orderFilter === 'ALL' || (orderFilter === 'UNASSIGNED' ? status === 'Не назначен' : orderFilter === 'PGP' ? status === 'Групповая проблема' : orderFilter === 'CANCELLED' ? status === 'Отменён' : orderFilter === 'ASSIGNED' ? status === 'Назначен' || status === 'В работе' || status === 'Выполнен' : true);
    const searchOk = `${order.order_id} ${order.address} ${order.technology} ${order.work_type_code}`.toLowerCase().includes(orderSearch.toLowerCase());
    return profileOk && statusOk && searchOk;
  }), [allOrders, ctx, orderFilter, orderSearch, profileFilter]);

  const assignedCount = summary?.visits_planned ?? 0;
  const completedCount = ctx?.plan.routes.reduce((sum, route) => sum + route.stops.filter((stop) => stop.type === 'VISIT' && stop.status === 'DONE').length, 0) ?? 0;
  const atRiskCount = ctx?.plan.alerts.filter((alert) => alert.type === 'LATE_RISK' && alert.status === 'ACTIVE').length ?? 0;
  const activeStaffCount = filteredRoutes.filter((route) => route.status === 'ACTIVE').length;
  const unassignedCount = summary?.unassigned ?? 0;

  // Keep only one Leaflet instance mounted: expanded mode otherwise duplicates OSRM calls and map state.
  const mapPanel = ctx && expandedPanel !== 'map' && <RouteMap routes={filteredRoutes} serviceCenters={ctx.service_centers} orders={ctx.orders} staffById={staffById} selectedStaffId={selectedStaffId} onSelectStaff={setSelectedStaffId} routePalette={routePalette} onExpand={() => setExpandedPanel('map')} expanded={false} />;
  const ganttPanel = ctx && <WorkloadGantt routes={filteredRoutes} staffById={staffById} selectedStaffId={selectedStaffId} onSelectStaff={setSelectedStaffId} highlightedOrderId={highlightedOrderId} onExpand={() => setExpandedPanel('gantt')} />;

  return (
    <div className="app-shell" data-theme={theme}>
      <header className="topbar">
        <div className="brand-lockup"><img className="brand-logo" src="/rostelecom-mark.png" alt="Логотип Ростелекома" /><div><strong>Ростелеком</strong><span>Smart Dispatch · Екатеринбург</span></div></div>
        <div className="topbar-actions">
          <div className="source-indicator"><span className="live-dot" />{ctx ? 'Смена загружена' : 'Ожидание загрузки'}</div>
          <button className="button button-quiet" type="button" onClick={() => void handleBootstrap()} disabled={loading}>{loading ? 'Расчёт…' : ctx ? '↻ Перезапустить тестовую смену' : 'Загрузить набор'}</button>
          {ctx && (
            <button className="button button-accent" type="button" onClick={() => openCreateOrder(selectedStaffId)} disabled={loading} title="Создать и добавить наряд в график">
              ＋ Добавить наряд
            </button>
          )}
          <button className="button button-primary" type="button" onClick={() => ctx ? setEventDialog(true) : void handleBootstrap()} disabled={loading}>{ctx ? '＋ Зафиксировать событие' : '▶ Построить план'}</button>
          <button className="theme-toggle" type="button" onClick={() => setTheme((value) => value === 'light' ? 'dark' : 'light')} aria-label="Переключить тему" title={theme === 'light' ? 'Тёмная тема' : 'Светлая тема'}><span className="theme-toggle-icon">{theme === 'light' ? '☾' : '☀'}</span><span>{theme === 'light' ? 'Тёмная' : 'Светлая'}</span></button>
        </div>
      </header>

      <main className="dashboard">
        {errorMsg && <div className="error-banner"><strong>Не удалось выполнить действие.</strong> {errorMsg}<button type="button" onClick={() => setErrorMsg(null)}>Закрыть</button></div>}
        {!ctx ? (
          <section className="welcome-card">
            <div className="welcome-icon">⌖</div><div><div className="eyebrow">Smart Dispatch / Екатеринбург</div><h1>Рабочее место диспетчера</h1><p>Загрузите тестовый набор, чтобы построить смену, посмотреть загрузку 40 сотрудников, маршруты, риски и нераспределённые наряды.</p><button className="button button-primary" type="button" onClick={() => void handleBootstrap()} disabled={loading}>{loading ? 'Загружаем и рассчитываем…' : 'Построить тестовый план'}</button></div>
          </section>
        ) : (
          <>
            <section className="kpi-grid">
              <StatCard label="Назначено в план" value={`${assignedCount} / ${summary?.orders_total ?? 0}`} hint={`${completedCount} фактически завершено`} tone="teal" />
              <StatCard label="Время в пути" value={fmtMinutes((summary?.travel_sec_total ?? 0) / 60)} hint="По матрице текущего плана" tone="blue" />
              <StatCard label="Баланс загрузки" value={`CV ${summary?.utilization_cv?.toFixed(3) ?? '0.000'}`} hint="Меньше — равномернее" tone="green" />
              <StatCard label="Риски опоздания" value={String(atRiskCount)} hint="По прогнозу расписания" tone={atRiskCount ? 'amber' : 'green'} />
              <StatCard label="Не распределено" value={String(unassignedCount)} hint={`${summary?.pgp_orders ?? 0} в группах ПГП`} tone={unassignedCount ? 'amber' : 'green'} />
              <StatCard label="План / модельное время" value={`v${ctx.plan.plan_version} · ${fmtTime(ctx.plan.as_of)}`} hint={`${activeStaffCount} сотрудников в смене`} tone="default" />
            </section>

            <section className="command-strip">
              <div className="profile-switch"><span>Профиль:</span>{(['ALL', 'LTP3', 'INSTALL'] as const).map((profile) => <button key={profile} type="button" className={profileFilter === profile ? 'selected' : ''} onClick={() => setProfileFilter(profile)}>{profile === 'ALL' ? 'Все' : profile === 'LTP3' ? '3ЛТП' : 'Инсталляция'}</button>)}</div>
              <div className="command-meta"><span className="status-dot" />{statusNote ?? `Актуальная версия плана v${ctx.plan.plan_version}`}<button className="text-button" type="button" disabled={loading || eventIdx >= demoEvents.length} onClick={() => void handleNextEvent()}>{eventIdx < demoEvents.length ? `Следующее событие сценария ${eventIdx + 1}/${demoEvents.length} →` : 'Сценарий событий завершён'}</button></div>
            </section>

            <section className="dashboard-grid top-grid">
              <div className="panel map-panel">{mapPanel}</div>
              <div className="side-stack">
                <section className="panel staff-panel">
                  <PanelHeader title="Сотрудники" subtitle="Нагрузка считается по работам и времени в пути" count={`${filteredStaff.length} чел.`} onExpand={() => setExpandedPanel('staff')} />
                  <div className="list-toolbar"><input aria-label="Поиск сотрудника" placeholder="Поиск сотрудника…" value={staffSearch} onChange={(e) => setStaffSearch(e.target.value)} /><span>{filteredStaff.length} / {ctx.staff.length}</span></div>
                  <div className="staff-list compact-scroll">
                    {filteredStaff.map((staff) => {
                      const route = routeByStaff[staff.staff_id];
                      const util = Math.round((route?.totals?.utilization ?? 0) * 100);
                      const visits = route?.totals?.visits ?? 0;
                      const isSelected = selectedStaffId === staff.staff_id;
                      return <button key={staff.staff_id} type="button" onClick={() => setSelectedStaffId(staff.staff_id)} className={`staff-row ${isSelected ? 'is-selected' : ''}`}>
                        <span className={`staff-avatar ${staff.profiles[0] === 'INSTALL' ? 'install' : 'ltp'}`}>{staff.profiles[0] === 'INSTALL' ? 'И' : '3'}</span>
                        <span className="staff-main"><strong>{staff.display_name ?? staff.staff_id}</strong><small>{staff.staff_id} · {profileLabel(staff.profiles[0])} · {staff.service_center_id}</small></span>
                        <span className="staff-workload"><span className={`load-number ${util >= 90 ? 'overload' : ''}`}>{util}%</span><span className="load-track"><span style={{ width: `${Math.min(100, util)}%` }} className={util >= 90 ? 'over' : ''} /></span><small>{visits} нар.</small></span>
                      </button>;
                    })}
                  </div>
                </section>
                <section className="panel route-detail-panel">
                  <PanelHeader title="Маршрут сотрудника" subtitle={selectedRoute ? `${selectedRoute.staff_id} · ${profileLabel(staffById[selectedRoute.staff_id]?.profiles[0])}` : 'Выберите сотрудника'} count={selectedRoute ? `${selectedRoute.totals?.visits ?? 0} виз.` : undefined} />
                  {selectedRoute ? <div className="route-stops compact-scroll">
                    {selectedRoute.stops.map((stop) => <RouteStop key={`${selectedRoute.staff_id}-${stop.seq}`} stop={stop} order={stop.order_id ? ctx.orders[stop.order_id] : undefined} />)}
                    {selectedRoute.stops.length === 0 && <div className="empty-state small">У сотрудника пока нет назначенных остановок.</div>}
                  </div> : <div className="empty-state small">Нет выбранного сотрудника.</div>}
                  <div className="route-foot"><span>В дороге: {fmtMinutes((selectedRoute?.totals?.travel_sec ?? 0) / 60)}</span><span>Загрузка: {Math.round((selectedRoute?.totals?.utilization ?? 0) * 100)}%</span></div>
                  <div style={{ display: 'grid', gridTemplateColumns: '1.2fr 1fr', gap: '8px', marginTop: '10px' }}>
                    <button type="button" className="button button-accent button-wide" onClick={() => openCreateOrder(selectedRoute?.staff_id)}>
                      ＋ Наряд сотруднику
                    </button>
                    <button type="button" className="button button-secondary button-wide" onClick={() => setEventDialog(true)}>
                      Проблема
                    </button>
                  </div>
                </section>
              </div>
            </section>

            <section className="panel gantt-panel">{ganttPanel}</section>

            <section className="dashboard-grid bottom-grid">
              <section className="panel orders-panel">
                <PanelHeader
                  title="Наряды на смену"
                  subtitle="Все заявки: назначенные, нераспределённые, ПГП и отменённые"
                  count={`${filteredOrders.length} из ${allOrders.length}`}
                  action={
                    <button className="button button-accent button-sm" type="button" onClick={() => openCreateOrder(null)}>
                      ＋ Добавить наряд
                    </button>
                  }
                  onExpand={() => setExpandedPanel('orders')}
                />
                <div className="list-toolbar orders-toolbar"><input aria-label="Поиск наряда" placeholder="Номер, адрес или технология…" value={orderSearch} onChange={(e) => setOrderSearch(e.target.value)} /><select aria-label="Фильтр статуса" value={orderFilter} onChange={(e) => setOrderFilter(e.target.value)}><option value="ALL">Все статусы</option><option value="ASSIGNED">Назначенные</option><option value="UNASSIGNED">Не распределённые</option><option value="PGP">ПГП</option><option value="CANCELLED">Отменённые</option></select></div>
                <OrdersTable orders={filteredOrders.slice(0, 9)} ctx={ctx} routePalette={routePalette} />
                {filteredOrders.length > 9 && <button className="text-button show-more" type="button" onClick={() => setExpandedPanel('orders')}>Показать все {filteredOrders.length} нарядов →</button>}
              </section>
              <section className="side-stack ops-stack">
                <section className="panel operations-panel">
                  <PanelHeader title="Риски и предупреждения" count={String(ctx.plan.alerts.filter((alert) => alert.status === 'ACTIVE').length)} />
                  <div className="operations-list compact-scroll">
                    {ctx.plan.alerts.filter((alert) => alert.status === 'ACTIVE').slice(0, 5).map((alert) => <AlertRow key={alert.alert_id} alert={alert} onClick={() => { if (alert.order_id) setOrderSearch(alert.order_id); setOrderFilter('ALL'); }} />)}
                    {ctx.plan.alerts.filter((alert) => alert.status === 'ACTIVE').length === 0 && <div className="empty-state small">Активных предупреждений нет.</div>}
                  </div>
                </section>
                <section className="panel operations-panel pgp-panel">
                  <PanelHeader title="Подозрение на групповую проблему" count={String(ctx.plan.pgp_groups.length)} />
                  <div className="operations-list compact-scroll">
                    {ctx.plan.pgp_groups.map((group) => <div className="pgp-row" key={group.group_id}><div><strong>{group.access_node_id}</strong><small>{group.order_ids.length} наряда · выявлено {fmtTime(group.detected_at)}</small></div><StatusPill label="Передача в станцию" tone="purple" /></div>)}
                    {ctx.plan.pgp_groups.length === 0 && <div className="empty-state small">Групповые проблемы не выявлены.</div>}
                  </div>
                </section>
              </section>
            </section>
            <footer className="dashboard-footer"><span>Smart Dispatch · Екатеринбург</span><span>Модельное время: {ctx.plan.as_of} · API v1</span><span className="footer-source">Тестовый набор · заменяется данными организаторов</span></footer>
          </>
        )}
      </main>

      {expandedPanel === 'map' && ctx && <ExpandedLayer title="Карта маршрутов · Екатеринбург" onClose={() => setExpandedPanel(null)}><RouteMap routes={filteredRoutes} serviceCenters={ctx.service_centers} orders={ctx.orders} staffById={staffById} selectedStaffId={selectedStaffId} onSelectStaff={setSelectedStaffId} routePalette={routePalette} onExpand={() => setExpandedPanel(null)} expanded /></ExpandedLayer>}
      {expandedPanel === 'gantt' && ctx && <ExpandedLayer title="Диаграмма загрузки сотрудников" onClose={() => setExpandedPanel(null)}><WorkloadGantt routes={filteredRoutes} staffById={staffById} selectedStaffId={selectedStaffId} onSelectStaff={setSelectedStaffId} highlightedOrderId={highlightedOrderId} expanded /></ExpandedLayer>}
      {expandedPanel === 'staff' && ctx && <ExpandedLayer title="Все сотрудники" onClose={() => setExpandedPanel(null)}><StaffExpanded staff={filteredStaff} routeByStaff={routeByStaff} selectedStaffId={selectedStaffId} onSelect={(id) => { setSelectedStaffId(id); setExpandedPanel(null); }} /></ExpandedLayer>}
      {expandedPanel === 'orders' && ctx && <ExpandedLayer title="Реестр нарядов" onClose={() => setExpandedPanel(null)}><div className="expanded-orders-tools"><input placeholder="Поиск наряда или адреса…" value={orderSearch} onChange={(e) => setOrderSearch(e.target.value)} /><select value={orderFilter} onChange={(e) => setOrderFilter(e.target.value)}><option value="ALL">Все статусы</option><option value="ASSIGNED">Назначенные</option><option value="UNASSIGNED">Не распределённые</option><option value="PGP">ПГП</option><option value="CANCELLED">Отменённые</option></select></div><OrdersTable orders={filteredOrders} ctx={ctx} routePalette={routePalette} expanded /></ExpandedLayer>}
      {eventDialog && ctx && <EventModal ctx={ctx} selectedStaffId={selectedStaffId} onClose={() => setEventDialog(false)} onSubmit={handleManualEvent} onOpenCreateOrder={openCreateOrder} loading={loading} />}
      {createOrderDialog && ctx && <CreateOrderModal ctx={ctx} initialStaffId={createOrderStaffId} onClose={() => setCreateOrderDialog(false)} onSubmit={handleManualEvent} loading={loading} />}
    </div>
  );
}

function RouteStop({ stop, order }: { stop: Stop; order?: OrderRecord }) {
  const typeLabel: Record<string, string> = { DEPOT_START: 'Выезд из СЦ', DEPOT_END: 'Возвращение в СЦ', VISIT: 'Визит к клиенту', BREAK: 'Обед', RESTOCK: 'Пополнение оборудования' };
  return <div className="route-stop"><span className={`stop-icon stop-${stop.type.toLowerCase()}`}>{stop.type === 'VISIT' ? '•' : stop.type === 'BREAK' ? 'Ⅱ' : stop.type === 'RESTOCK' ? '↻' : '⌂'}</span><div className="route-stop-main"><strong>{typeLabel[stop.type] ?? stop.type}</strong><small>{order ? `${order.order_id} · ${workLabel(order.work_type_code)}` : stop.location_id}</small>{order && <small className="muted-text">{order.address}</small>}</div><time>{fmtTime(stop.start)}–{fmtTime(stop.end)}</time></div>;
}

function OrdersTable({ orders, ctx, routePalette, expanded = false }: { orders: OrderRecord[]; ctx: DayContextResponse; routePalette: Record<string, string>; expanded?: boolean }) {
  return <div className={`orders-table-wrap ${expanded ? 'orders-table-expanded' : ''}`}><table className="orders-table"><thead><tr><th>Наряд</th><th>Тип работы</th><th>Адрес</th><th>Слот</th><th>Исполнитель</th><th>Статус</th></tr></thead><tbody>{orders.map((order) => {
    const status = orderStatus(order.order_id, ctx);
    return <tr key={order.order_id}><td className="mono-cell">{order.order_id}</td><td><span className="work-name">{workLabel(order.work_type_code)}</span><small>{order.technology}{order.is_repeat ? ' · повтор' : ''}</small></td><td className="address-cell">{order.address}</td><td className="mono-cell">{fmtTime(order.slot.start)}–{fmtTime(order.slot.end)}</td><td>{status.staff ? <span className="assigned-staff"><i style={{ background: routePalette[status.staff] ?? '#7d8aa3' }} />{status.staff}</span> : '—'}</td><td><StatusPill label={status.label} tone={status.tone} /></td></tr>;
  })}</tbody></table>{orders.length === 0 && <div className="empty-state">По выбранным фильтрам наряды не найдены.</div>}</div>;
}

function AlertRow({ alert, onClick }: { alert: AlertItem; onClick: () => void }) {
  const title = alert.type === 'LATE_RISK' ? 'Риск опоздания' : alert.type === 'PGP_DETECTED' ? 'Выявлена групповая проблема' : 'Наряд не распределён';
  return <button type="button" className="alert-row" onClick={onClick}><span className={`alert-symbol alert-${alert.type.toLowerCase()}`}>!</span><span className="alert-copy"><strong>{title}{alert.order_id ? ` · ${alert.order_id}` : ''}</strong><small>{alert.message}</small></span><span className="alert-time">{fmtTime(alert.created_at)}</span></button>;
}

function StaffExpanded({ staff, routeByStaff, selectedStaffId, onSelect }: { staff: StaffMember[]; routeByStaff: Record<string, Route>; selectedStaffId: string | null; onSelect: (id: string) => void }) {
  return <div className="staff-expanded-list">{staff.map((member) => {
    const route = routeByStaff[member.staff_id]; const util = Math.round((route?.totals?.utilization ?? 0) * 100);
    return <button type="button" key={member.staff_id} className={`staff-expanded-row ${selectedStaffId === member.staff_id ? 'is-selected' : ''}`} onClick={() => onSelect(member.staff_id)}><span className={`staff-avatar ${member.profiles[0] === 'INSTALL' ? 'install' : 'ltp'}`}>{member.profiles[0] === 'INSTALL' ? 'И' : '3'}</span><span className="staff-expanded-name"><strong>{member.display_name ?? member.staff_id}</strong><small>{member.staff_id} · {profileLabel(member.profiles[0])} · {member.service_center_id} · {member.technologies.join(', ')}</small></span><span className="staff-expanded-progress"><span>{util}% загрузки</span><i><b style={{ width: `${Math.min(util, 100)}%` }} /></i></span><span className="staff-expanded-visits">{route?.totals?.visits ?? 0} нарядов</span><StatusPill label={route?.status === 'UNAVAILABLE' ? 'Недоступен' : (route?.totals?.visits ?? 0) > 0 ? 'В плане' : 'Свободен'} tone={route?.status === 'UNAVAILABLE' ? 'danger' : (route?.totals?.visits ?? 0) > 0 ? 'success' : 'neutral'} /></button>;
  })}</div>;
}
