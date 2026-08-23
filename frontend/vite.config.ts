import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    port: 5173,
    // `host: true` binds 0.0.0.0, so Vite advertised EVERY adapter -- including
    // 172.20.16.1, which belongs to the Hyper-V vEthernet switch that WSL and
    // Docker Desktop create. Nothing outside this PC can reach that address, so
    // it was pure noise next to the real LAN one (192.168.1.13, the Wi-Fi card).
    //
    // Localhost only by default. That also matters because the API behind this
    // proxy currently runs with API_REQUIRE_KEY=0 -- putting the dev server on
    // the LAN puts an unauthenticated trading API on the LAN with it.
    //
    // Need it on your phone? `npm run dev:lan` (plain `vite --host`, which
    // overrides this).
    host: 'localhost',
    proxy: {
      '/api': {
        target: 'http://localhost:8000',
        changeOrigin: true,
      },
    },
  },
})
