import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// The browser only ever talks to this one origin; /api is proxied to the backend, including
// WebSocket upgrades. No CORS preflight, no exposed API host, one reverse proxy in
// production. The native shell instead points at an absolute origin via VITE_API_ORIGIN
// (see src/api/config.ts), so the same bundle works in both.
export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg', 'favicon-32.png', 'apple-touch-icon.png'],
      manifest: {
        name: 'KARMA — thou art the work you do',
        short_name: 'KARMA',
        description:
          'A trust-first labour marketplace and a social proof network sharing one identity and one reputation ledger.',
        theme_color: '#0B0B0F',
        background_color: '#0B0B0F',
        display: 'standalone',
        orientation: 'portrait',
        start_url: '/',
        icons: [
          { src: '/icons/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/pwa-512.png', sizes: '512x512', type: 'image/png' },
          {
            src: '/icons/maskable-512.png',
            sizes: '512x512',
            type: 'image/png',
            purpose: 'maskable',
          },
        ],
      },
      workbox: {
        // The manifest, icons and hashed chunks are precached by the build; the globs below
        // keep the app shell available fully offline on first visit.
        globPatterns: ['**/*.{js,css,html,svg,woff2}'],
        // Authenticated reads must never be served stale from a cache, and writes must always
        // reach the server. So the API is network-only: offline users see the cached shell and
        // a clean "you are offline" state, never a lie about someone else's data.
        navigateFallback: '/index.html',
        runtimeCaching: [
          {
            urlPattern: ({ url }) => url.pathname.startsWith('/api/'),
            handler: 'NetworkOnly',
          },
          {
            // Static media (icons, imagery) may be cached aggressively.
            urlPattern: ({ request }) => request.destination === 'image',
            handler: 'CacheFirst',
            options: {
              cacheName: 'karma-images',
              expiration: { maxEntries: 64, maxAgeSeconds: 30 * 24 * 3600 },
            },
          },
        ],
      },
    }),
  ],
  server: {
    host: '0.0.0.0',
    port: 5173,
    allowedHosts: true,
    proxy: {
      // `ws: true` is required: the real-time endpoint is mounted under /api/v1, so without
      // it the upgrade request is proxied as plain HTTP and the socket never opens.
      '/api': { target: 'http://localhost:8000', changeOrigin: true, ws: true },
    },
  },
  build: { target: 'es2020', sourcemap: false },
})
