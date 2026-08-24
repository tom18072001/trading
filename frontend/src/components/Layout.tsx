import { Link, NavLink, Outlet } from 'react-router-dom';
import { useEffect, useState, type ReactNode } from 'react';
import { useTradingState } from '../lib/tradingState';
import { flowApi, type Freshness } from '../api/client';

// ---- Inline stroke icons (18px) ----
const ic = (paths: ReactNode) => (
  <svg
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    {paths}
  </svg>
);

const ICONS: Record<string, ReactNode> = {
  insight: ic(<>
    <path d="M14 3v4a1 1 0 0 0 1 1h4" />
    <path d="M17 21H7a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h7l5 5v11a2 2 0 0 1-2 2z" />
    <path d="M9 9h1M9 13h6M9 17h6" />
  </>),
  flow: ic(<>
    <path d="M3 12h4l3 8 4-16 3 8h4" />
  </>),
  rotation: ic(<>
    <path d="M3 7h11l-3-3M21 17H10l3 3" />
  </>),
  stealth: ic(<>
    <path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z" />
    <circle cx="12" cy="12" r="2.6" />
  </>),
  pulse: ic(<>
    <path d="M3 12h3l2 6 4-14 2 8h2l2-3h3" />
  </>),
  ranking: ic(<>
    <path d="M4 20V10M10 20V4M16 20v-8M22 20h-20" />
  </>),
  regime: ic(<>
    <circle cx="12" cy="12" r="9" />
    <path d="M12 7v5l3.5 2" />
  </>),
  risk: ic(<>
    <path d="M12 3l8 4v6c0 4.5-3.4 7.6-8 8-4.6-.4-8-3.5-8-8V7z" />
    <path d="M12 9v4M12 16h.01" />
  </>),
  backtest: ic(<>
    <path d="M3 3v18h18" />
    <path d="M7 15l4-5 3 3 5-7" />
  </>),
};

// 2026-08-23 (review §C): nav merged 9 → 5. Nine doors for 15 sectors was
// more navigation than data. What merged into what:
//
//   Dòng tiền        = Money Flow Monitor + Sector Detail  (tab, same page)
//   Luân chuyển      = Stealth Watch + Rotation Map        (early vs. already moved)
//   Rủi ro & Vị thế  = Risk + Flow Pulse                   (also kills the §A4 double exposure)
//   Nghiên cứu       = Xếp hạng + Regime + Backtest        (not a daily job)
//
// The groups are gone with them: five items do not need headers, and the
// "Theo dõi / Ra quyết định" split was describing the old nine.
const nav = [
  { to: '/insight', label: 'Daily Insight', icon: 'insight', hint: 'Mở mỗi sáng' },
  { to: '/flow', label: 'Dòng tiền', icon: 'flow', hint: '15 ngành + chi tiết' },
  { to: '/rotation', label: 'Luân chuyển', icon: 'rotation', hint: 'Tiền đi đâu tiếp' },
  { to: '/positions', label: 'Rủi ro & Vị thế', icon: 'risk', hint: 'Đang nắm gì' },
  { to: '/research', label: 'Nghiên cứu', icon: 'backtest', hint: 'Backtest · xếp hạng · regime' },
];

/**
 * §18.4/20 kill-switch banner. Deliberately app-wide and un-dismissable: a
 * halt that you can only see on the page where you set it is a halt you will
 * forget about, and forgetting means acting on picks the 17:00 job has already
 * stopped publishing.
 */
function HaltBanner() {
  const s = useTradingState();
  if (!s.halt_effective) return null;
  return (
    <div className="shrink-0 bg-sell/[0.14] border-b border-sell/40 px-8 py-2 flex items-center gap-3">
      <span className="w-1.5 h-1.5 rounded-full bg-sell animate-dot-pulse shrink-0" />
      <span className="text-[12.5px] font-semibold text-sell">
        TẠM DỪNG GIAO DỊCH — không phát tín hiệu mua mới
      </span>
      {s.halt_reason && <span className="text-[12px] text-sell/80">· {s.halt_reason}</span>}
      {s.halt_env && (
        <span className="text-[11px] font-mono text-sell/70">
          · đặt bằng biến môi trường TRADING_HALT (không tắt được từ giao diện)
        </span>
      )}
      <Link to="/positions?tab=risk"
        className="ml-auto text-[11.5px] font-semibold text-sell hover:underline shrink-0">
        Quản lý →
      </Link>
    </div>
  );
}

