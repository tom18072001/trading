/**
 * One filter vocabulary for every sector table (backlog step 6).
 *
 * Each table had its own answer to "show me less": Money Flow Monitor had a
 * flow_z_hot box, Xếp hạng had nothing, and neither could answer the question
 * a trader actually asks — *which of these do I already own*.
 *
 * State lives in the URL, same reasoning as components/Tabs.tsx: a filtered
 * view is a thing you send to someone, and F5 must not clear it. `replace`
 * so typing in the search box does not stack fifteen history entries.
 */
import type { ReactNode } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useTradingState } from './tradingState';

// Sorting and CSV export live here too: they are the other two things every
// one of these tables was missing, and they read the same URL params.

export type TableFilter = {
  q: string;
  action: string;          // '' = all
  heldOnly: boolean;
  set: (patch: Partial<{ q: string; action: string; heldOnly: boolean }>) => void;
  /** Sector codes in the position book. Empty = nothing held. */
  held: Set<string>;
  active: boolean;
};

export function useTableFilter(prefix = ''): TableFilter {
  const [sp, setSp] = useSearchParams();
  const s = useTradingState();
  const k = (n: string) => (prefix ? `${prefix}_${n}` : n);

  const q = sp.get(k('q')) ?? '';
  const action = sp.get(k('act')) ?? '';
  const heldOnly = sp.get(k('held')) === '1';

  const set = (patch: Partial<{ q: string; action: string; heldOnly: boolean }>) => {
    const next = new URLSearchParams(sp);
    const put = (key: string, v: string) => (v ? next.set(key, v) : next.delete(key));
    if (patch.q !== undefined) put(k('q'), patch.q);
    if (patch.action !== undefined) put(k('act'), patch.action);
    if (patch.heldOnly !== undefined) put(k('held'), patch.heldOnly ? '1' : '');
    setSp(next, { replace: true });
  };

  const held = new Set(s.positions.map((p) => p.sector_code).filter(Boolean));
  return { q, action, heldOnly, set, held, active: !!(q || action || heldOnly) };
}

/** Does one row survive the filter? `action` is optional — flow tables have none. */
export function passes(
  f: TableFilter,
  row: { sector: string; name?: string; action?: string },
): boolean {
  if (f.q) {
    const hay = `${row.sector} ${row.name ?? ''}`.toLowerCase();
    if (!hay.includes(f.q.toLowerCase())) return false;
  }
  if (f.action && (row.action ?? '').toUpperCase() !== f.action) return false;
  if (f.heldOnly && !f.held.has(row.sector)) return false;
  return true;
}

// ---- column sorting -------------------------------------------------------

export type Sorter = {
  key: string;
  dir: 'asc' | 'desc';
  toggle: (key: string) => void;
  /** Sort a copy. Nulls always sink, in both directions. */
  apply: <T extends Record<string, any>>(rows: T[]) => T[];
};

export function useSorter(defaultKey: string, defaultDir: 'asc' | 'desc' = 'asc', prefix = ''): Sorter {
  const [sp, setSp] = useSearchParams();
  const k = (n: string) => (prefix ? `${prefix}_${n}` : n);
  const key = sp.get(k('sort')) || defaultKey;
  const dir = (sp.get(k('dir')) === 'desc' ? 'desc' : sp.get(k('dir')) === 'asc' ? 'asc' : defaultDir);

  const toggle = (next: string) => {
    const sp2 = new URLSearchParams(sp);
    // Same column = flip; new column = start descending, because every
    // numeric column here is one you want biggest-first.
    const nextDir = next === key ? (dir === 'asc' ? 'desc' : 'asc') : 'desc';
    sp2.set(k('sort'), next);
    sp2.set(k('dir'), nextDir);
    setSp(sp2, { replace: true });
  };

  const apply = <T extends Record<string, any>>(rows: T[]): T[] =>
    [...rows].sort((a, b) => {
      const x = a[key], y = b[key];
      if (x == null && y == null) return 0;
      if (x == null) return 1;
      if (y == null) return -1;
      const c = typeof x === 'number' && typeof y === 'number'
        ? x - y : String(x).localeCompare(String(y));
      return dir === 'asc' ? c : -c;
    });

  return { key, dir, toggle, apply };
}

