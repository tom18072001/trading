/**
 * UI tests for DailyInsightPage.
 *
 * Scope:
 *   - Pure helpers (fmtNum, fmtPct)
 *   - AgentReport card rendering (valid + invalid + error states)
 *   - PickTable rendering (BUY vs SELL columns, rows, collapsible news)
 *
 * Out of scope: the full DailyInsightPage component (fetches via axios; tested
 * via the E2E preview harness instead).
 */
import { describe, it, expect } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/react';

import {
  fmtNum,
  fmtPct,
  AgentReport,
  PickTable,
} from './DailyInsightPage';

// ---------------- formatters ----------------

describe('fmtNum', () => {
  it('returns em-dash for null / undefined / NaN', () => {
    expect(fmtNum(null)).toBe('—');
    expect(fmtNum(undefined)).toBe('—');
    expect(fmtNum(NaN)).toBe('—');
  });

  it('formats numbers using vi-VN locale', () => {
    // vi-VN uses "." as thousands separator and "," as decimal. 1234.5 → "1.234,5"
    expect(fmtNum(1234.5)).toBe('1.234,5');
  });

  it('respects the digit limit', () => {
    expect(fmtNum(1.23456, 2)).toBe('1,23');
  });
});

describe('fmtPct', () => {
  it('signs positive numbers with + and keeps negatives', () => {
    expect(fmtPct(5.2)).toBe('+5.20%');
    expect(fmtPct(-3.1)).toBe('-3.10%');
  });

  it('returns em-dash for null', () => {
    expect(fmtPct(null)).toBe('—');
  });
});

// ---------------- AgentReport ----------------

describe('AgentReport', () => {
  it('renders nothing when no report', () => {
    const { container } = render(<AgentReport report={null} />);
    expect(container.firstChild).toBeNull();
  });

  it('shows fallback card when agent invalid', () => {
    render(<AgentReport report={{ is_valid: false, error: 'no JSON block' }} />);
    expect(screen.getByText(/chưa sẵn sàng/i)).toBeInTheDocument();
    expect(screen.getByText(/no JSON block/)).toBeInTheDocument();
  });

  it('renders gist, regime comment, buys, avoid, and portfolio note', () => {
    const report = {
      is_valid: true,
      model: 'claude-sonnet-4-6',
      duration_ms: 1234,
      cost_usd: 0.12,
      gist: 'Thị trường chop, chỉ STEEL & TECH nổi bật',
      regime_comment: 'Dòng tiền hẹp, giữ cash nhiều.',
      top_buys: [
        {
          symbol: 'HPG', sector: 'STEEL', action: 'BUY', conviction: 4,
          entry: 28.0, target: 30.0, stop: 26.5, rr: 1.5,
          reasoning: 'STEEL dẫn đầu, momentum xác nhận.',
          risks: ['macro tightening'],
        },
      ],
      avoid: [
        {
          symbol: 'PC1', sector: 'POWER', action: 'AVOID', conviction: 4,
          entry: null, target: null, stop: 25.1, rr: null,
          reasoning: 'Dilution risk, tránh.',
        },
      ],
      portfolio_note: '50% cash, 30% STEEL, 20% TECH.',
    };
    render(<AgentReport report={report} />);

    // Model + cost header shows up
    expect(screen.getByText(/claude-sonnet-4-6/)).toBeInTheDocument();
    expect(screen.getByText(/\$0\.120/)).toBeInTheDocument();

    // VN narrative pieces
    expect(screen.getByText(report.gist)).toBeInTheDocument();
    expect(screen.getByText(report.regime_comment)).toBeInTheDocument();

    // BUY card — ticker + conviction stars (★★★★☆ shown in both BUY + AVOID
    // cards when convictions match; use getAllByText to allow that).
    expect(screen.getByText('HPG')).toBeInTheDocument();
    expect(screen.getAllByText(/★★★★☆/).length).toBeGreaterThanOrEqual(1);

    // Entry / target / stop rendered
    expect(screen.getByText(/Entry/)).toBeInTheDocument();

    // Risks chip
    expect(screen.getByText(/macro tightening/i)).toBeInTheDocument();

    // AVOID card
    expect(screen.getByText('PC1')).toBeInTheDocument();
    expect(screen.getByText(/Dilution risk/i)).toBeInTheDocument();

    // Portfolio note
    expect(screen.getByText(/50% cash, 30% STEEL/)).toBeInTheDocument();
  });
});

