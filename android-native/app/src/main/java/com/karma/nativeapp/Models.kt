package com.karma.nativeapp

import org.json.JSONObject

/**
 * Plain data classes mirroring the backend's Pydantic contracts (app/schemas/__init__.py).
 * Parsed by hand with org.json so the project carries no serialization dependency.
 * Every field name matches the JSON key exactly.
 */

private fun JSONObject.strOrNull(key: String): String? =
    if (isNull(key)) null else optString(key, "")

private fun JSONObject.intOr(key: String, default: Int): Int =
    if (isNull(key)) default else optInt(key, default)

data class User(
    val id: Int,
    val handle: String,
    val displayName: String,
    val karma: Int,
    val karmaWork: Int,
    val karmaSocial: Int,
    val tier: String,
    val isVerified: Boolean,
) {
    companion object {
        fun from(o: JSONObject) = User(
            id = o.intOr("id", 0),
            handle = o.optString("handle", ""),
            displayName = o.optString("display_name", ""),
            karma = o.intOr("karma", 50),
            karmaWork = o.intOr("karma_work", 50),
            karmaSocial = o.intOr("karma_social", 50),
            tier = o.optString("verification_tier", "none"),
            isVerified = o.optBoolean("is_verified", false),
        )
    }
}

data class AuthResponse(val user: User, val accessToken: String, val refreshToken: String) {
    companion object {
        fun from(o: JSONObject) = AuthResponse(
            user = User.from(o.getJSONObject("user")),
            accessToken = o.optString("access_token", ""),
            refreshToken = o.optString("refresh_token", ""),
        )
    }
}

data class Post(
    val id: Int,
    val kind: String,
    val body: String,
    val authorName: String,
    val authorHandle: String,
    val authorKarma: Int,
    val likes: Int,
    val comments: Int,
    val categoryName: String?,
    val rating: Int,
    val amountEarned: Double,
) {
    companion object {
        fun from(o: JSONObject) = Post(
            id = o.intOr("id", 0),
            kind = o.optString("kind", "share"),
            body = o.optString("body", ""),
            authorName = o.strOrNull("author_name") ?: o.optString("author_handle", ""),
            authorHandle = o.optString("author_handle", ""),
            authorKarma = o.intOr("author_karma", 50),
            likes = o.intOr("likes_count", 0),
            comments = o.intOr("comments_count", 0),
            categoryName = o.strOrNull("category_name"),
            rating = o.intOr("rating", 0),
            amountEarned = o.optDouble("amount_earned", 0.0),
        )
    }
}

data class Gig(
    val id: Int,
    val title: String,
    val status: String,
    val urgency: String,
    val address: String,
    val total: Double,
    val paymentStatus: String,
) {
    companion object {
        fun from(o: JSONObject) = Gig(
            id = o.intOr("id", 0),
            title = o.optString("title", ""),
            status = o.optString("status", ""),
            urgency = o.optString("urgency", ""),
            address = o.optString("address_label", ""),
            total = o.optDouble("total", 0.0),
            paymentStatus = o.optString("payment_status", ""),
        )
    }
}

data class KarmaEvent(
    val id: Int,
    val eventType: String,
    val domain: String,
    val delta: Int,
    val reason: String,
) {
    companion object {
        fun from(o: JSONObject) = KarmaEvent(
            id = o.intOr("id", 0),
            eventType = o.optString("event_type", ""),
            domain = o.optString("domain", ""),
            delta = o.intOr("delta", 0),
            reason = o.optString("reason", ""),
        )
    }
}

data class KarmaLedger(
    val blended: Int,
    val work: Int,
    val social: Int,
    val band: String,
    val totalEvents: Int,
    val events: List<KarmaEvent>,
) {
    companion object {
        fun from(o: JSONObject): KarmaLedger {
            val arr = o.optJSONArray("events")
            val events = mutableListOf<KarmaEvent>()
            if (arr != null) for (i in 0 until arr.length()) events.add(KarmaEvent.from(arr.getJSONObject(i)))
            return KarmaLedger(
                blended = o.intOr("blended", 50),
                work = o.intOr("work", 50),
                social = o.intOr("social", 50),
                band = o.optString("band", ""),
                totalEvents = o.intOr("total_events", events.size),
                events = events,
            )
        }
    }
}
