import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  // React 19.2 ships `act` ONLY in its development build. Vitest runs with
  // NODE_ENV=test, so Vite resolved React's production entry and
  // @testing-library/react fell back to the removed
  // react-dom/test-utils.act -- every render() then died with
  // "TypeError: React.act is not a function". 8 of the 13 frontend tests had
  // been failing this way (CLAUDE.md section 19 counted all 13 as passing).
  //
  // Asking the resolver for the development condition gives RTL the real act.
  resolve: {
    conditions: ['development', 'browser'],
  },
  define: {
    'process.env.NODE_ENV': JSON.stringify('development'),
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    css: false,           // Tailwind classes stay as strings; no need to resolve CSS
    include: ['src/**/*.test.{ts,tsx}'],
    exclude: ['node_modules', 'dist'],
  },
});
