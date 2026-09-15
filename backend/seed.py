# FIXED: Proof posts are unfakeable (kind=proof requires payment_status=paid and gig_id)
# — the demo's proof posts are now backed by real completed, paid gigs.
"""Seed the demo database so KARMA is alive on first run.

Run:  python seed.py
Creates five categories, four workers with proof history, a customer, and an admin
who can operate the trust console. The customer has already completed a gig, so the
feed, matching and karma ledger all have content.
"""
from __future__ import annotations

import asyncio
import random
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.db import SessionLocal, engine, init_db
from app.core.security import create_access_token, hash_password
from app.models.marketplace import Gig, ServiceCategory, WorkerProfile
from app.models.messaging import (
    BitchatConversation,
    BitchatDevice,
    BitchatEnvelope,
    BitchatPanicEvent,
    BitchatPreKey,
)
from app.models.payments import GigPayment, StripeWebhookEvent
from app.models.social import Post
from app.models.trust import (
    Dispute, LedgerEntry, Review, SafetyIncident, TrustedContact,
    VerificationSubmission, Wallet,
)
from app.models.user import User
from app.services.karma import KarmaLedger, KarmaEventType

PASSWORD = "StrongPass!234"
DEMO_TOKEN_USER = "priya"

CATEGORIES = [
    ("Electrical", "electrical", "⚡", "Wiring, fans, fittings, inverters", 200, 18, 350),
    ("Plumbing", "plumbing", "🚿", "Leaks, taps, motors, drainage", 200, 18, 320),
    ("Carpentry", "carpentry", "🪚", "Furniture, doors, modular kitchens", 250, 20, 400),
    ("Painting", "painting", "🎨", "Interior, exterior, texture, polish", 180, 15, 300),
    ("Cleaning", "cleaning", "🧹", "Deep clean, sofa, bathroom, kitchen", 150, 12, 250),
]

WORKERS = [
    # handle, name, category, lat, lng, jobs, rating, tier, hourly, bio, skills
    ("ramesh.electric", "Ramesh Kumar", "electrical", 22.7216, 75.8597, 48, 4.9, "gold", 380,
     "12 years of residential wiring across Indore. ISI-certified materials only.",
     ["Wiring", "Inverter", "Fan fitting"]),
    ("sunita.plumb", "Sunita Bai", "plumbing", 22.7156, 75.8617, 63, 4.8, "gold", 330,
     "Motor repair and leakage specialist. Available same-day for urgent work.",
     ["Motor repair", "Leakage", "Bathroom fittings"]),
    ("arjun.carp", "Arjun Yadav", "carpentry", 22.7306, 75.8507, 27, 4.7, "silver", 420,
     "Modular kitchen and wardrobe work. I bring my own tools.",
     ["Modular kitchen", "Wardrobe", "Doors"]),
    ("kavita.clean", "Kavita Verma", "cleaning", 22.7126, 75.8527, 91, 4.9, "gold", 260,
     "Deep cleaning team of three. Sofa shampoo and kitchen degreasing.",
     ["Deep clean", "Sofa shampoo", "Kitchen"]),
]


