"""Prove the Alembic baseline is a real schema, not decoration.

Creates a database with `alembic upgrade head` (not `init_db()`), boots the actual
application against it, and drives a short authenticated flow. If the baseline were missing
a column or an index the app needed, this would fail.

    DATABASE_URL=sqlite+aiosqlite:////tmp/x.db .venv/bin/python scripts/check_alembic.py
"""

from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

# Resolve the target database first and point DATABASE_URL at it BEFORE importing anything
# from app.*: settings are read at import time and the engine is built from them, so a later
# assignment would silently test the default database instead of the migrated one.
DB_PATH = os.environ.get(
    "KARMA_CHECK_DB", str(Path(tempfile.gettempdir()) / "karma_alembic_check.db")
)
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{DB_PATH}"

import httpx  # noqa: E402


def build_schema_with_alembic(db_path: str) -> None:
    env = {**os.environ, "DATABASE_URL": f"sqlite+aiosqlite:///{db_path}", "PYTHONPATH": str(BACKEND)}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise SystemExit(f"alembic upgrade failed:\n{result.stdout}\n{result.stderr}")


async def drive_app() -> tuple[list[int], bool]:
    """Boot the real ASGI app in-process and exercise it end to end."""
    from app.main import app  # imported here, after DATABASE_URL is correct

    transport = httpx.ASGITransport(app=app)
    codes: list[int] = []
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        h = await c.get("/api/v1/health")
        codes.append(h.status_code)
        print(f"  health                          {h.status_code}")

        r = await c.post(
            "/api/v1/auth/register",
            json={
                "email": "alembic@example.com",
                "password": "Str0ngPass!23",
                "display_name": "Alembic Check",
                "handle": "alembic_check",
            },
        )
        codes.append(r.status_code)
        print(f"  auth/register                   {r.status_code}")
        headers = {"Authorization": f"Bearer {r.json()['access_token']}"}

        led = await c.get("/api/v1/karma/ledger", headers=headers)
        codes.append(led.status_code)
        body = led.json()
        print(
            f"  karma/ledger                    {led.status_code}  "
            f"blended={body.get('blended')} band={body.get('band')} "
            f"events={body.get('total_events')}"
        )

        post = await c.post(
            "/api/v1/feed/posts",
            json={"body": "written against an Alembic-built schema", "kind": "post"},
            headers=headers,
        )
        codes.append(post.status_code)
        print(f"  feed/posts (create)             {post.status_code}")

        feed = await c.get("/api/v1/feed/posts", headers=headers)
        codes.append(feed.status_code)
        items = feed.json()
        n = len(items) if isinstance(items, list) else len(items.get("items", []))
        print(f"  feed/posts (read)               {feed.status_code}  posts={n}")

        anon = await c.get("/api/v1/karma/ledger")
        codes.append(anon.status_code)
        print(f"  karma/ledger (unauthenticated)  {anon.status_code}   <- must be 401")

    expected = [200, 201, 200, 201, 200, 401]
    return codes, codes == expected


def main() -> int:
    Path(DB_PATH).unlink(missing_ok=True)

    print(f"  target: {DB_PATH}\n")
    build_schema_with_alembic(DB_PATH)
    print("  alembic upgrade head            ok\n")

    codes, ok = asyncio.run(drive_app())

    print()
    if ok:
        print("  ✓ the application runs correctly on an Alembic-built schema")
        return 0
    print(f"  ✗ unexpected status codes: {codes}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
