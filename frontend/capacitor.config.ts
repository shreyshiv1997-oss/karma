import type { CapacitorConfig } from '@capacitor/cli'

/**
 * The native shell around the same React bundle that ships to the web.
 *
 * `webDir` is Vite's output, so the native build and the PWA are, byte for byte, the same app —
 * there is no second frontend to maintain. That is the whole point.
 *
 * `androidScheme: 'https'` serves the WebView from `https://localhost`, which matters twice:
 * the WebCrypto and secure-context APIs the auth layer leans on stay available, and the
 * same-origin assumption in `src/api/config.ts` can detect "I am native" from the origin.
 *
 * The API origin itself is baked at build time (VITE_API_ORIGIN) when the native bundle is
 * produced — see mobile/README.md. There is no reverse proxy inside a phone.
 */
const config: CapacitorConfig = {
  appId: 'com.karma.app',
  appName: 'KARMA',
  webDir: 'dist',
  backgroundColor: '#0B0B0F',
  server: {
    androidScheme: 'https',
  },
  android: {
    // No pinch-zoom surprises on form fields, but accessibility zoom stays available to the OS.
    allowMixedContent: false,
  },
  plugins: {
    SplashScreen: {
      launchShowDuration: 400,
      launchAutoHide: false, // the app hides it once React is mounted — no flash of unstyled shell
      backgroundColor: '#0B0B0F',
      showSpinner: false,
      androidSplashResourceName: 'splash',
      splashFullScreen: true,
      splashImmersive: true,
    },
    StatusBar: {
      style: 'DARK', // light glyphs on the ink background
      backgroundColor: '#0B0B0F',
      overlaysWebView: false,
    },
  },
}

export default config
