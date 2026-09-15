package com.karma.nativeapp

import org.json.JSONArray
import org.json.JSONObject
import java.io.IOException
import java.net.HttpURLConnection
import java.net.URL

class ApiException(val code: Int, message: String) : IOException(message)

/**
 * A deliberately tiny HTTP boundary: HttpURLConnection + org.json, no Retrofit, no Gson.
 * Zero third-party dependencies means the project builds in Android Studio with nothing to
 * resolve beyond the standard AndroidX artifacts.
 *
 * Every call is synchronous; callers run them on a background executor and post results to the
 * UI thread. Tokens ride along as a Bearer header.
 */
object Api {

    private fun call(
        method: String,
        path: String,
        token: String? = null,
        body: JSONObject? = null,
    ): String {
        val url = URL(ApiConfig.base + path)
        val conn = url.openConnection() as HttpURLConnection
        conn.connectTimeout = 15_000
        conn.readTimeout = 15_000
        conn.requestMethod = method
        conn.setRequestProperty("Accept", "application/json")
        token?.let { conn.setRequestProperty("Authorization", "Bearer $it") }

        if (body != null) {
            conn.doOutput = true
            conn.setRequestProperty("Content-Type", "application/json")
            conn.outputStream.use { it.write(body.toString().toByteArray(Charsets.UTF_8)) }
        }

        val code = conn.responseCode
        val stream = if (code in 200..299) conn.inputStream else conn.errorStream
        val text = stream?.bufferedReader()?.use { it.readText() } ?: ""
        conn.disconnect()

        if (code !in 200..299) throw ApiException(code, detail(text, code))
        return text
    }

    private fun detail(text: String, code: Int): String = try {
        JSONObject(text).optString("detail", "HTTP $code")
    } catch (_: Exception) {
        "HTTP $code"
    }

    // ── auth ────────────────────────────────────────────────────────────
    fun login(identifier: String, password: String): AuthResponse {
        val body = JSONObject().put("identifier", identifier).put("password", password)
        return AuthResponse.from(JSONObject(call("POST", "/auth/login", null, body)))
    }

    fun me(token: String): User =
        User.from(JSONObject(call("GET", "/auth/me", token)))

    /**
     * Ends this device's session on the server.
     *
     * The refresh token rides along because the endpoint can only revoke what it is handed, and an
     * access token expires on its own in an hour anyway -- the thirteen days after that are the part
     * worth killing. The access token is nullable on purpose: this endpoint accepts a sign-out from
     * a client whose access token has already died, which is the common case for a phone left in a
     * pocket, and skipping the call then would leave the refresh token valid. Callers must not treat
     * a failure as a reason to stay signed in.
     */
    fun logout(token: String?, refreshToken: String?) {
        val body = refreshToken?.let { JSONObject().put("refresh_token", it) }
        call("POST", "/auth/logout", token, body)
    }

    // ── feed ────────────────────────────────────────────────────────────
    fun posts(token: String): List<Post> {
        val arr = JSONArray(call("GET", "/feed/posts", token))
        return (0 until arr.length()).map { Post.from(arr.getJSONObject(it)) }
    }

    // ── gigs ────────────────────────────────────────────────────────────
    fun gigs(token: String): List<Gig> {
        val arr = JSONArray(call("GET", "/gigs/mine", token))
        return (0 until arr.length()).map { Gig.from(arr.getJSONObject(it)) }
    }

    // ── karma ───────────────────────────────────────────────────────────
    fun ledger(token: String): KarmaLedger =
        KarmaLedger.from(JSONObject(call("GET", "/karma/ledger", token)))
}
