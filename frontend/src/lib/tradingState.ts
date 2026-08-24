/**
 * One shared copy of the operator state (kill-switch, positions, watchlist).
 *
 * The halt banner lives in Layout, the toggle lives on /positions and the
 * "đã vào lệnh" buttons live on Daily Insight — three trees that never meet.
 * A module-level store read through useSyncExternalStore is React's own answer
 * to that; a Context provider would need Layout to own state it does not use,
 * and a state library would be a dependency for one object.
 *
 * Every mutation returns the whole state from the server, so `set` replaces
 * rather than merges and the client can never drift from the file on disk.
 */
import { useSyncExternalStore } from 'react';
import { stateApi, type PositionPatch, type TradingState } from '../api/client';

const EMPTY: TradingState = {
  halt: false, halt_reason: '', halt_set_at: null,
  halt_env: false, halt_effective: false,
  capital_mn: 100, positions: [], watchlist: [],
};

let state: TradingState = EMPTY;
let loaded = false;
const listeners = new Set<() => void>();

function set(next: TradingState) {
  state = next;
  loaded = true;
  listeners.forEach((l) => l());
}

function subscribe(l: () => void) {
  listeners.add(l);
  if (!loaded) {
    loaded = true;  // one fetch even if ten components mount at once
    stateApi.get().then((r) => set(r.data)).catch(() => {});
  }
  return () => { listeners.delete(l); };
}

export function useTradingState(): TradingState {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

const run = (p: Promise<{ data: TradingState }>) => p.then((r) => { set(r.data); return r.data; });

export const tradingState = {
  setHalt: (halt: boolean, reason = '') => run(stateApi.setHalt(halt, reason)),
  setCapital: (mn: number) => run(stateApi.setCapital(mn)),
  addPosition: (p: { symbol: string; sector_code?: string; side?: 'BUY' | 'SELL'; entry_price?: number | null; note?: string }) =>
    run(stateApi.addPosition(p)),
  updatePosition: (symbol: string, side: 'BUY' | 'SELL', patch: PositionPatch) =>
    run(stateApi.updatePosition(symbol, side, patch)),
  removePosition: (symbol: string, side: 'BUY' | 'SELL' = 'BUY') =>
    run(stateApi.removePosition(symbol, side)),
  toggleWatch: (symbol: string) => run(stateApi.toggleWatch(symbol)),
  reload: () => run(stateApi.get()),
};

/** Is this symbol already held? Used to mark picks you have acted on. */
export function isHeld(s: TradingState, symbol: string, side: 'BUY' | 'SELL' = 'BUY') {
  return s.positions.some((p) => p.symbol === symbol && p.side === side);
}