// ---------------- PickTable ----------------

describe('PickTable', () => {
  const buyPicks = [
    { symbol: 'HPG', sector_code: 'STEEL', sector_name: 'Thép',
      action: 'BUY', close: 28, target: 30, stop: 26.5, rr: 1.5,
      upside_pct: 7, downside_pct: 5, technical_bits: ['RSI 55'],
      thesis: 'momentum', news: [] },
    { symbol: 'NKG', sector_code: 'STEEL', sector_name: 'Thép',
      action: 'BUY', close: 14, target: 16, stop: 13, rr: 1.5,
      upside_pct: 9, downside_pct: 6, technical_bits: ['MACD+'],
      thesis: 'insider buy', news: [] },
  ];

  it('shows empty-state when no picks', () => {
    render(<PickTable title="Top BUY" subtitle="x" kind="BUY" picks={[]} />);
    expect(screen.getByText(/không có ngành/i)).toBeInTheDocument();
  });

  it('renders a row per pick with BUY columns', () => {
    render(<PickTable title="BUY" subtitle="x" kind="BUY" picks={buyPicks} />);
    expect(screen.getByText('HPG')).toBeInTheDocument();
    expect(screen.getByText('NKG')).toBeInTheDocument();
    // BUY-specific column headers present
    expect(screen.getByText(/^Target$/)).toBeInTheDocument();
    expect(screen.getByText(/^R:R$/)).toBeInTheDocument();
    // Technical bit chip
    expect(screen.getByText('RSI 55')).toBeInTheDocument();
  });

  it('falls back to legacy field names (price / r_r / sector)', () => {
    const legacy = [
      { symbol: 'BVH', sector: 'INSUR', sector_name: 'Bảo hiểm',
        action: 'BUY', price: 67, target: 71, stop: 65, r_r: 2.1,
        upside_pct: 6, downside_pct: 3, technical_bits: [], thesis: 'flow', news: [] },
    ];
    render(<PickTable title="BUY" subtitle="x" kind="BUY" picks={legacy} />);
    expect(screen.getByText('BVH')).toBeInTheDocument();
    expect(screen.getByText('INSUR')).toBeInTheDocument();
  });

  it('hides news by default and expands on click', () => {
    const withNews = [{
      ...buyPicks[0],
      news: [
        { source: 'KBS', title: 'FPT: Nghị quyết HĐQT 2026',
          url: 'https://example.com/a', published: '2026-03-30T12:25' },
        { source: 'Google News', title: 'Ông Trương Gia Bình: FPT đang tái sinh',
          url: 'https://example.com/b', published: 'Wed, 15 Apr 2026' },
      ],
    }];
    render(<PickTable title="BUY" subtitle="x" kind="BUY" picks={withNews} />);
    expect(screen.queryByText(/Nghị quyết HĐQT 2026/)).toBeNull();

    const toggle = screen.getByRole('button', { name: /tin tức \(2\)/i });
    fireEvent.click(toggle);

    expect(screen.getByText(/Nghị quyết HĐQT 2026/)).toBeInTheDocument();
    expect(screen.getByText(/FPT đang tái sinh/)).toBeInTheDocument();
    expect(screen.getByText('KBS')).toBeInTheDocument();
    expect(screen.getByText('Google News')).toBeInTheDocument();
  });

  it('renders SELL variant with Stop-out / ATR% / Score columns', () => {
    const sellPicks = [
      { symbol: 'PC1', sector_code: 'POWER', sector_name: 'Điện',
        action: 'SELL', close: 26, stop: 25.1, score: -2, atr_pct: 3.4,
        downside_pct: 3.5, technical_bits: [], thesis: 'flow rút', news: [] },
    ];
    render(<PickTable title="SELL" subtitle="x" kind="SELL" picks={sellPicks} />);
    expect(screen.queryByText(/^Target$/)).toBeNull();
    expect(screen.getByText(/Stop-out/i)).toBeInTheDocument();
    expect(screen.getByText(/^Score$/)).toBeInTheDocument();
    expect(screen.getByText(/ATR%/)).toBeInTheDocument();
  });
});
