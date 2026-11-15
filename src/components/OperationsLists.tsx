import React from 'react';
import type { AlertItem, OrderRecord, PgpGroup, UnassignedOrder } from '../types/dispatch';

interface OperationsListsProps {
  mode: 'alerts' | 'unassigned';
  alerts: AlertItem[];
  pgpGroups: PgpGroup[];
  unassigned: UnassignedOrder[];
  orders: Record<string, OrderRecord>;
}

function fmtTime(iso: string): string {
  const m = iso.match(/T(\d{2}:\d{2})/);
  return m ? m[1] : iso;
}

export const OperationsLists: React.FC<OperationsListsProps> = ({
  mode,
  alerts,
  pgpGroups,
  unassigned,
  orders,
}) => {
  if (mode === 'alerts') {
    return (
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="flex items-center justify-between pb-3 border-b border-slate-200">
            <h2 className="text-base font-semibold text-slate-900">Предупреждения и риски (Alerts)</h2>
            <span className="text-xs text-slate-500 font-mono-nums">{alerts.length}</span>
          </div>
          {alerts.length === 0 ? (
            <p className="text-xs text-slate-500 py-8 text-center">Предупреждений за смену пока нет.</p>
          ) : (
            <div className="divide-y divide-slate-100 max-h-[420px] overflow-y-auto">
              {alerts.map((a) => (
                <div key={a.alert_id} className="py-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-slate-900 font-mono-nums">
                      {a.type} · {a.status === 'RESOLVED' ? 'Решено' : 'Активно'}
                    </span>
                    <span className="text-slate-500 font-mono-nums">{fmtTime(a.created_at)}</span>
                  </div>
                  <p className="text-slate-700 mt-1">{a.message}</p>
                  <p className="text-slate-500 mt-1 font-mono-nums">
                    Рекомендация: {a.suggested_action}
                    {a.suggested_staff_id ? ` -> ${a.suggested_staff_id}` : ''}
                    {a.applied ? ' · Применено автоматически' : ''}
                  </p>
                </div>
              ))}
            </div>
          )}
        </div>

        <div className="bg-white border border-slate-200 rounded-lg p-5">
          <div className="flex items-center justify-between pb-3 border-b border-slate-200">
            <h2 className="text-base font-semibold text-slate-900">Подозрения на групповую проблему (ПГП)</h2>
            <span className="text-xs text-slate-500 font-mono-nums">{pgpGroups.length}</span>
          </div>
          {pgpGroups.length === 0 ? (
            <p className="text-xs text-slate-500 py-8 text-center">Групповых аварий на узлах не выявлено.</p>
          ) : (
            <div className="divide-y divide-slate-100 max-h-[420px] overflow-y-auto">
              {pgpGroups.map((g) => (
                <div key={g.group_id} className="py-3 text-xs">
                  <div className="flex items-center justify-between gap-2">
                    <span className="font-semibold text-slate-900 font-mono-nums">
                      {g.group_id} · Узел {g.access_node_id}
                    </span>
                    <span className="text-slate-500 font-mono-nums">Выявлено {fmtTime(g.detected_at)}</span>
                  </div>
                  <p className="text-slate-700 mt-1">{g.comment ?? 'Передано в станционное подразделение'}</p>
                  <p className="text-slate-500 mt-1 font-mono-nums">Наряды: {g.order_ids.join(', ')}</p>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="bg-white border border-slate-200 rounded-lg p-5">
      <div className="flex items-center justify-between pb-3 border-b border-slate-200">
        <div>
          <h2 className="text-base font-semibold text-slate-900">Нераспределённые наряды</h2>
          <p className="text-xs text-slate-500 mt-0.5">
            Каждый нераспределённый наряд снабжён причиной и предлагаемым действием
          </p>
        </div>
        <span className="text-xs text-slate-500 font-mono-nums">Всего: {unassigned.length}</span>
      </div>

      {unassigned.length === 0 ? (
        <p className="text-xs text-slate-500 py-8 text-center">Все допустимые наряды распределены по маршрутам.</p>
      ) : (
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-left border-collapse text-xs">
            <thead>
              <tr className="border-b border-slate-200 text-slate-500">
                <th className="py-2 pr-4 font-medium">Наряд</th>
                <th className="py-2 pr-4 font-medium">Технология / Адрес</th>
                <th className="py-2 pr-4 font-medium">Код причины</th>
                <th className="py-2 pr-4 font-medium">Пояснение</th>
                <th className="py-2 font-medium">Действие</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100">
              {unassigned.map((u) => {
                const ord = orders[u.order_id];
                return (
                  <tr key={u.order_id} className="hover:bg-slate-50">
                    <td className="py-2.5 pr-4 font-medium text-slate-900 font-mono-nums whitespace-nowrap">
                      {u.order_id}
                    </td>
                    <td className="py-2.5 pr-4 text-slate-600">
                      {ord ? `${ord.technology} · ${ord.address}` : '—'}
                    </td>
                    <td className="py-2.5 pr-4 font-mono-nums text-amber-800 whitespace-nowrap">
                      {u.reason_code}
                    </td>
                    <td className="py-2.5 pr-4 text-slate-700">{u.reason_text}</td>
                    <td className="py-2.5 font-mono-nums text-slate-900 whitespace-nowrap">
                      {u.suggested_action}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
};
