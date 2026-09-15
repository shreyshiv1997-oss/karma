package com.karma.nativeapp

/**
 * Where the API lives. A native app makes real cross-origin HTTP calls (no browser CORS,
 * no reverse proxy), so this is a plain absolute base URL.
 *
 *  - Android emulator reaching a backend on your host:  http://10.0.2.2:8000
 *  - A physical phone on your Wi-Fi:                    http://<your-lan-ip>:8000
 *  - Production:                                        https://api.yourdomain.com
 *
 * The backend must be started with `--host 0.0.0.0` so it is reachable off-loopback.
 */
object ApiConfig {
    const val BASE_URL: String = "http://10.0.2.2:8000"
    const val API_PREFIX: String = "/api/v1"
    val base: String get() = BASE_URL + API_PREFIX
}