/**
 * Review §D — how old is what I am looking at?
 *
 * Every page rendered its own answer or none at all, so a stale DB looked
 * identical to a fresh one on eight of nine routes. One strip, above every
 * page, fetched once. Quiet when fresh — a bar that always shouts is a bar
 * nobody reads; it only takes colour when the data is actually behind.
 */
function DataAgeBar() {
  const [f, setF] = useState<Freshness | null>(null);
  useEffect(() => {
    flowApi.freshness().then((r) => setF(r.data)).catch(() => {});
  }, []);
  if (!f) return null;

  const stale = !f.is_fresh && f.gap_days > 0;
  return (
    <div className={`shrink-0 px-8 py-1.5 border-b flex items-center gap-2 text-[11.5px] font-mono ${
      stale ? 'bg-warn/[0.10] border-warn/35 text-warn' : 'border-line text-lo'}`}>
      <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${stale ? 'bg-warn' : 'bg-buy/70'}`} />
      <span>Dữ liệu đến {f.latest_date || '—'}</span>
      {stale ? (
        <span className="font-semibold">
          · chậm {f.gap_days} phiên so với {f.last_trading_day} — chạy lại job EOD trước khi ra quyết định
        </span>
      ) : (
        <span>· phiên gần nhất {f.last_trading_day}{f.is_weekend && ' · cuối tuần'}</span>
      )}
    </div>
  );
}

export default function Layout() {
  return (
    <div className="flex h-screen bg-bg text-hi font-body">
      <aside className="w-[236px] shrink-0 bg-sidebar border-r border-line flex flex-col sticky top-0 h-screen">
        {/* Logo block */}
        <div className="px-4 py-5 border-b border-line">
          <div className="flex items-center gap-2.5">
            <div
              className="w-[34px] h-[34px] rounded-[9px] flex items-center justify-center font-display font-bold text-bg text-[15px]"
              style={{
                background: 'linear-gradient(140deg, #46C9E6, #2C9C8E)',
                boxShadow: '0 4px 14px rgba(70,201,230,.25)',
              }}
            >
              V
            </div>
            <div className="leading-tight">
              <h1 className="font-display font-bold text-[15px] text-hi tracking-tight">
                VN Sector Flow
              </h1>
              <p className="text-[10px] text-lo -mt-0.5">Rotation · Money Flow · Regime</p>
            </div>
          </div>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 overflow-y-auto space-y-1">
          {nav.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `relative flex items-center gap-2.5 rounded-[9px] px-3 py-2.5 text-[13px] font-medium transition-all ${
                  isActive
                    ? 'text-acc border border-acc/[0.22]'
                    : 'text-mid border border-transparent hover:bg-white/[0.04] hover:text-hi'
                }`
              }
              style={({ isActive }) =>
                isActive
                  ? {
                      background: 'linear-gradient(90deg, rgba(70,201,230,.13), transparent)',
                      boxShadow: 'inset 2.5px 0 0 0 #46C9E6',
                    }
                  : undefined
              }
            >
              <span className="w-[18px] flex items-center justify-center shrink-0">{ICONS[item.icon]}</span>
              <span className="leading-tight">
                {item.label}
                <span className="block text-[10px] text-lo font-normal">{item.hint}</span>
              </span>
            </NavLink>
          ))}
        </nav>

        {/* Footer status */}
        <div className="px-4 py-3.5 border-t border-line">
          <div className="flex items-center gap-2">
            <span className="w-1.5 h-1.5 rounded-full bg-buy animate-dot-pulse" />
            <span className="text-[11px] text-mid font-mono">api · localhost:8000</span>
          </div>
          <p className="text-[10px] text-lo mt-1">15 sectors · top-5 proxy basket</p>
        </div>
      </aside>

      <main className="flex-1 overflow-auto bg-bg flex flex-col">
        <HaltBanner />
        <DataAgeBar />
        <div className="flex-1">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
