/// <reference types="vite/client" />
/// <reference types="vite-plugin-pwa/client" />

/**
 * The build-time environment KARMA reads.
 *
 * Only these keys are declared, deliberately: `import.meta.env` is a stringly-typed bag that
 * gets inlined at build time, so an undeclared key fails silently as `undefined` rather than
 * as a type error. Declaring them here is what makes a typo in `VITE_API_ORIGIN` a compile
 * failure instead of a native app that cannot reach its backend.
 */
interface ImportMetaEnv {
  /**
   * Absolute API origin for the native shell, e.g. `https://api.karma.example.com`.
   * Empty or unset means "same origin", which is what the web build wants.
   */
  readonly VITE_API_ORIGIN?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
