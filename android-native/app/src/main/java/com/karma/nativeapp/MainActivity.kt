package com.karma.nativeapp

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.view.View
import android.widget.Button
import android.widget.TextView
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import androidx.recyclerview.widget.LinearLayoutManager
import androidx.recyclerview.widget.RecyclerView
import com.google.android.material.bottomnavigation.BottomNavigationView
import java.util.concurrent.Executors

class MainActivity : AppCompatActivity() {
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())
    private lateinit var session: Session

    private val feedAdapter = FeedAdapter()
    private val gigsAdapter = GigsAdapter()
    private val karmaAdapter = KarmaAdapter()

    private lateinit var recycler: RecyclerView
    private lateinit var karmaHeader: View
    private lateinit var ring: KarmaRingView

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_main)

        session = Session(this)

        recycler = findViewById(R.id.list)
        recycler.layoutManager = LinearLayoutManager(this)

        karmaHeader = findViewById(R.id.karma_header)
        ring = findViewById(R.id.karma_ring)

        findViewById<TextView>(R.id.title_handle).text =
            session.displayName ?: session.handle ?: "KARMA"

        findViewById<Button>(R.id.logout).setOnClickListener {
            // Revoke first, but do not wait for it: the tokens live in `session` and nowhere
            // else, so a phone with no signal must still be able to sign itself out. The call is
            // for whoever else may be holding a copy of them.
            val access = session.accessToken
            val refresh = session.refreshToken
            // Either half is worth sending. An expired access token used to short-circuit this
            // block entirely, which meant the one client that most needed to revoke its session
            // was the one that never asked -- /auth/logout authenticates from the refresh token
            // when the access token is gone, so hand it what there is.
            if (!access.isNullOrEmpty() || !refresh.isNullOrEmpty()) {
                onIo({ runCatching { Api.logout(access, refresh) } }) { }
            }
            session.clear()
            startActivity(Intent(this, LoginActivity::class.java))
            finish()
        }

        val nav = findViewById<BottomNavigationView>(R.id.bottom_nav)
        nav.setOnItemSelectedListener { item ->
            when (item.itemId) {
                R.id.nav_feed -> loadFeed()
                R.id.nav_gigs -> loadGigs()
                R.id.nav_karma -> loadKarma()
            }
            true
        }
        loadFeed()
    }

    private fun <T> onIo(work: () -> T, onUi: (Result<T>) -> Unit) {
        io.execute {
            val r = runCatching(work)
            main.post { onUi(r) }
        }
    }

    private fun token(): String = session.accessToken ?: ""

    private fun fail(e: Throwable) =
        Toast.makeText(this, e.message ?: "Network error", Toast.LENGTH_SHORT).show()

    private fun loadFeed() {
        karmaHeader.visibility = View.GONE
        recycler.adapter = feedAdapter
        onIo({ Api.posts(token()) }) { r ->
            r.onSuccess { feedAdapter.submit(it) }.onFailure { fail(it) }
        }
    }

    private fun loadGigs() {
        karmaHeader.visibility = View.GONE
        recycler.adapter = gigsAdapter
        onIo({ Api.gigs(token()) }) { r ->
            r.onSuccess { gigsAdapter.submit(it) }.onFailure { fail(it) }
        }
    }

    private fun loadKarma() {
        karmaHeader.visibility = View.VISIBLE
        recycler.adapter = karmaAdapter
        onIo({ Api.ledger(token()) }) { r ->
            r.onSuccess { ledger ->
                ring.value = ledger.blended
                findViewById<TextView>(R.id.karma_split).text =
                    "work ${ledger.work}  ·  social ${ledger.social}  ·  ${ledger.band}"
                findViewById<TextView>(R.id.karma_total).text =
                    "${ledger.totalEvents} events"
                karmaAdapter.submit(ledger.events)
            }.onFailure { fail(it) }
        }
    }
}
