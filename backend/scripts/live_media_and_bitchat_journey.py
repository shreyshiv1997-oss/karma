"""Live media-upload and Bitchat-relay journey against a running server.

Unlike the test suite, this drives the real HTTP server end to end with an
independent client-side crypto implementation (Ed25519 identities, signed
one-time X25519 prekeys, HKDF-SHA256 with salt=nonce/info=AAD, AES-256-GCM)
that mirrors the Flutter boundary byte-for-byte, so the relay contract is
proven over the wire rather than simulated in-process.

    KARMA_BASE=http://localhost:8000/api/v1 .venv/bin/python scripts/live_media_and_bitchat_journey.py

Exits non-zero if any check fails, so it can be used as a smoke test.
Requires a seeded database (`python seed.py`): the demo customer `priya` and
worker `ramesh.electric` must exist.
"""

from __future__ import annotations

import base64
import json
import os
import time
import urllib.error
import urllib.request
import uuid
from datetime import UTC, datetime

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ed25519, x25519
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

BASE = os.environ.get("KARMA_BASE", "http://localhost:8000/api/v1").rstrip("/")
PASSWORD = "StrongPass!234"
# 1x1 transparent PNG; the upload contract sniffs bytes, not the declared type.
PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M8AAAMBAQDJ/pLvAAAAAElFTkSuQmCC"
)
_failures: list[str] = []


def check(label: str, condition: bool, detail: str = "") -> None:
    mark = "✓" if condition else "✗"
    print(f"  {mark}  {label}{(' -> ' + detail) if detail else ''}")
    if not condition:
        _failures.append(label)


