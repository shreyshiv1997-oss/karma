# FIXED: Proof posts are unfakeable (kind=proof requires a gig) — enforced by a schema
# CHECK constraint, not only by a request-schema regex.
"""Unified social content.

Tatwamasi kept ``posts``, ``reels``, ``stories`` and ``tweets`` as four separate tables that
were ~90% identical columns. KARMA collapses them into one ``posts`` table with a ``kind``
discriminator -- four tables -> one, because keeping them apart is exactly the Frankenstein
seam the merger exists to remove.

``kind="proof"`` is the new one, and it is the fusion made physical: a completed, *paid* gig
publishes here automatically. Nothing else can create a proof post.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.sqlite import JSON as JSONType
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


class PostKind(str, enum.Enum):
    POST = "post"      # Tatwamasi feed post
    REEL = "reel"      # Tatwamasi short video
    PULSE = "pulse"    # Tatwamasi tweet-length text
    PROOF = "proof"    # KARMA: evidence of completed, paid work


class Post(Base):
    __tablename__ = "posts"
    __table_args__ = (
        Index("ix_posts_kind_created", "kind", "created_at"),
        # "Proof posts are unfakeable by construction" was, before this, enforced only by
        # a regex on the PostCreate request schema -- one code path's input validation.
        # Any other writer (the seed script, an ETL backfill, a future endpoint, a psql
        # session) could insert kind='proof' with no gig behind it, and the feed would
        # render it identically to real evidence. The constraint moves the invariant to
        # the one place every writer has to go through.
        CheckConstraint(
            "kind <> 'proof' OR gig_id IS NOT NULL",
            name="ck_posts_proof_requires_gig",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16), default=PostKind.POST.value, index=True)
    body: Mapped[str] = mapped_column(Text, default="")
    media_urls: Mapped[list] = mapped_column(JSONType, default=list)
    hashtags: Mapped[list] = mapped_column(JSONType, default=list)

    # --- proof-only fields. Populated exclusively by gig completion. ---
    gig_id: Mapped[int | None] = mapped_column(ForeignKey("gigs.id"), index=True)
    before_url: Mapped[str | None] = mapped_column(String(512))
    after_url: Mapped[str | None] = mapped_column(String(512))
    category_name: Mapped[str | None] = mapped_column(String(80))
    amount_earned: Mapped[float | None] = mapped_column()
    rating: Mapped[int | None] = mapped_column(Integer)

    likes_count: Mapped[int] = mapped_column(Integer, default=0)
    comments_count: Mapped[int] = mapped_column(Integer, default=0)
    shares_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class Like(Base):
    __tablename__ = "likes"
    __table_args__ = (UniqueConstraint("post_id", "user_id", name="uq_like_once"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
