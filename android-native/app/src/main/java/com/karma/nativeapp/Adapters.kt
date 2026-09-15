package com.karma.nativeapp

import android.view.LayoutInflater
import android.view.View
import android.view.ViewGroup
import android.widget.TextView
import androidx.recyclerview.widget.RecyclerView

/** The three list adapters. Plain findViewById holders — no view-binding codegen to get wrong. */

class FeedAdapter : RecyclerView.Adapter<FeedAdapter.Holder>() {
    private val items = mutableListOf<Post>()
    fun submit(list: List<Post>) { items.clear(); items.addAll(list); notifyDataSetChanged() }

    class Holder(v: View) : RecyclerView.ViewHolder(v) {
        val author: TextView = v.findViewById(R.id.post_author)
        val karma: TextView = v.findViewById(R.id.post_karma)
        val body: TextView = v.findViewById(R.id.post_body)
        val meta: TextView = v.findViewById(R.id.post_meta)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder =
        Holder(LayoutInflater.from(parent.context).inflate(R.layout.item_post, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(h: Holder, position: Int) {
        val p = items[position]
        h.author.text = p.authorName.ifEmpty { "@${p.authorHandle}" }
        h.karma.text = p.authorKarma.toString()
        h.body.text = p.body
        val meta = buildList {
            add("♥ ${p.likes}")
            add("💬 ${p.comments}")
            p.categoryName?.let { add(it) }
            if (p.kind == "proof") {
                if (p.rating > 0) add("★ ${p.rating}")
                if (p.amountEarned > 0) add("₹${"%.0f".format(p.amountEarned)}")
            }
        }.joinToString("  ·  ")
        h.meta.text = meta
    }
}

class GigsAdapter : RecyclerView.Adapter<GigsAdapter.Holder>() {
    private val items = mutableListOf<Gig>()
    fun submit(list: List<Gig>) { items.clear(); items.addAll(list); notifyDataSetChanged() }

    class Holder(v: View) : RecyclerView.ViewHolder(v) {
        val title: TextView = v.findViewById(R.id.gig_title)
        val status: TextView = v.findViewById(R.id.gig_status)
        val total: TextView = v.findViewById(R.id.gig_total)
        val address: TextView = v.findViewById(R.id.gig_address)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder =
        Holder(LayoutInflater.from(parent.context).inflate(R.layout.item_gig, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(h: Holder, position: Int) {
        val g = items[position]
        h.title.text = g.title
        h.status.text = "${g.status.uppercase()}  ·  ${g.urgency}  ·  paid: ${g.paymentStatus}"
        h.total.text = "₹${"%.2f".format(g.total)}"
        h.address.text = g.address
    }
}

class KarmaAdapter : RecyclerView.Adapter<KarmaAdapter.Holder>() {
    private val items = mutableListOf<KarmaEvent>()
    fun submit(list: List<KarmaEvent>) { items.clear(); items.addAll(list); notifyDataSetChanged() }

    class Holder(v: View) : RecyclerView.ViewHolder(v) {
        val delta: TextView = v.findViewById(R.id.ev_delta)
        val type: TextView = v.findViewById(R.id.ev_type)
        val reason: TextView = v.findViewById(R.id.ev_reason)
    }

    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): Holder =
        Holder(LayoutInflater.from(parent.context).inflate(R.layout.item_karma_event, parent, false))

    override fun getItemCount() = items.size

    override fun onBindViewHolder(h: Holder, position: Int) {
        val e = items[position]
        h.delta.text = (if (e.delta >= 0) "+${e.delta}" else "${e.delta}")
        h.delta.setTextColor(if (e.delta >= 0) 0xFF4D7C0F.toInt() else 0xFFBE123C.toInt())
        h.type.text = "${e.eventType}  ·  ${e.domain}"
        h.reason.text = e.reason
    }
}
