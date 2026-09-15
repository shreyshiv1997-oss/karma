# FIXED: Proof posts are unfakeable (kind=proof requires payment_status=paid and gig_id)
# — the feed now refuses kind=proof explicitly instead of relying on a schema regex.
"""Unified social feed.

One table, four kinds. ``kind="proof"`` cannot be created here -- it is published only by
gig completion, which is what keeps the feed honest.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, HTTPException, Query
from sqlalchemy import delete, or_, select, update
from sqlalchemy.exc import IntegrityError

from app.core.deps import CurrentUser, SessionDep
from app.models.social import Comment, Like, Post, PostKind
from app.models.user import User
from app.routers.media import validate_media_references
from app.schemas import Message, PostCreate, PostOut

router = APIRouter(prefix="/feed", tags=["Feed"])

_HASHTAG = re.compile(r"#([\w\u0900-\u097F]{1,40})")


def _escape_like(term: str) -> str:
    """Make a user substring safe for LIKE. ``%`` and ``_`` are wildcards, and the escape
    character itself must be escaped first or it escapes the escapes."""
    return term.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def _to_out(post: Post, author: User | None, *, liked: bool = False) -> PostOut:
    out = PostOut.model_validate(post)
    if author is not None:
        out.author_name = author.display_name
        out.author_handle = author.handle
        out.author_avatar = author.avatar_url
        out.author_karma = author.karma
        out.author_tier = author.verification_tier
    out.liked_by_me = liked
    return out


async def _load(
    session, posts: list[Post], viewer: User | None = None
) -> list[PostOut]:
    if not posts:
        return []
    ids = {p.author_id for p in posts}
    authors = {
        a.id: a
        for a in (await session.execute(select(User).where(User.id.in_(ids)))).scalars().all()
    }
    # The viewer's likes are one batch query too, not one per card: liking is per-user state
    # riding a per-post payload, and an N+1 here would grow exactly as fast as the feed does.
    liked_ids: set[int] = set()
    if viewer is not None:
        liked_ids = set(
            (
                await session.execute(
                    select(Like.post_id).where(
                        Like.user_id == viewer.id,
                        Like.post_id.in_({p.id for p in posts}),
                    )
                )
            ).scalars().all()
        )
    return [_to_out(p, authors.get(p.author_id), liked=p.id in liked_ids) for p in posts]


@router.get("/posts", response_model=list[PostOut])
async def list_posts(
    session: SessionDep,
    user: CurrentUser,
    kind: str | None = Query(default=None, pattern="^(post|reel|pulse|proof)$"),
    q: str | None = Query(
        default=None,
        max_length=80,
        description="Case-insensitive substring search over post text, proof category, and "
        "author name/handle. Hashtags live in the body, so `tag` and `#tag` both find them.",
    ),
    limit: int = Query(default=20, ge=1, le=50),
    before_id: int | None = Query(
        default=None,
        ge=1,
        description="Keyset cursor: return posts older than this id. Pass the last id of the "
        "previous page. A short page is the end of the feed.",
    ),
) -> list[PostOut]:
    # Keyset, not OFFSET. `?offset=` would reshuffle rows between pages whenever anyone posted
    # in the gap -- the same post twice, or none at all, which is exactly what a social feed
    # cannot afford -- and it costs the database a scan of everything it skips. Ids are assigned
    # in insert order, so `id <` agrees with the `created_at DESC` ordering.
    stmt = select(Post).order_by(Post.created_at.desc(), Post.id.desc()).limit(limit)
    if kind:
        stmt = stmt.where(Post.kind == kind)
    needle = (q or "").strip()
    if needle:
        # The author columns live on `users`, so searching them needs the join; selecting
        # only Post entities keeps the response shape (and _load's author batch) unchanged.
        pattern = f"%{_escape_like(needle)}%"
        stmt = stmt.join(User, Post.author_id == User.id).where(
            or_(
                Post.body.ilike(pattern, escape="\\"),
                Post.category_name.ilike(pattern, escape="\\"),
                User.display_name.ilike(pattern, escape="\\"),
                User.handle.ilike(pattern, escape="\\"),
            )
        )
    if before_id is not None:
        stmt = stmt.where(Post.id < before_id)
    posts = list((await session.execute(stmt)).scalars().all())
    return await _load(session, posts, viewer=user)


@router.post("/posts", response_model=PostOut, status_code=201)
async def create_post(
    payload: PostCreate, user: CurrentUser, session: SessionDep
) -> PostOut:
    if "can_post" not in set(user.capabilities or []):
        raise HTTPException(status_code=403, detail="Missing capability: can_post")

    # Belt and braces. `PostCreate.kind` already excludes "proof" by pattern, but that is
    # input validation on one schema: widen the pattern, add a field, accept a dict here,
    # and the invariant is gone with nothing failing. Proof is evidence of a paid gig and
    # only gigs._complete_gig may mint it, so the router says so in its own voice.
    if payload.kind == PostKind.PROOF.value:
        raise HTTPException(
            status_code=403,
            detail="Proof posts are published by completing a paid gig, not by posting.",
        )

    media_urls = await validate_media_references(
        session,
        owner_id=user.id,
        references=payload.media_urls,
        purposes={"post"},
    )
    hashtags = list(dict.fromkeys(payload.hashtags + _HASHTAG.findall(payload.body)))
    post = Post(
        author_id=user.id,
        kind=payload.kind,
        body=payload.body,
        media_urls=media_urls,
        hashtags=hashtags[:20],
    )
    session.add(post)
    # SQL, not read-modify-write: the like counter and the wallet both got this treatment
    # because two concurrent writes must compose rather than one clobbering the other.
    await session.execute(
        update(User).where(User.id == user.id).values(posts_count=User.posts_count + 1)
    )
    await session.flush()
    await session.refresh(user)
    return _to_out(post, user)


@router.post("/posts/{post_id}/like", response_model=PostOut)
async def like_post(post_id: int, user: CurrentUser, session: SessionDep) -> PostOut:
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    existing = await session.scalar(
        select(Like).where(Like.post_id == post_id, Like.user_id == user.id)
    )
    # Counter updates are expressed as SQL so concurrent likes compose instead of
    # overwriting each other -- the same read-modify-write hazard as the wallet, with
    # the same fix, applied where the contention is highest.

    async def _unlike() -> None:
        # Decrement only when this request is the one that removed the row, so two unlikes aimed
        # at one like cannot subtract twice. The `> 0` clause is the backstop, not the mechanism:
        # a count that goes negative is a post that never had those likes.
        removed = await session.execute(
            delete(Like).where(Like.post_id == post_id, Like.user_id == user.id)
        )
        if removed.rowcount:
            await session.execute(
                update(Post)
                .where(Post.id == post_id, Post.likes_count > 0)
                .values(likes_count=Post.likes_count - 1)
            )

    # The response must say which way the toggle landed: only the branch that actually
    # inserted the row leaves the caller liking the post.
    liked = False
    if existing is None:
        # The read above and the insert below are not one atomic act. Two taps a millisecond apart
        # both see no like, and `uq_like_once` rejects the second -- which used to reach the user as
        # a 500, because the rejected INSERT surfaced out of the counter UPDATE's autoflush, outside
        # any handler. A rejected insert is not a server error, it is the other tap having won, so
        # this request does what a second tap means: unlike. The savepoint keeps the failed row from
        # poisoning the rest of the transaction, the shape ``_credit_wallet`` already uses.
        try:
            async with session.begin_nested():
                session.add(Like(post_id=post_id, user_id=user.id))
                await session.flush()
        except IntegrityError:
            await _unlike()
        else:
            liked = True
            await session.execute(
                update(Post)
                .where(Post.id == post_id)
                .values(likes_count=Post.likes_count + 1)
            )
    else:
        liked = False
        await _unlike()
    await session.flush()
    await session.refresh(post)

    author = await session.get(User, post.author_id)
    return _to_out(post, author, liked=liked)


@router.post("/posts/{post_id}/comment", response_model=Message, status_code=201)
async def comment(
    post_id: int, body: dict, user: CurrentUser, session: SessionDep
) -> Message:
    text = str(body.get("body", "")).strip()
    if not text or len(text) > 2000:
        raise HTTPException(status_code=422, detail="Comment body must be 1-2000 characters")

    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")

    session.add(Comment(post_id=post_id, author_id=user.id, body=text))
    await session.execute(
        update(Post)
        .where(Post.id == post_id)
        .values(comments_count=Post.comments_count + 1)
    )
    await session.flush()
    return Message(detail="Comment added")


@router.get("/posts/{post_id}/comments")
async def list_comments(post_id: int, session: SessionDep, user: CurrentUser) -> list[dict]:
    """Comments are readable by signed-in users, like the feed they belong to.

    They were world-readable, which is inconsistent with GET /feed/posts (authenticated) and
    put other people's replies -- often about a named address or a landlord -- on an
    enumerable post id with no session required.
    """
    del user  # authorisation only; comments are readable by any account in good standing
    rows = (
        await session.execute(
            select(Comment, User.display_name, User.handle)
            .join(User, User.id == Comment.author_id)
            .where(Comment.post_id == post_id)
            .order_by(Comment.created_at.asc())
        )
    ).all()
    return [
        {
            "id": c.id,
            "body": c.body,
            "author_name": name,
            "author_handle": handle,
            "created_at": c.created_at.isoformat() if c.created_at else None,
        }
        for c, name, handle in rows
    ]


@router.delete("/posts/{post_id}", response_model=Message)
async def delete_post(post_id: int, user: CurrentUser, session: SessionDep) -> Message:
    post = await session.get(Post, post_id)
    if post is None:
        raise HTTPException(status_code=404, detail="Post not found")
    if post.author_id != user.id and "admin" not in set(user.capabilities or []):
        raise HTTPException(status_code=403, detail="Not your post")

    # Proof posts are evidence tied to a paid transaction; they are not deletable.
    if post.kind == PostKind.PROOF.value:
        raise HTTPException(
            status_code=409, detail="Proof posts are permanent evidence and cannot be deleted"
        )

    # The counter belongs to the *author*. This used to decrement ``user``, which is the
    # admin whenever moderation removes someone else's post: the author's count went stale
    # and an unrelated one fell. Captured before the delete so the id survives the flush.
    author_id = post.author_id
    await session.delete(post)
    await session.execute(
        update(User).where(User.id == author_id).values(posts_count=User.posts_count - 1)
    )
    # Clamped here rather than with MAX()/GREATEST(), which are spelled differently in
    # SQLite and Postgres. A second statement is cheap and dialect-neutral.
    await session.execute(
        update(User).where(User.id == author_id, User.posts_count < 0).values(posts_count=0)
    )
    await session.flush()
    return Message(detail="Post deleted")
