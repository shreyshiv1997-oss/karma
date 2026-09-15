/**
 * The native shell, kept to one thin module so the web build never pays for it in logic.
 *
 * Everything here is a no-op in a browser tab. In the Capacitor shell it is what makes the app
 * feel native rather than "a website in a box": the splash is held until React has painted (no
 * flash of unstyled shell), the status bar matches the ink chrome, the Android hardware back
 * button walks the hash router instead of nuking the app, and meaningful moments get haptics.
 *
 * The web has equivalents for all of this (scroll, focus, history) — this module is only the
 * bridge to platform affordances the browser cannot reach.
 */
import { Capacitor } from '@capacitor/core'
import { App as CapApp } from '@capacitor/app'
import { StatusBar, Style } from '@capacitor/status-bar'
import { SplashScreen } from '@capacitor/splash-screen'
import { Haptics, ImpactStyle } from '@capacitor/haptics'

/** True inside the Capacitor WebView, false in every browser tab. */
export const isNative = Capacitor.isNativePlatform()

/**
 * Bring the platform chrome in line with the design system. Called once at mount.
 */
export async function initNativeShell(): Promise<void> {
  if (!isNative) return

  try {
    // Light glyphs over the ink background, and let the WebView draw under the bar so the
    // app feels edge-to-edge. The layout already reserves space via env(safe-area-inset-*).
    await StatusBar.setStyle({ style: Style.Dark })
    await StatusBar.setBackgroundColor({ color: '#0B0B0F' })
  } catch {
    /* Chrome decoration is cosmetic; never let it break the app. */
  }

  try {
    // Android hardware back: walk the hash router the same way a link would, and only leave
    // the app when there is nowhere left to go. Without this, back kills the WebView.
    CapApp.addListener('backButton', () => {
      const { hash } = window.location
      if (hash && hash !== '#/' && hash !== '#/feed') {
        window.location.hash = '#/feed'
      } else {
        void CapApp.minimizeApp()
      }
    })
  } catch {
    /* Not fatal. */
  }
}

/** Hide the splash once the first meaningful paint is up. */
export async function hideSplash(): Promise<void> {
  if (!isNative) return
  try {
    await SplashScreen.hide({ fadeOutDuration: 200 })
  } catch {
    /* Already hidden or unavailable. */
  }
}

/**
 * A quiet tick of feedback for moments that matter — a gig completed, karma earned.
 * Haptics are the mobile replacement for the celebration motion the web gets.
 */
export function hapticCelebration(): void {
  if (!isNative) return
  void Haptics.impact({ style: ImpactStyle.Medium }).catch(() => undefined)
}

export function hapticTap(): void {
  if (!isNative) return
  void Haptics.impact({ style: ImpactStyle.Light }).catch(() => undefined)
}
