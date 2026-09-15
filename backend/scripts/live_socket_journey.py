"""Live WebSocket journey against a running server.

Unlike the test suite, this drives real TCP sockets over HTTP(S), so the ASGI upgrade,
uvicorn's WebSocket handling and the Vite proxy are all exercised rather than simulated.

    KARMA_BASE=http://localhost:8000/api/v1 .venv/bin/python scripts/live_socket_journey.py

Exits non-zero if any check fails, so it can be used as a smoke test.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.error
import urllib.request

BASE = os.environ.get("KARMA_BASE", "http://localhost:8000/api/v1").rstrip("/")
WS_BASE = BASE.replace("http://", "ws://").replace("https://", "wss://")

PASSWORD = "StrongPass!234"
CUSTOMER = "priya"
_failures: list[str] = []


def _check(label: str, condition: bool, detail: str = "") -> None:
    mark = "✓" if condition else "✗"
    print(f"  {mark}  {label}{(' -> ' + detail) if detail else ''}")
    if not condition:
        _failures.append(label)


def _http(method: str, path: str, body: dict | None = None, token: str | None = None) -> tuple[int, dict]:
    request = urllib.request.Request(
        f"{BASE}{path}",
        data=json.dumps(body).encode() if body is not None else None,
        method=method,
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw or b"{}")
        except json.JSONDecodeError:
            return exc.code, {"raw": raw.decode(errors="replace")}


def _customer_token() -> str:
    """Sign in as the seeded customer, or explain that the database is not seeded.

    This used to register a throwaway handle and self-grant `can_hire`, which is precisely the hole
    that the verified-contact rule closed: an account that has never proved it owns a phone number
    may not hire anyone, and no route attaches a phone to an account afterwards -- registration is
    where a consumed OTP lands, so the throwaway could not even be repaired. The script already
    refuses to run without seeded categories, so it takes its actor from the same seed. A gate that
    fails on its own setup, instead of on a broken socket, is not a gate.
    """
    code, body = _http("POST", "/auth/login", {"identifier": CUSTOMER, "password": PASSWORD})
    if code != 200 or not isinstance(body, dict) or "access_token" not in body:
        print(f"  ! the seeded customer {CUSTOMER!r} cannot sign in ({code}); run seed.py first")
        raise SystemExit(2)
    return body["access_token"]


async def main() -> int:
    try:
        import websockets
    except ImportError:
        print("  ! the 'websockets' package is required for this script")
        return 2

    print("═══ LIVE WEBSOCKET JOURNEY ═══\n")
    print(f"  base: {BASE}\n")

    # ── a customer and a gig ────────────────────────────────────────────────
    token = _customer_token()

    _, categories = _http("GET", "/categories")
    if not categories:
        print("  ! no service categories; run seed.py first")
        return 2
    category_id = categories[0]["id"]

    code, gig = _http(
        "POST",
        "/gigs",
        {
            "category_id": category_id,
            "title": "Socket smoke test",
            "description": "Verifying live push over a real WebSocket.",
            "lat": 22.7196,
            "lng": 75.8577,
            "estimated_hours": 1,
        },
        token,
    )
    _check("gig created", code == 201, f"id={gig.get('id')}")
    if code != 201:
        return 1
    gig_id = gig["id"]

    # ── the handshake ───────────────────────────────────────────────────────
    code, ticket_body = _http("POST", "/realtime/ticket", token=token)
    _check("ticket issued", code == 200, f"expires_in={ticket_body.get('expires_in')}")
    if code != 200:
        return 1

    url = f"{WS_BASE}/realtime/gigs/{gig_id}?ticket={ticket_body['ticket']}"

    print("\n── handshake ──")

    async def _expect_refusal(url: str, label: str) -> None:
        """A refusal must arrive as HTTP 403 on the handshake, not as a WebSocket frame.

        Starlette turns ``close()`` before ``accept()`` into an HTTP 403 response to the
        upgrade request. The application-level close code is never transmitted, because no
        WebSocket connection is ever established -- which is the point: an unauthorised
        client is refused at the HTTP layer and never holds an open socket.
        """
        try:
            async with websockets.connect(url) as ws:
                await ws.recv()
        except websockets.exceptions.InvalidStatus as exc:
            _check(label, exc.response.status_code == 403, f"HTTP {exc.response.status_code}")
            return
        except websockets.exceptions.ConnectionClosedError as exc:
            # Tolerated: a server that accepts first and then closes lands here instead.
            _check(label, exc.rcvd.code in (4401, 4403), f"close code={exc.rcvd.code}")
            return
        except Exception as exc:  # noqa: BLE001
            _check(label, False, f"{type(exc).__name__}: {exc}")
            return
        _check(label, False, "connection unexpectedly succeeded")

    # A socket with no ticket must be refused before it is ever accepted.
    await _expect_refusal(f"{WS_BASE}/realtime/gigs/{gig_id}", "no-ticket socket refused")

    # A ticket cannot be spent twice.
    try:
        async with websockets.connect(url) as ws:
            snapshot = json.loads(await ws.recv())
            _check(
                "snapshot frame on connect",
                snapshot.get("type") == "gig.snapshot",
                f"status={snapshot.get('data', {}).get('status')}",
            )
            _check("snapshot carries the real status", snapshot["data"]["status"] == "searching")
    except Exception as exc:  # noqa: BLE001
        _check("socket opens with a valid ticket", False, f"{type(exc).__name__}: {exc}")
        return 1

    await _expect_refusal(url, "ticket is single-use")

    # ── live delivery ───────────────────────────────────────────────────────
    print("\n── live delivery ──")
    code, replay = _http("POST", "/realtime/ticket", token=token)
    if code != 200:
        _check("second ticket issued", False, f"{code}")
        return 1

    async with websockets.connect(f"{WS_BASE}/realtime/gigs/{gig_id}?ticket={replay['ticket']}") as ws:
        json.loads(await ws.recv())  # discard the snapshot

        # Application-level ping/pong keeps the socket alive through proxies.
        await ws.send("ping")
        pong = json.loads(await ws.recv())
        _check("application ping answered", pong.get("type") == "pong")

        # Change state over ordinary HTTP; the push must arrive on the socket.
        code, moved = _http(
            "POST", f"/gigs/{gig_id}/status", {"status": "cancelled"}, token
        )
        _check("gig cancelled over HTTP", code == 200, f"{code}")

        try:
            pushed = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
        except TimeoutError:
            _check("push received", False, "timed out after 10s")
            return 1

        _check("push received", pushed.get("type") == "gig.status_changed", str(pushed.get("type")))
        _check("push carries the new status", pushed.get("data", {}).get("status") == "cancelled")
        _check("push is scoped to this gig", pushed.get("gig_id") == gig_id, f"gig_id={pushed.get('gig_id')}")
        _check("push is timestamped", bool(pushed.get("at")))

    print()
    if _failures:
        print(f"════════ {len(_failures)} CHECK(S) FAILED: {_failures} ════════")
        return 1
    print("════════ LIVE WEBSOCKET JOURNEY: ALL CHECKS PASSED ════════")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
