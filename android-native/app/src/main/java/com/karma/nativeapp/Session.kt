package com.karma.nativeapp

import android.content.Context
import android.content.SharedPreferences

/**
 * Minimal token store. Access + refresh tokens and a small cached identity live in
 * SharedPreferences. For a production ship you would move the tokens into the Android
 * Keystore / EncryptedSharedPreferences; the interface stays the same.
 */
class Session(context: Context) {
    private val prefs: SharedPreferences =
        context.getSharedPreferences("karma_session", Context.MODE_PRIVATE)

    var accessToken: String?
        get() = prefs.getString("access_token", null)
        set(v) = prefs.edit().putString("access_token", v).apply()

    var refreshToken: String?
        get() = prefs.getString("refresh_token", null)
        set(v) = prefs.edit().putString("refresh_token", v).apply()

    var handle: String?
        get() = prefs.getString("handle", null)
        set(v) = prefs.edit().putString("handle", v).apply()

    var displayName: String?
        get() = prefs.getString("display_name", null)
        set(v) = prefs.edit().putString("display_name", v).apply()

    var karma: Int
        get() = prefs.getInt("karma", 50)
        set(v) = prefs.edit().putInt("karma", v).apply()

    val isLoggedIn: Boolean get() = !accessToken.isNullOrEmpty()

    fun saveAuth(auth: AuthResponse) {
        accessToken = auth.accessToken
        refreshToken = auth.refreshToken
        handle = auth.user.handle
        displayName = auth.user.displayName
        karma = auth.user.karma
    }

    fun clear() = prefs.edit().clear().apply()
}
