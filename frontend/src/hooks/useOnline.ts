import { useEffect, useState } from 'react'

/**
 * Live connectivity, from the platform's own events. These fire in the browser *and* in the
 * Capacitor WebView, so one hook serves both without pulling a native plugin into the web
 * bundle. The app uses it to show a calm "you're offline" bar rather than a wall of failed
 * fetches.
 */
export function useOnline(): boolean {
  const [online, setOnline] = useState(() => navigator.onLine)

  useEffect(() => {
    const up = () => setOnline(true)
    const down = () => setOnline(false)
    window.addEventListener('online', up)
    window.addEventListener('offline', down)
    return () => {
      window.removeEventListener('online', up)
      window.removeEventListener('offline', down)
    }
  }, [])

  return online
}