def _http(
    method: str,
    path: str,
    body: dict | None = None,
    token: str | None = None,
    raw: bytes | None = None,
    headers: dict | None = None,
) -> tuple[int, object, dict]:
    url = BASE + path
    data = raw
    head = dict(headers or {})
    if body is not None:
        data = json.dumps(body).encode()
        head["Content-Type"] = "application/json"
    if token:
        head["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=data, headers=head, method=method)
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = response.read()
            try:
                return response.status, json.loads(payload or b"null"), {k.lower(): v for k, v in response.headers.items()}
            except ValueError:  # JSONDecodeError or binary (media object) payload
                return response.status, payload, {k.lower(): v for k, v in response.headers.items()}
    except urllib.error.HTTPError as exc:
        raw_body = exc.read()
        try:
            return exc.code, json.loads(raw_body or b"null"), {k.lower(): v for k, v in exc.headers.items()}
        except ValueError:
            return exc.code, raw_body, {k.lower(): v for k, v in exc.headers.items()}


def _multipart(fields: dict[str, str], filename: str, content: bytes, content_type: str, token: str) -> tuple[int, object]:
    boundary = "----karma-journey"
    parts = b""
    for name, value in fields.items():
        parts += f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n{value}\r\n".encode()
    parts += (
        f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{filename}\"\r\n"
        f"Content-Type: {content_type}\r\n\r\n".encode()
        + content
        + b"\r\n"
    )
    parts += f"--{boundary}--\r\n".encode()
    status, body, _ = _http(
        "POST",
        "/media/uploads",
        token=token,
        raw=parts,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    return status, body


def _b64(value: bytes) -> str:
    return base64.b64encode(value).decode("ascii")


def _unb64(value: str) -> bytes:
    return base64.b64decode(value, validate=True)


def envelope_aad(
    message_id: str,
    room_id: str,
    sender_device_id: str,
    recipient_device_id: str,
    prekey_id: int,
    ephemeral_key: str,
    sent_at_epoch: int,
    ttl_seconds: int,
    max_hops: int,
) -> str:
    """Canonical AAD shared with the Flutter boundary (KARMA-BITCHAT-AAD-V1)."""
    return "\n".join(
        (
            "KARMA-BITCHAT-AAD-V1",
            message_id,
            room_id,
            sender_device_id,
            recipient_device_id,
            str(prekey_id),
            ephemeral_key,
            str(sent_at_epoch),
            str(ttl_seconds),
            str(max_hops),
        )
    )


def prekey_signed_bytes(device_id: str, key_id: int, public_key_b64: str) -> bytes:
    return f"KARMA-BITCHAT-PREKEY-V1\n{device_id}\n{key_id}\n{public_key_b64}".encode()


class Identity:
    """Client-side boundary: one Ed25519 identity plus signed one-time X25519 prekeys."""

    def __init__(self) -> None:
        self.ed = ed25519.Ed25519PrivateKey.generate()
        self.device_id = str(uuid.uuid4())
        self.identity_pub = _b64(
            self.ed.public_key().public_bytes(
                encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
            )
        )
        self.prekeys: dict[int, tuple[str, x25519.X25519PrivateKey]] = {}
        for key_id in range(1, 25):
            key = x25519.X25519PrivateKey.generate()
            self.prekeys[key_id] = (
                _b64(
                    key.public_key().public_bytes(
                        encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
                    )
                ),
                key,
            )

    def sign(self, data: bytes) -> str:
        return _b64(self.ed.sign(data))

    def prekey_payloads(self) -> list[dict]:
        return [
            {
                "key_id": key_id,
                "public_key": public,
                "signature": self.sign(prekey_signed_bytes(self.device_id, key_id, public)),
            }
            for key_id, (public, _) in self.prekeys.items()
        ]


def journey() -> None:
    print("media upload contract")
    status, priya = _login("priya")
    assert status == 200, "seeded customer priya must exist (run python seed.py)"
    priya_t = priya["access_token"]  # type: ignore[index]
    status, ramesh = _login("ramesh.electric")
    assert status == 200, "seeded worker ramesh.electric must exist (run python seed.py)"
    ramesh_t = ramesh["access_token"]  # type: ignore[index]
    status, me, _ = _http("GET", "/auth/me", token=ramesh_t)
    ramesh_id = me["id"]  # type: ignore[index]
    check("seeded demo accounts sign in", True)

    # The relay journey must be assigned to the seeded worker, so use the category they serve.
    status, profile, _ = _http("GET", "/workers/me/profile", token=ramesh_t)
    assert status == 200 and profile.get("category"), "seeded worker profile must name a category"
    worker_category = profile["category"]  # type: ignore[union-attr]

    status, body = _multipart({"purpose": "gig"}, "evidence.png", PNG, "image/png", priya_t)
    check("upload image -> 201 with API reference", status == 201 and str(body["url"]).startswith("/api/v1/media/objects/"), str(body) if status != 201 else "")  # type: ignore[index]
    ref = body["url"]  # type: ignore[index]
    status, raw_bytes, headers = _http("GET", ref.removeprefix("/api/v1"))
    check(
        "object round-trips bytes with immutable delivery",
        status == 200
        and raw_bytes == PNG
        and headers.get("cache-control") == "public, max-age=31536000, immutable"
        and headers.get("x-content-type-options") == "nosniff",
    )
    status, body = _multipart({"purpose": "post"}, "note.bin", b"not-image-bytes", "application/octet-stream", priya_t)
    check("non-image bytes -> 415", status == 415, str(body) if isinstance(body, dict) else "")
    status, body = _multipart({"purpose": "post"}, "big.png", PNG[:8] + b"0" * (5 * 1024 * 1024 + 1024), "image/png", priya_t)
    check("oversized upload -> 413", status == 413, str(body) if isinstance(body, dict) else "")
    status, body = _multipart({"purpose": "nonsense"}, "x.png", PNG, "image/png", priya_t)
    check("unsupported purpose -> 422", status == 422, str(body) if isinstance(body, dict) else "")

    status, caps, _ = _http("GET", "/locations/capabilities", token=priya_t)
    check("capabilities report consent requirement", status == 200 and caps.get("consent_required") is True, str(caps))  # type: ignore[union-attr]
    status, body, _ = _http("POST", "/locations/geocode", {"query": "Vijay Nagar Indore"}, token=priya_t)
    check("geocode without wire consent -> 422", status == 422)
    status, body, _ = _http(
        "POST", "/locations/geocode", {"query": "Vijay Nagar Indore", "consent": True}, token=priya_t
    )
    check(
        "consented geocode is honest (results, or 503 when unconfigured)",
        status == 200 and isinstance(body, list) or status == 503,
        f"{status}",
    )
    status, body, _ = _http("POST", "/locations/reverse", {"lat": 22.7196, "lng": 75.8577}, token=priya_t)
    check("reverse without wire consent -> 422", status == 422)

    status, categories, _ = _http("GET", "/categories", token=priya_t)
    assert status == 200 and categories, "seeded categories are required"
    matches = [c for c in categories if c["name"] == worker_category]  # type: ignore[union-attr]
    assert matches, f"seeded categories must include {worker_category!r}"
    category_id = matches[0]["id"]  # type: ignore[index]
    status, body, _ = _http(
        "POST",
        "/gigs",
        {
            "category_id": category_id,
            "title": "Location provenance gig",
            "lat": 22.7,
            "lng": 75.85,
            "location_source": "device",
            "location_consent": False,
        },
        token=priya_t,
    )
    check("device location without consent -> 422", status == 422)
    status, gig, _ = _http(
        "POST",
        "/gigs",
        {
            "category_id": category_id,
            "title": "Media journey gig",
            "description": "owned photos, consented location",
            "lat": 22.7196,
            "lng": 75.8577,
            "address_label": "Vijay Nagar (chosen result)",
            "location_source": "geocoded",
            "geocoder": "OpenStreetMap Nominatim",
            "location_consent": True,
            "photos": [ref],
        },
        token=priya_t,
    )
    check(
        "gig with owned photo + consented geocoded location -> 201 with provenance",
        status == 201
        and gig.get("location_source") == "geocoded"  # type: ignore[union-attr]
        and gig.get("geocoder") == "OpenStreetMap Nominatim"  # type: ignore[union-attr]
        and gig.get("photos") == [ref],  # type: ignore[union-attr]
    )
    status, body, _ = _http(
        "POST",
        "/gigs",
        {
            "category_id": category_id,
            "title": "Remote URL photo gig",
            "lat": 22.7,
            "lng": 75.85,
            "photos": ["https://attacker.example/x.jpg"],
        },
        token=priya_t,
    )
    check("arbitrary remote URL photo -> 422", status == 422)

    print("bitchat authenticated relay")
    stranger_handle = f"stranger{uuid.uuid4().hex[:10]}"
    status, body, _ = _http(
        "POST",
        "/auth/register",
        {
            "handle": stranger_handle,
            "display_name": "Stranger",
            "email": f"{stranger_handle}@example.com",
            "password": "SuperSecret123",
            "city": "Indore",
        },
    )
    assert status == 201, "fresh stranger registration failed"
    stranger_t = body["access_token"]  # type: ignore[index]

    status, body, _ = _http(
        "POST",
        "/gigs",
        {
            "category_id": category_id,
            "title": "Bitchat journey gig",
            "description": "relay contract over the wire",
            "lat": 22.7196,
            "lng": 75.8577,
        },
        token=priya_t,
    )
    assert status == 201, "journey gig creation failed"
    gig_id = body["id"]  # type: ignore[index]
    status, body, _ = _http(
        "POST", f"/gigs/{gig_id}/assign?worker_id={ramesh_id}", token=priya_t
    )
    check("assign worker -> sendable conversation", status == 200 and body.get("status") == "assigned")  # type: ignore[union-attr]

    status, body, _ = _http("GET", f"/bitchat/gigs/{gig_id}/session", token=stranger_t)
    check("stranger cannot open the session", status in (403, 404), str(body) if isinstance(body, dict) else "")

    priya_dev, ramesh_dev = Identity(), Identity()
    status, body, _ = _http(
        "POST",
        "/bitchat/devices",
        {
            "device_id": priya_dev.device_id,
            "label": "Journey phone",
            "identity_key": priya_dev.identity_pub,
            "prekeys": priya_dev.prekey_payloads(),
        },
        token=priya_t,
    )
    status2, body2, _ = _http(
        "POST",
        "/bitchat/devices",
        {
            "device_id": ramesh_dev.device_id,
            "label": "Journey phone",
            "identity_key": ramesh_dev.identity_pub,
            "prekeys": ramesh_dev.prekey_payloads(),
        },
        token=ramesh_t,
    )
    check(
        "register devices with 24 signed one-time prekeys",
        status == 200 and body.get("prekeys_available") == 24 and status2 == 200 and body2.get("prekeys_available") == 24,  # type: ignore[union-attr]
    )
    status, body, _ = _http(
        "POST",
        "/bitchat/devices",
        {
            "device_id": priya_dev.device_id,
            "label": "Journey phone",
            "identity_key": priya_dev.identity_pub,
            "prekeys": [
                {
                    "key_id": 300,
                    "public_key": priya_dev.prekeys[1][0],
                    "signature": "A" * 88,  # canonical base64 of 64 bytes, not a real signature
                }
            ],
        },
        token=priya_t,
    )
    check("forged prekey signature -> rejected", status in (400, 403, 422), str(body) if isinstance(body, dict) else "")

    status, session, _ = _http("GET", f"/bitchat/gigs/{gig_id}/session", token=priya_t)
    peers = [d for d in session.get("peer_devices", []) if d["device_id"] == ramesh_dev.device_id]  # type: ignore[union-attr]
    check(
        "session exposes room, can_send and the peer device",
        status == 200
        and session.get("can_send") is True  # type: ignore[union-attr]
        and len(peers) == 1
        and peers[0]["prekeys_available"] >= 1,
    )
    room_id = session["room_id"]  # type: ignore[index]

    status, claimed, _ = _http(
        "POST",
        f"/bitchat/gigs/{gig_id}/prekeys/claim",
        {"sender_device_id": priya_dev.device_id, "recipient_device_id": ramesh_dev.device_id},
        token=priya_t,
    )
    status2, claimed2, _ = _http(
        "POST",
        f"/bitchat/gigs/{gig_id}/prekeys/claim",
        {"sender_device_id": priya_dev.device_id, "recipient_device_id": ramesh_dev.device_id},
        token=priya_t,
    )
    check(
        "atomic one-time claims return distinct keys",
        status == 200 and status2 == 200 and claimed["key_id"] != claimed2["key_id"],  # type: ignore[index]
    )
    status, body, _ = _http(
        "POST",
        f"/bitchat/gigs/{gig_id}/prekeys/claim",
        {"sender_device_id": priya_dev.device_id, "recipient_device_id": ramesh_dev.device_id},
        token=stranger_t,
    )
    check("stranger prekey claim -> refused", status in (403, 404))

    plaintext = "Meet me at the panel — breaker trips under load."
    message_id = str(uuid.uuid4())
    ephemeral = x25519.X25519PrivateKey.generate()
    ephemeral_pub = _b64(
        ephemeral.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw
        )
    )
    nonce = os.urandom(12)
    sent_at = datetime.now(UTC).replace(microsecond=0)
    aad = envelope_aad(
        message_id, room_id, priya_dev.device_id, ramesh_dev.device_id,
        claimed["key_id"], ephemeral_pub, int(sent_at.timestamp()), 10, 3,  # type: ignore[index]
    )
    shared = ephemeral.exchange(
        x25519.X25519PublicKey.from_public_bytes(_unb64(claimed["public_key"]))  # type: ignore[index]
    )
    key = HKDF(
        algorithm=hashes.SHA256(), length=32, salt=nonce, info=aad.encode()
    ).derive(shared)
    box = AESGCM(key).encrypt(nonce, plaintext.encode(), aad.encode())
    ciphertext, mac = box[:-16], box[-16:]
    envelope = {
        "message_id": message_id,
        "room_id": room_id,
        "sender_device_id": priya_dev.device_id,
        "recipient_device_id": ramesh_dev.device_id,
        "prekey_id": claimed["key_id"],  # type: ignore[index]
        "ephemeral_key": ephemeral_pub,
        "nonce": _b64(nonce),
        "ciphertext": _b64(ciphertext),
        "mac": _b64(mac),
        "signature": priya_dev.sign(
            f"{aad}\n{_b64(nonce)}\n{_b64(ciphertext)}\n{_b64(mac)}".encode()
        ),
        "sent_at": sent_at.isoformat().replace("+00:00", "Z"),
        "ttl_seconds": 10,
        "max_hops": 3,
        "transport": "server",
    }
    status, body, _ = _http("POST", f"/bitchat/gigs/{gig_id}/messages", envelope, token=priya_t)
    check("signed encrypted envelope relayed", status == 201, str(body) if isinstance(body, dict) else "")

    # Tampered copy: a fresh reservation plus a fresh message id so the check that fires is
    # the Ed25519 verification, not dedup or the prekey-reservation guard.
    status, fresh_claim, _ = _http(
        "POST",
        f"/bitchat/gigs/{gig_id}/prekeys/claim",
        {"sender_device_id": priya_dev.device_id, "recipient_device_id": ramesh_dev.device_id},
        token=priya_t,
    )
    assert status == 200, "tamper-test prekey claim failed"
    tamper_mid = str(uuid.uuid4())
    aad_t = envelope_aad(
        tamper_mid, room_id, priya_dev.device_id, ramesh_dev.device_id,
        fresh_claim["key_id"], ephemeral_pub, int(sent_at.timestamp()), 10, 3,  # type: ignore[index]
    )
    tampered = dict(
        envelope,
        message_id=tamper_mid,
        prekey_id=fresh_claim["key_id"],  # type: ignore[index]
        signature=priya_dev.sign(f"{aad_t}\n{_b64(nonce)}\n{_b64(ciphertext)}\n{_b64(mac)}".encode()),
    )
    tampered["ciphertext"] = _b64(bytes([ciphertext[0] ^ 1]) + ciphertext[1:])
    status, body, _ = _http("POST", f"/bitchat/gigs/{gig_id}/messages", tampered, token=priya_t)
    check("tampered ciphertext -> signature mismatch 422", status == 422, str(body) if isinstance(body, dict) else "")

    status, inbox, _ = _http(
        "GET", f"/bitchat/gigs/{gig_id}/inbox?device_id={ramesh_dev.device_id}", token=ramesh_t
    )
    received = [e for e in inbox if e["message_id"] == message_id]  # type: ignore[union-attr]
    check("envelope reaches the recipient inbox", len(received) == 1)
    if received:
        env = received[0]
        aad_r = envelope_aad(
            env["message_id"], room_id, env["sender_device_id"], env["recipient_device_id"],
            env["prekey_id"], env["ephemeral_key"],
            int(datetime.fromisoformat(env["sent_at"].replace("Z", "+00:00")).timestamp()),
            env["ttl_seconds"], env["max_hops"],
        )
        authentic = True
        try:
            ed25519.Ed25519PublicKey.from_public_bytes(_unb64(priya_dev.identity_pub)).verify(
                _unb64(env["signature"]),
                f"{aad_r}\n{env['nonce']}\n{env['ciphertext']}\n{env['mac']}".encode(),
            )
        except Exception:
            authentic = False
        check("recipient verifies the sender signature", authentic)
        prekey = ramesh_dev.prekeys[env["prekey_id"]][1]  # type: ignore[index]
        shared_r = prekey.exchange(
            x25519.X25519PublicKey.from_public_bytes(_unb64(env["ephemeral_key"]))
        )
        key_r = HKDF(
            algorithm=hashes.SHA256(), length=32, salt=_unb64(env["nonce"]), info=aad_r.encode()
        ).derive(shared_r)
        try:
            decoded = AESGCM(key_r).decrypt(
                _unb64(env["nonce"]),
                _unb64(env["ciphertext"]) + _unb64(env["mac"]),
                aad_r.encode(),
            ).decode()
            check("recipient decrypts the plaintext round-trip", decoded == plaintext, decoded[:40])
        except Exception as exc:
            check("recipient decrypts the plaintext round-trip", False, repr(exc))
        check("relay never sees the plaintext", plaintext not in (env["ciphertext"] + env["mac"]))

    time.sleep(11)
    _http("GET", f"/bitchat/gigs/{gig_id}/session", token=ramesh_t)  # triggers the expiry purge
    status, inbox, _ = _http(
        "GET", f"/bitchat/gigs/{gig_id}/inbox?device_id={ramesh_dev.device_id}", token=ramesh_t
    )
    check("expired envelope physically deleted", all(e["message_id"] != message_id for e in inbox))  # type: ignore[union-attr]

    status, body, _ = _http(
        "POST",
        f"/bitchat/gigs/{gig_id}/panic",
        {"device_id": ramesh_dev.device_id, "reason": "panic_and_wipe"},
        token=ramesh_t,
    )
    check("panic accepted", status == 200, str(body) if isinstance(body, dict) else "")
    status, body, _ = _http(
        "POST",
        "/bitchat/devices",
        {
            "device_id": ramesh_dev.device_id,
            "label": "again",
            "identity_key": ramesh_dev.identity_pub,
            "prekeys": [],
        },
        token=ramesh_t,
    )
    check("wiped device id is a non-recyclable tombstone", status == 409 and "wiped" in str(body).lower())

    status, admin = _login("karma.admin")
    assert status == 200, "seeded admin karma.admin must exist (run python seed.py)"
    status, incidents, _ = _http("GET", "/admin/safety/incidents", token=admin["access_token"])  # type: ignore[index]
    check(
        "panic left a safety incident for the console",
        status == 200
        and any("panic" in json.dumps(item).lower() for item in incidents),  # type: ignore[union-attr]
    )

    status, mine, _ = _http("GET", "/gigs/mine?role=customer", token=priya_t)
    completed = [g for g in mine if g["status"] == "completed"]  # type: ignore[union-attr]
    if completed:
        done_id = completed[0]["id"]
        status, sess, _ = _http("GET", f"/bitchat/gigs/{done_id}/session", token=priya_t)
        check("completed gig conversation is read-only", status == 200 and sess.get("can_send") is False)  # type: ignore[union-attr]
        status, body, _ = _http(
            "POST",
            f"/bitchat/gigs/{done_id}/prekeys/claim",
            {"sender_device_id": priya_dev.device_id, "recipient_device_id": ramesh_dev.device_id},
            token=priya_t,
        )
        check("completed gig prekey claim -> 409", status == 409)
    else:
        check("completed gig conversation is read-only", True, "no completed gig in this database (skipped)")

    print()
    if _failures:
        print(f"{len(_failures)} check(s) FAILED:")
        for label in _failures:
            print(f"  ✗  {label}")
        raise SystemExit(1)
    print("live media + Bitchat journey: all checks passed")


def _login(identifier: str) -> tuple[int, dict]:
    status, body, _ = _http(
        "POST", "/auth/login", {"identifier": identifier, "password": PASSWORD}
    )
    return status, (body if isinstance(body, dict) else {})


journey()