/** A sortable <th>. Click to sort, click again to flip. */
export function Th({
  s, col, align = 'left', children, className = '',
}: {
  s: Sorter; col: string; align?: 'left' | 'right' | 'center';
  children: ReactNode; className?: string;
}) {
  const on = s.key === col;
  // Spelled out, not `text-${align}`: Tailwind scans source text, so an
  // interpolated class name is never generated.
  const al = align === 'right' ? 'text-right' : align === 'center' ? 'text-center' : 'text-left';
  return (
    <th className={`p-2.5 ${al} ${className}`}>
      <button onClick={() => s.toggle(col)}
        className={`inline-flex items-center gap-1 uppercase tracking-wider transition ${
          on ? 'text-hi' : 'hover:text-hi'}`}>
        {children}
        <span className={on ? 'text-acc' : 'opacity-0'}>{s.dir === 'asc' ? '▲' : '▼'}</span>
      </button>
    </th>
  );
}

// ---- CSV ------------------------------------------------------------------

/**
 * Download rows as CSV. Excel on a Vietnamese locale opens UTF-8 as mojibake
 * without the BOM, and these files are full of "Ngân hàng".
 */
export function downloadCsv(filename: string, cols: { key: string; label: string }[], rows: any[]) {
  const cell = (v: any) => {
    const s = v == null ? '' : String(v);
    return /[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s;
  };
  const body = [
    cols.map((c) => cell(c.label)).join(','),
    ...rows.map((r) => cols.map((c) => cell(r[c.key])).join(',')),
  ].join('\r\n');
  const url = URL.createObjectURL(
    new Blob(['﻿' + body], { type: 'text/csv;charset=utf-8' }));
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function FilterBar({
  f, actions, total, shown, onExport,
}: {
  f: TableFilter;
  /** Action values to offer, or null for tables with no action column. */
  actions?: string[] | null;
  total: number;
  shown: number;
  onExport?: () => void;
}) {
  const btn = 'px-2.5 py-1 rounded-md text-[11.5px] font-semibold transition';
  return (
    <div className="flex flex-wrap items-center gap-2.5 rounded-2xl bg-panel border border-line p-3">
      <input
        value={f.q}
        onChange={(e) => f.set({ q: e.target.value })}
        placeholder="Tìm ngành…"
        className="bg-panel2 border border-line rounded-lg px-3 py-1.5 text-[12.5px] text-hi w-44 placeholder:text-lo"
      />

      {actions && actions.length > 0 && (
        <div className="flex rounded-lg bg-panel2 border border-line p-0.5">
          <button onClick={() => f.set({ action: '' })}
            className={`${btn} ${!f.action ? 'bg-raise text-hi' : 'text-mid hover:text-hi'}`}>
            Tất cả
          </button>
          {actions.map((a) => (
            <button key={a} onClick={() => f.set({ action: f.action === a ? '' : a })}
              className={`${btn} ${f.action === a ? 'bg-raise text-hi' : 'text-mid hover:text-hi'}`}>
              {a}
            </button>
          ))}
        </div>
      )}

      <button
        onClick={() => f.set({ heldOnly: !f.heldOnly })}
        disabled={f.held.size === 0}
        title={f.held.size === 0 ? 'Chưa đánh dấu vị thế nào' : `${f.held.size} ngành đang nắm`}
        className={`${btn} rounded-lg border disabled:opacity-40 ${
          f.heldOnly ? 'bg-acc/[0.14] text-acc border-acc/40' : 'bg-panel2 text-mid border-line hover:text-hi'
        }`}
      >
        Chỉ ngành tôi đang nắm{f.held.size > 0 && ` (${f.held.size})`}
      </button>

      <span className="text-[11px] text-lo font-mono ml-auto">
        {shown}/{total}
        {f.active && (
          <button onClick={() => f.set({ q: '', action: '', heldOnly: false })}
            className="ml-2 text-mid hover:text-hi">xoá lọc</button>
        )}
      </span>

      {onExport && (
        <button onClick={onExport}
          className="px-2.5 py-1 rounded-lg bg-panel2 border border-line text-[11.5px] font-semibold text-mid hover:text-hi">
          Xuất CSV
        </button>
      )}
    </div>
  );
}
