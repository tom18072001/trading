# Handoff: VN Sector Flow — Front-end Redesign

## Overview
Complete visual redesign of the **VN Sector Flow** trading terminal — a tool that tracks
sector money-flow rotation on HOSE and produces a daily MUA/BÁN (buy/sell) decision list
optimized for **T+3** swing trades (buy today, sellable from T+3 per HOSE settlement).

The redesign covers all 5 views + the shared app shell:
1. **Daily Insight** (priority) — the buy/sell decision cockpit
2. **Money Flow Monitor** — where is money flowing, how strong
3. **Rotation Map** — which sector → which sector
4. **Stealth Watch** — quiet accumulation + breakout lead-time
5. **Flow Pulse** — live intraday tape + alerts + exposure

Visual direction: **modern dark fintech** — airy spacing, strong typographic hierarchy,
restrained color (green=buy, red=sell, amber=stealth/caution, cyan=interactive accent).

## About the Design Files
The files in this bundle are **design references created as self-contained HTML prototypes**
(`.dc.html`). They show the intended look, layout, and interaction behavior — they are **not
production code to copy directly**.

The task is to **recreate these designs inside the existing codebase** at
`Trading/frontend/` — a **React + TypeScript + Vite + react-router + Tailwind CSS** app — using
its established patterns. Each prototype maps 1:1 to an existing page component (see *Files &
Mapping* below). Replace the JSX/Tailwind markup of those pages while keeping the existing API
client calls (`insightApi.daily()`, `/api/flow/*`, `/api/rotation/*`, `/api/stealth/*`,
`/api/pulse/*`) and data shapes from the specs in `Trading/specs/`.

> The prototypes inline all mock data in a `state.data` object at the top of each file's logic
> class. In the real app, that object is replaced by the API response (shapes already match the
> specs). Treat the mock object as the data contract / prop shape.

## Fidelity
**High-fidelity (hifi).** Final colors, typography, spacing, and interactions are specified
below to exact values. Recreate pixel-faithfully using the codebase's Tailwind setup. Where a
value below is given as a hex/px, use it directly (add the tokens to the Tailwind theme or use
arbitrary values).

---

## Design Tokens

### Color
| Token | Hex | Use |
|---|---|---|
| `bg` | `#0A0D12` | app background |
| `sidebar` | `#0C1016` | sidebar background |
| `panel` | `#11151C` | card / section background |
| `panel2` | `#161B24` | nested / table-header background |
| `raise` | `#1C222D` | chips, raised tiles |
| `line` | `rgba(255,255,255,.07)` | hairline borders |
| `line2` | `rgba(255,255,255,.13)` | stronger borders |
| `hi` | `#EAF0F7` | primary text |
| `mid` | `#909DAF` | secondary text |
| `lo` | `#5A6573` | tertiary / labels |
| `buy` | `#33D49A` | BUY / inflow / positive |
| `buy-dim` | `rgba(51,212,154,.13)` | buy backgrounds |
| `sell` | `#FF5D73` | SELL / outflow / negative |
| `sell-dim` | `rgba(255,93,115,.13)` | sell backgrounds |
| `warn` | `#F5B13D` | stealth / caution |
| `warn-dim` | `rgba(245,177,61,.12)` | warn backgrounds |
| `acc` | `#46C9E6` | interactive accent / links / active nav |
| `acc-dim` | `rgba(70,201,230,.13)` | accent backgrounds |

Multi-line chart sector palette (Money Flow): CHEM `#33D49A`, REAL `#46C9E6`, OIL `#7FB2FF`,
POWER `#B98BFF`, INSUR `#F5B13D`, TECH `#7A8696`, FOOD `#5CCFB8`, STEEL `#E08A6B`,
BANK `#FF8FA0`, TEXT `#FF5D73`.

### Typography
- **Display / headings / tickers**: `Space Grotesk` (600/700). Page titles 29px/700, letter-spacing −0.02em. Symbols & big numbers 14–24px/700.
- **Body / UI**: `Manrope` (400/500/600/700). Body 13–14px, secondary 11–12px.
- **Numbers / tabular / mono**: `JetBrains Mono` (400/500/600) with `font-variant-numeric: tabular-nums`. All prices, z-scores, %, timestamps.
- Section labels: 10.5px / 700 / uppercase / letter-spacing 0.15em / color `lo`.

