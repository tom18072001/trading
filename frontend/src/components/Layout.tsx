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
};

const nav = [
  { to: '/insight', label: 'Daily Insight', icon: 'insight', end: false },
  { to: '/flow', label: 'Money Flow Monitor', icon: 'flow', end: true },
  { to: '/rotation', label: 'Rotation Map', icon: 'rotation', end: false },
  { to: '/stealth', label: 'Stealth Watch', icon: 'stealth', end: false },
  { to: '/pulse', label: 'Flow Pulse', icon: 'pulse', end: false },
];

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
          <div className="section-label px-2 mb-2">Phân tích</div>
          <div className="space-y-1">
            {nav.map((item) => (
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
