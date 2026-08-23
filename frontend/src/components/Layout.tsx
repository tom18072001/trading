import { NavLink, Outlet } from 'react-router-dom';
import type { ReactNode } from 'react';

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

// Two groups, because they answer different questions. "Theo dõi" is what is
// happening in the market right now; "Ra quyết định" is what the system thinks
// you should do about it and what that would have cost you.
//
// The second group was wired on 2026-08-23. All four pages existed and worked;
// none had a route. CLAUDE.md section 12 lists Rotation Ranking, Regime
// Monitor, Sector Backtest and Risk as deliverables of this redesign.
const nav = [
  { to: '/insight', label: 'Daily Insight', icon: 'insight', end: false, group: 'Theo dõi' },
  { to: '/flow', label: 'Money Flow Monitor', icon: 'flow', end: true, group: 'Theo dõi' },
  { to: '/rotation', label: 'Rotation Map', icon: 'rotation', end: false, group: 'Theo dõi' },
  { to: '/stealth', label: 'Stealth Watch', icon: 'stealth', end: false, group: 'Theo dõi' },
  { to: '/pulse', label: 'Flow Pulse', icon: 'pulse', end: false, group: 'Theo dõi' },
  { to: '/ranking', label: 'Xếp hạng ngành', icon: 'ranking', end: false, group: 'Ra quyết định' },
  { to: '/regime', label: 'Trạng thái thị trường', icon: 'regime', end: false, group: 'Ra quyết định' },
  { to: '/risk', label: 'Rủi ro & Vị thế', icon: 'risk', end: false, group: 'Ra quyết định' },
  { to: '/backtest', label: 'Backtest', icon: 'backtest', end: false, group: 'Ra quyết định' },
];

const navGroups = ['Theo dõi', 'Ra quyết định'] as const;

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
        <nav className="flex-1 px-3 py-4 overflow-y-auto">
          {navGroups.map((group) => (
            <div key={group} className="mb-4 last:mb-0">
              <div className="section-label px-2 mb-2">{group}</div>
              <div className="space-y-1">
                {nav.filter((item) => item.group === group).map((item) => (

              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
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
                <span className="w-[18px] flex items-center justify-center">{ICONS[item.icon]}</span>
                <span>{item.label}</span>
              </NavLink>
                ))}
              </div>
            </div>
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

      <main className="flex-1 overflow-auto bg-bg">
        <Outlet />
      </main>
    </div>
  );
}