### Spacing / radius / shadow
- Page padding: 30–36px. Section gap: 22px. Card padding: 22px (comfortable) / 16px (compact).
- Radius: sections/cards 16px · chips/tiles 8–11px · pills 6–8px · sidebar items 9px.
- Shadow: tiles/active tabs `0 1px 3px rgba(0,0,0,.3)`; logo `0 4px 14px rgba(70,201,230,.25)`.
- Custom scrollbar: 9px, thumb `#232A35` with 2px `bg` border.

### Shared app shell
- Layout: fixed **236px** sidebar (`sidebar` bg, sticky full-height) + scrolling `main`.
- Sidebar: logo block (34px gradient-square mark `linear-gradient(140deg, acc, #2C9C8E)` + wordmark "VN Sector Flow" / subtitle "Rotation · Money Flow · Regime"), section label "PHÂN TÍCH", 5 nav links, footer status (pulsing green dot + `api · localhost:8000` / `15 sectors · top-5 proxy basket`).
- Nav item: icon (18px stroke SVG) + label, 9px radius, 9/12px padding. **Active**: color `acc`, bg `linear-gradient(90deg, acc-dim, transparent)`, 1px `rgba(70,201,230,.22)` border, 2.5px accent bar on the left edge. **Inactive**: color `mid`, hover bg `rgba(255,255,255,.04)` + color `hi`.
- Page header: 29px title + `mid` subtitle, right side holds page-specific controls (date badge, regime pill, refresh, live clock).

---

## Screens / Views

### 1. Daily Insight  → `src/pages/DailyInsightPage.tsx`
**Purpose:** answer "hôm nay mua mã nào, bán mã nào" and execute within T+3.

**Layout (top→bottom, gap 22px):**
- **Header**: title + date badge; subtitle with colored MUA/BÁN/T+3 words; "cập nhật {timestamp}". Right: **Refresh** button (cyan gradient, spinning icon while running) with async-stage progress bar (stages: queued → publishing_signals → rebuilding_universe → trader_agent → assembling → done; % + stage label).
- **Data-quality banner** (when `freshness.is_valid === false`): amber gradient strip, warning triangle, `ohlcv_fail % ≥ 25%` meta.
- **Decision cockpit**: `grid 300px / 1fr`. Left = **regime gauge** (SVG semicircle, red/slate/green arcs, needle angle from market score; label + confidence % + "Tư thế phòng thủ" pill). Right = 3 count tiles (NÊN MUA / NÊN BÁN / TÍCH LUỸ NGẦM) each with a faint diagonal color wash, 42px/700 number.
- **Sector flow spectrum**: a horizontal axis from "◄ DÒNG TIỀN RA" (red) to "DÒNG TIỀN VÀO ►" (green); sector dots positioned by `flow_z20` (`left% = (z+3)/6*100`), dot size larger for |z|>2, colored glow ring; below it 3 delta cards (inflow/outflow/stealth) each with an SVG sparkline + sector + metric + "→ what to do".
- **Trader Agent — Minh**: panel with `linear-gradient(135deg, panel, rgba(70,201,230,.04))`, cyan border; avatar "M" square, model·ms·$cost meta, 15px/600 gist, regime comment, accent "Phân bổ" note box.
- **Action list (picks)**: toolbar with **capital slider** ("Vốn" 50–500tr) + **view toggle** (Thẻ / Bảng / Timeline T+3). Three layouts of the same buy/sell picks:
  - **Thẻ (cards, default)**: 2-col grid. Each card: symbol (22px), sector chip, sector name, MUA/BÁN badge + conviction stars (amber). BUY cards show a **price ladder** (vertical track, target line green / stop line red / current dot) + **T+3 schedule** (4 day chips T0→T+3, T0 highlighted cyan, T+3 "Bán được" highlighted green) + sizing row (R:R, phân bổ tr, rủi ro tối đa). SELL cards show a red stop-out caution block. Then technical-bit chips, thesis, risk bullets (⚠), and an expandable news drawer.
  - **Bảng (table)**: compact row grid — Mã+badge / Ngành / luận điểm (truncated) / Giá / Entry / Target / Stop / R:R.
  - **Timeline T+3**: 4 day columns header (T0 18/6 … T+3 23/6); one lane per BUY with a flow bar from "Mua {entry}" (pinging cyan dot) to "Chốt {target}" (green dot).
