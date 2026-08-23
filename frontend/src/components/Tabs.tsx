/**
 * In-page tabs, backed by the URL (review §C, 2026-08-23).
 *
 * The nav went from 9 doors to 5. What used to be a separate route is now a
 * tab, so the tab has to live in the URL — otherwise a merged page loses the
 * deep links the old routes had, and a refresh drops you back on tab one.
 *
 * `replace: true` on purpose: switching tabs should not stack history entries
 * that Back has to walk through.
 */
import { useSearchParams } from 'react-router-dom';

export type TabItem = { key: string; label: string };

export function useTab(items: TabItem[], param = 'tab') {
  const [sp, setSp] = useSearchParams();
  const raw = sp.get(param) ?? '';
  const active = items.some((i) => i.key === raw) ? raw : items[0].key;
  const set = (key: string) => {
    const next = new URLSearchParams(sp);
    next.set(param, key);
    setSp(next, { replace: true });
  };
  return [active, set] as const;
}

export function Tabs({
  items,
  active,
  onChange,
}: {
  items: TabItem[];
  active: string;
  onChange: (key: string) => void;
}) {
  return (
    <div className="sticky top-0 z-20 bg-bg/95 backdrop-blur border-b border-line px-8 py-3">
      <div className="max-w-[1240px] mx-auto flex rounded-lg bg-panel2 border border-line p-0.5 w-fit">
        {items.map((i) => (
          <button
            key={i.key}
            onClick={() => onChange(i.key)}
            className={`px-4 py-1.5 rounded-md text-[12.5px] font-semibold transition ${
              active === i.key ? 'bg-raise text-hi shadow-sm' : 'text-mid hover:text-hi'
            }`}
          >
            {i.label}
          </button>
        ))}
      </div>
    </div>
  );
}