async def main() -> None:
    random.seed(20260827)
    await init_db()

    async with SessionLocal() as s:
        # Idempotent: wipe and rebuild so re-running is safe.
        for model in (
            StripeWebhookEvent, GigPayment, BitchatEnvelope, BitchatPanicEvent,
            BitchatPreKey, BitchatConversation, BitchatDevice, Post, Review, LedgerEntry,
            Wallet, Dispute, SafetyIncident, Gig, WorkerProfile,
            VerificationSubmission, TrustedContact, User, ServiceCategory,
        ):
            await s.execute(model.__table__.delete())
        await s.commit()

        categories: dict[str, int] = {}
        for name, slug, emoji, desc, base, per_km, per_hr in CATEGORIES:
            cat = ServiceCategory(
                name=name, slug=slug, emoji=emoji, description=desc,
                base_fare=Decimal(str(base)), per_km_rate=Decimal(str(per_km)),
                per_hour_rate=Decimal(str(per_hr)),
            )
            s.add(cat)
            await s.flush()
            categories[slug] = cat.id

        ledger = KarmaLedger(s)

        # --- the customer -------------------------------------------------
        customer = User(
            handle=DEMO_TOKEN_USER, display_name="Priya Malviya",
            email="priya@example.com", phone="+919876500001",
            password_hash=hash_password(PASSWORD), city="Indore",
            capabilities=["can_post", "can_follow", "can_chat", "can_hire"],
            karma=50, karma_work=50, karma_social=50, reputation_score=50.0,
            bio="Vijay Nagar. Hiring mostly for electrical and plumbing.",
        )
        s.add(customer)
        await s.flush()

        # Demo only. Production admins remain provisioned out of band; no public
        # endpoint can grant this capability.
        admin = User(
            handle="karma.admin", display_name="KARMA Trust Desk",
            email="admin@karma.local", password_hash=hash_password(PASSWORD),
            city="Indore", bio="Demo trust-and-safety operator.",
            capabilities=["can_post", "can_follow", "can_chat", "admin"],
            karma=50, karma_work=50, karma_social=50, reputation_score=50.0,
        )
        s.add(admin)
        await s.flush()

        # Give the demo console real queues to operate rather than empty-state mockups.
        # Document references use the same masked-at-rest representation as the API.
        s.add(VerificationSubmission(
            user_id=customer.id, document_type="aadhaar",
            document_ref="XXXX0001", status="pending",
        ))
        s.add(SafetyIncident(
            raised_by=customer.id, note="Demo safety check-in requiring review",
            status="open", lat=22.7196, lng=75.8577,
        ))

        # --- the workers, each with proof history -------------------------
        worker_ids: list[int] = []
        for (handle, name, cat_slug, lat, lng, jobs, rating, tier,
             hourly, bio, skills) in WORKERS:
            user = User(
                handle=handle, display_name=name, email=f"{handle}@example.com",
                password_hash=hash_password(PASSWORD), city="Indore",
                capabilities=["can_post", "can_follow", "can_chat", "can_work"],
                karma=50, karma_work=50, karma_social=50, reputation_score=50.0,
                bio=bio, is_verified=True, verification_tier=tier,
            )
            s.add(user)
            await s.flush()

            s.add(WorkerProfile(
                user_id=user.id, category_id=categories[cat_slug],
                hourly_rate=Decimal(str(hourly)), rating=rating, rating_count=jobs,
                total_jobs=jobs, is_available=True, verification_tier=tier,
                background_check_status="cleared", approved_at=datetime.now(UTC),
                bio=bio, skills=skills, lat=lat, lng=lng,
                avg_response_time_seconds=random.choice([180, 300, 420, 600]),
            ))

            # Trust events give them a real karma history, not a hardcoded number.
            await ledger.record(user.id, KarmaEventType.PHONE_VERIFIED,
                                reason="Phone number verified")
            await ledger.record(user.id, KarmaEventType.KYC_APPROVED,
                                reason=f"Identity verified — {tier.title()} tier", tier=tier)
            for i in range(min(jobs, 12)):
                await ledger.record(user.id, KarmaEventType.GIG_COMPLETED,
                                    reason=f"Completed job #{jobs - i} on time")
                if i % 3 == 0:
                    await ledger.record(user.id, KarmaEventType.PROOF_PUBLISHED,
                                        reason="Published proof of work")
                if i % 4 == 0:
                    await ledger.record(user.id, KarmaEventType.REVIEW_RECEIVED,
                                        reason="5-star review received", rating=5)

            # Completed gigs become visible proof posts in the feed.
            #
            # Each proof is backed by a real completed, *paid* gig row. The seed used to
            # fabricate free-floating proof posts with gig_id NULL, which is precisely the
            # forgery the product promises is impossible -- and it put six of them per
            # worker into the demo everyone judges the product by. The schema now refuses
            # it (ck_posts_proof_requires_gig), so the seed does what the API does.
            for i in range(3):
                created = datetime.now(UTC) - timedelta(days=random.randint(1, 30))
                title = random.choice([
                    f"Rewired a {random.randint(2,4)}-room flat",
                    "Replaced a burnt-out distribution board",
                    "Fixed a submerged motor and repiped the overhead tank",
                    "Full interior repaint, two coats plus primer",
                ])
                earned = round(random.uniform(1200, 4800), 2)
                past_gig = Gig(
                    customer_id=customer.id, worker_id=user.id,
                    category_id=categories[cat_slug],
                    title=title, description="Historic completed work.",
                    status="completed", urgency="standard",
                    lat=lat, lng=lng, address_label="Indore",
                    total=Decimal(str(round(earned / (1 - 0.15), 2))),
                    estimated_hours=3.0, payment_status="paid",
                    created_at=created, completed_at=created,
                )
                s.add(past_gig)
                await s.flush()
                s.add(Post(
                    author_id=user.id, kind="proof",
                    body=title,
                    media_urls=[], hashtags=[cat_slug, "indore"],
                    gig_id=past_gig.id,
                    before_url=f"https://placehold.co/800x600/1a1a2e/eaeaea?text=Before+{i+1}",
                    after_url=f"https://placehold.co/800x600/4d7c0f/ffffff?text=After+{i+1}",
                    category_name=next(n for n, sl, *_ in CATEGORIES if sl == cat_slug),
                    amount_earned=earned,
                    rating=random.choice([5, 5, 5, 4]),
                    created_at=created,
                ))
                await ledger.record(user.id, KarmaEventType.PROOF_PUBLISHED,
                                    reason="Published proof of work")
            worker_ids.append(user.id)

        # --- a completed gig, so the wallet and stats are populated -------
        gig = Gig(
            customer_id=customer.id, worker_id=worker_ids[0],
            category_id=categories["electrical"],
            title="Rewire 3-room flat", description="Old aluminium wiring, full replacement",
            status="completed", urgency="standard", lat=22.7196, lng=75.8577,
            address_label="Vijay Nagar, Indore",
            fare_breakdown={"base_fare": 200.0, "distance_fare": 5.4, "time_fare": 1400.0,
                            "subtotal": 1605.4, "skill_multiplier": 1.18,
                            "urgency_multiplier": 1.0, "night_multiplier": 1.0,
                            "platform_fee": 240.81, "total": 1846.21},
            total=Decimal("1846.21"), estimated_hours=4.0, payment_status="paid",
            completed_at=datetime.now(UTC) - timedelta(days=2),
        )
        s.add(gig)
        await s.flush()
        dispute = Dispute(
            gig_id=gig.id, raised_by=customer.id,
            reason="The final invoice needs a manual scope review.", status="open",
        )
        s.add(dispute)
        await s.flush()
        await ledger.record(
            worker_ids[0], KarmaEventType.DISPUTE_FILED,
            reason="A dispute was filed against this gig",
            ref_type="dispute", ref_id=dispute.id,
        )
        s.add(Review(gig_id=gig.id, reviewer_id=customer.id, reviewee_id=worker_ids[0],
                     rating=5, punctuality=5, quality=5, communication=4,
                     comment="On time, clean work, explained everything."))
        s.add(Wallet(user_id=worker_ids[0], balance=Decimal("1569.28"),
                     lifetime_earned=Decimal("1569.28")))
        s.add(LedgerEntry(user_id=worker_ids[0], entry_type="payout",
                          amount=Decimal("1569.28"), gig_id=gig.id,
                          note=f"Payout for gig #{gig.id}"))
        s.add(TrustedContact(user_id=customer.id, name="Alok (husband)",
                             phone="+919876500002", relationship="spouse"))
        await s.commit()

        count_users = len((await s.execute(User.__table__.select())).all())
        count_posts = len((await s.execute(Post.__table__.select())).all())
        print(f"Seeded {count_users} users, {count_posts} posts, "
              f"{len(CATEGORIES)} categories, 1 completed gig.")
        print()
        print("  Customer : priya            / StrongPass!234")
        print("  Worker   : ramesh.electric / StrongPass!234")
        print("  Admin    : karma.admin     / StrongPass!234")
        print()
        token = create_access_token(1)
        print(f"  Demo bearer token (user id 1):\n  {token[:64]}...")

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