- **Footer disclaimer** (10.5px `lo`).

**Pick data shape** (each item): `{ side:'BUY'|'SELL', symbol, sector, sector_name, conviction(0-5), entry, target, stop, current, rr, bits:[], thesis, risks:[], news:[{title,source,published}] }`. T+3 schedule shared per day: `{label,date,sub,state:'now'|'future'|'sell'}`.

**Sizing math:** deployable = capital × 0.5; per-buy alloc = deployable × conviction / Σconviction; risk = alloc × (entry−stop)/entry; shares would be alloc×1000/entry (price in nghìn VND).

**Tweakable props:** `accent` (color, default `#46C9E6`), `density` (`comfortable`|`compact`), `showSizing` (boolean).

### 2. Money Flow Monitor  → `src/pages/FlowMonitorPage.tsx`
**Purpose:** where money is flowing and how strong.
**Layout:** interval toggle (`1D 1W 2W 1M 1Q`) + threshold legend → **multi-line z-chart** (SVG `viewBox 0 0 1000 320`, `preserveAspectRatio=none`, `vector-effect=non-scaling-stroke`; zero line + dashed ±1σ amber / ±2σ red threshold lines; y maps `z` via `y = 160 − z*46.667`; clicking a sector in the legend highlights its line (strokeWidth 3, others opacity .18)) → **heat strip** (15 rows × 24 cells, each cell colored by z: green/red alpha = `0.08 + min(1,|z|/3)*0.62`) → **ranking table** (#, Ngành+dot, Score, Flow z20, Foreign, Breadth, ATR%, Action chip, Why chips; row click selects sector & tints row).
**Action chip colors:** BUY=buy, ACCUMULATE=warn, SELL=sell, HOLD=mid/raise.

### 3. Rotation Map  → `src/pages/RotationMapPage.tsx`
**Purpose:** money moving FROM → TO which sector.
**Layout:** header (window + min Δz pill) → **Sankey** (SVG `viewBox 0 0 1000 420`; sources left x≈156, targets right x≈830, 14px node rects; ribbon = filled bezier path, height ∝ link weight × scale, color = source color, opacity .34 default / .07 dimmed / .7 selected; node labels = code + Δshare% colored by sign) → **pair table** (#, From→To with colored dots + arrow, Δz source (red), Δz target (green), Bắt đầu, Tuổi, Persist·lag, Corr, Trạng thái chip CONFIRMED/EMERGING/FADING). Clicking a pair row filters the matching ribbon.
**Sankey layout algorithm** is in the prototype's `renderVals()` — port the `layout(order, totals, x)` + ribbon path builder verbatim (it balances source/target band cursors).

### 4. Stealth Watch  → `src/pages/StealthWatchPage.tsx`
**Purpose:** quiet accumulation + breakout lead-time estimate.
**Layout:** **Gantt timeline** (30-phiên window; one row per sector; event bar `left% = start/30*100`, `width% = age/30*100`; active = bright amber, resolved = dim amber; x-axis ticks 20/5…hôm nay 18/6) → **Active / Warming tabs** → **active cards** (3-col grid; symbol+name, stealth score, **5-condition gate** rows each with ✓/✕ circle + label + value, persistence progress bar `X/5 phiên`, cyan "Dự kiến breakout ~Nd (range)" box) / **warming cards** (passing/5 gate + highest flow_z + progress) → **history table** (Ngành, Bắt đầu, Kết thúc, Peak return, Lead, classification chip HIT/FALSE POSITIVE/DRY-POWDER TIMEOUT).
**5 gate conditions:** flow_z20 > +1σ · foreign_hit ≥ 60% · breadth SMA20 rising · ATR rank ≤ 0.5 · price in bottom 40% of 60d range.

### 5. Flow Pulse  → `src/pages/FlowPulsePage.tsx`
**Purpose:** live intraday tape + alerts + open exposure.
**Layout:** header with **LIVE** pill (pinging dot) + ticking clock → **alerts ticker** (newest first; ts / sector / message / event tag; green for up-cross, red for down/extreme) → **live tape** (row per sector sorted by z: code, Δshare with ▲/▼ arrow, flow z20 + Δ1h, foreign streak badge, **signal chip** ALERT↑/ALERT↓/NEUTRAL, 20-bar sparkline; rows with alert tinted) → **open exposure table** (Ngành·Mã, Side, Tỉ trọng, Vào lệnh, Lãi/Lỗ, Cách stop) → **VaR/CVaR panel** (collapsed by default; expands to 4 tiles: VaR 95%, CVaR 95%, Max drawdown 30d, Tổng exposure).
**Live behavior:** poll every ~30s in production (prototype simulates every 2.6s): perturb each z, shift sparkline, recompute arrows/deltas; when a z crosses the alert threshold (default 1.5σ) upward, prepend a new alert (cap 7). Clock updates every 1s.

---

## Interactions & Behavior
- **Nav**: standard router links; active state per route (see shell tokens). Prototype uses `<a href>` between files — in app use `<NavLink>` (already in `Layout.tsx`).
- **Daily Insight refresh**: fire async pipeline, poll `/insight/refresh/status` every 2s, show stage label + progress %; drop final payload into page state (logic already in current `DailyInsightPage.tsx` — keep it, restyle UI).
- **View toggle / tabs**: instant local state, active tab = `raise` bg + shadow.
- **Capital slider**: `onInput` updates capital → recompute alloc/risk live.
- **News drawer / VaR panel**: local open/close boolean, caret ▸/▾.
- **Chart/legend/pair/row selection**: local `selected` state; highlight + dim siblings.
- **Transitions**: progress bar width `.5s cubic-bezier(.4,0,.2,1)`; button/link `all 150ms`. Keyframes: `dotPulse` (status dot), `livePing` / `nowPing` (live & T0 markers), `spin` (refresh icon), `fadeUp` (card enter).

## State Management
- Per-page local React state only (no global store needed):
  - Daily Insight: `data, refreshing, refreshStage, refreshPct, pickView, openNews{}, capital`.
  - Money Flow: `interval, selected`.
  - Rotation: `selected` (pair key).
  - Stealth: `tab` (active|warming).
  - Flow Pulse: `clock, rows[], alerts[], varOpen` + two intervals (clock 1s, tick ~2.6s sim / 30s real).
- Data fetching: reuse existing `src/api/client.ts` calls; data shapes match `Trading/specs/*.md`.

## Assets
- No raster assets. All icons are inline stroke SVGs (logo mark, nav icons, gauge, sankey, sparklines, arrows). Reuse or move to an `Icon` component.
- Fonts via Google Fonts: `Space Grotesk`, `Manrope`, `JetBrains Mono` (already easy to add to `index.html` or `@import`).

## Files & Mapping
Design references in this bundle (open in any browser):
| Prototype file | Recreate in |
|---|---|
| `Daily Insight.dc.html` | `src/pages/DailyInsightPage.tsx` |
| `Money Flow Monitor.dc.html` | `src/pages/FlowMonitorPage.tsx` |
| `Rotation Map.dc.html` | `src/pages/RotationMapPage.tsx` |
| `Stealth Watch.dc.html` | `src/pages/StealthWatchPage.tsx` |
| `Flow Pulse.dc.html` | `src/pages/FlowPulsePage.tsx` |
| shared sidebar/shell (in every file) | `src/components/Layout.tsx` |

> Each `.dc.html` is a streaming "Design Component": markup lives between conceptual `<x-dc>`
> tags, logic in a `class Component`. Read the inline `style="..."` for exact values and the
> `renderVals()` method for the derived/computed data (gauge math, sankey layout, sizing,
> spark/heat color functions) — port those helpers directly to TS.
