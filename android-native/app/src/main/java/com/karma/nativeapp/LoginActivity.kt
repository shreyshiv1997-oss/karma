package com.karma.nativeapp

import android.content.Intent
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.widget.Button
import android.widget.EditText
import android.widget.ProgressBar
import android.widget.Toast
import androidx.appcompat.app.AppCompatActivity
import java.util.concurrent.Executors

class LoginActivity : AppCompatActivity() {
    private val io = Executors.newSingleThreadExecutor()
    private val main = Handler(Looper.getMainLooper())

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContentView(R.layout.activity_login)

        val session = Session(this)
        if (session.isLoggedIn) {
            startActivity(Intent(this, MainActivity::class.java))
            finish()
            return
        }

        val identifier = findViewById<EditText>(R.id.login_identifier)
        val password = findViewById<EditText>(R.id.login_password)
        val button = findViewById<Button>(R.id.login_button)
        val progress = findViewById<ProgressBar>(R.id.login_progress)

        button.setOnClickListener {
            val id = identifier.text.toString().trim()
            val pw = password.text.toString()
            if (id.length < 3 || pw.isEmpty()) {
                Toast.makeText(this, "Enter handle/email and password", Toast.LENGTH_SHORT).show()
                return@setOnClickListener
            }
            progress.visibility = android.view.View.VISIBLE
            button.isEnabled = false
            io.execute {
                val result = runCatching { Api.login(id, pw) }
                main.post {
                    progress.visibility = android.view.View.GONE
                    button.isEnabled = true
                    result
                        .onSuccess { auth ->
                            Session(this).saveAuth(auth)
                            startActivity(Intent(this, MainActivity::class.java))
                            finish()
                        }
                        .onFailure { e ->
                            Toast.makeText(this, e.message ?: "Login failed", Toast.LENGTH_LONG).show()
                        }
                }
            }
        }
    }
}
