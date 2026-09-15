"""WebSocket endpoints for the gig lifecycle.

Two routes, deliberately split:

  * ``POST /realtime/ticket`` -- an ordinary authenticated HTTP call that mints a
    single-use handshake token.
  * ``GET  /realtime/gigs/{gig_id}`` (upgrade) -- spends the ticket and streams events.

The split exists because browsers cannot attach an ``Authorization`` header to a WebSocket
handshake. The obvious workaround -- ``?token=<jwt>`` -- puts a long-lived credential into
proxy logs, browser history and ``Referer`` headers. Exchanging it for a 30-second,
single-use ticket keeps the JWT on the HTTP path where it belongs.
"""

from __future__ import annotations

import asyncio
import logging

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.db import get_session_factory
from app.core.deps import CurrentUser
from app.models.marketplace import Gig
from app.services.realtime import TICKET_TTL_S, issue_ticket, realtime, redeem_ticket

log = logging.getLogger(__name__)

router = APIRouter(prefix="/realtime", tags=["realtime"])

# How often the server sends a ping frame. Kept well under the typical 60s idle timeout of
# load balancers and proxies so a quiet gig is not mistaken for a dead connection.
_HEARTBEAT_S = 25.0


class TicketOut(BaseModel):
    ticket: str
    expires_in: int
    ws_path: str


@router.post("/ticket", response_model=TicketOut)
async def create_ticket(user: CurrentUser) -> TicketOut:
    """Exchange the caller's access token for a single-use WebSocket handshake ticket.

    The socket checks no token of its own, so this is where revocation reaches it: a credential
    a logout has revoked, or a session epoch that has moved past, cannot mint a ticket, so what a
    signed-out account loses is the ability to start a stream. What it does not lose is a stream
    already open -- that ends with the tab, or with the socket's own silence timer. Closing that
    gap would mean the socket holding a token it was deliberately never given, which is the thing
    this ticket design exists to avoid; a logout that also has to interrupt a live gig is a
    different trade and is not made here.
    """
    ticket = await issue_ticket(user.id)
    return TicketOut(
        ticket=ticket,
        expires_in=TICKET_TTL_S,
        ws_path=f"/realtime/gigs/{{gig_id}}?ticket={ticket}",
    )


async def _authorised_for_gig(
    factory: async_sessionmaker[AsyncSession], user_id: int, gig_id: int
) -> bool:
    """Only the two parties to a gig may watch it.

    Labour Link accepted any connection for any job id, which meant any client could
    enumerate job ids and read someone else's hiring activity in real time.
    """
    async with factory() as session:
        gig = await session.scalar(select(Gig).where(Gig.id == gig_id))
    if gig is None:
        return False
    return user_id in (gig.customer_id, gig.worker_id)


@router.websocket("/gigs/{gig_id}")
async def gig_stream(
    websocket: WebSocket,
    gig_id: int,
    factory: Annotated[async_sessionmaker[AsyncSession], Depends(get_session_factory)],
    ticket: str = Query(default="", description="Single-use ticket from POST /realtime/ticket"),
) -> None:
    """Stream lifecycle events for one gig to its customer and its assigned worker."""
    user_id = await redeem_ticket(ticket)
    if user_id is None:
        # 4401 = unauthorised, in the application-defined 4000-4999 range. Closing with a
        # code rather than accepting and immediately erroring keeps the failure unambiguous
        # to the client and avoids ever holding an unauthenticated socket open.
        await websocket.close(code=4401)
        return

    if not await _authorised_for_gig(factory, user_id, gig_id):
        # 4403 = authenticated, but not a party to this gig. The ticket was valid, so the
        # caller is known; they simply may not watch this one.
        await websocket.close(code=4403)
        return

    await websocket.accept()

    if not await realtime.connect(gig_id, user_id, websocket):
        await websocket.close(code=4429, reason="Too many open connections")
        return

    try:
        # Send the current state immediately. A client that connects mid-gig would otherwise
        # see nothing until the next transition, and would have to poll to bootstrap.
        async with factory() as session:
            gig = await session.get(Gig, gig_id)
        if gig is not None:
            await websocket.send_json(
                {
                    "type": "gig.snapshot",
                    "gig_id": gig_id,
                    "data": {
                        "status": gig.status,
                        "payment_status": gig.payment_status,
                        "worker_id": gig.worker_id,
                        "total": float(gig.total) if gig.total is not None else None,
                    },
                    "at": None,
                }
            )

        # Hold the socket open and answer pings. All outbound traffic is pushed by
        # publishers; this loop only keeps the connection alive and notices disconnects.
        while True:
            try:
                message = await asyncio.wait_for(
                    websocket.receive_text(), timeout=_HEARTBEAT_S
                )
            except TimeoutError:
                await websocket.send_json({"type": "ping"})
                continue

            if message == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        pass
    except Exception:  # noqa: BLE001 - a broken socket must not escape into the ASGI app
        log.debug("gig stream %s closed unexpectedly", gig_id, exc_info=True)
    finally:
        await realtime.disconnect(gig_id, user_id, websocket)
