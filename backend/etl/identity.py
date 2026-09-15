"""Identity resolution for the merge ETL.

This module carries risk R1 from the analysis: merging two *different humans* into one
account is unrecoverable, so the default behaviour is to refuse.

Rules, in order of precedence:
  1. A phone match is authoritative. Labour Link required a verified phone; it is the
     strongest identifier either system holds.
  2. An email match merges only when neither side also carries a conflicting phone.
  3. A handle collision is never merged -- handles are chosen, not verified, so two
     people can legitimately want the same one. The later arrival gets a suffixed handle
     and lands in the review queue.
  4. Anything ambiguous goes to the manual-review queue rather than being guessed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Decision = Literal["merge", "create", "review"]


@dataclass(frozen=True)
class SourceIdentity:
    """One row from one source system, normalised."""

    source: str  # "tatwamasi" | "labourlink"
    source_id: int
    phone: str | None
    email: str | None
    handle: str | None
    display_name: str
    reputation: float | None
    password_hash: str | None

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"


@dataclass
class Resolution:
    decision: Decision
    reason: str
    # Set when merging into an already-imported identity.
    merge_into: str | None = None
    # Set when the handle had to be changed to avoid a collision.
    new_handle: str | None = None


@dataclass
class IdentityResolver:
    """Stateful resolver: call ``resolve`` for each incoming row in order."""

    by_phone: dict[str, str] = field(default_factory=dict)
    by_email: dict[str, str] = field(default_factory=dict)
    by_handle: dict[str, str] = field(default_factory=dict)
    # canonical key -> the phone/email/handle it owns
    phone_of: dict[str, str | None] = field(default_factory=dict)
    email_of: dict[str, str | None] = field(default_factory=dict)
    queue: list[dict] = field(default_factory=list)

    def resolve(self, incoming: SourceIdentity) -> Resolution:
        phone = _norm_phone(incoming.phone)
        email = _norm_email(incoming.email)
        handle = _norm_handle(incoming.handle) or _derive_handle(incoming)

        # ── Rule 1: phone is authoritative ─────────────────────────────
        if phone and phone in self.by_phone:
            canonical = self.by_phone[phone]
            return self._merge(canonical, incoming, phone, email, handle, "same verified phone")

        # ── Rule 2: email, but only when it cannot contradict a phone ──
        if email and email in self.by_email:
            canonical = self.by_email[email]
            known_phone = self.phone_of.get(canonical)
            if phone and known_phone and phone != known_phone:
                # Same email, two different verified phones: two different people
                # sharing an address, or a data error. Never guess.
                self._enqueue(incoming, canonical, "email matches but phones conflict")
                return Resolution("review", "email matches an existing account with a different phone")
            return self._merge(canonical, incoming, phone, email, handle, "same email")

        # ── Rule 3: handle collision is never a merge ──────────────────
        if handle in self.by_handle:
            new_handle = self._suffix(handle)
            self._register(incoming.key, phone, email, new_handle)
            self._enqueue(incoming, self.by_handle[handle], "handle already taken; suffixed")
            return Resolution(
                "create",
                "handle collision — a new account was created with a suffixed handle",
                new_handle=new_handle,
            )

        # ── Rule 4: nothing matched, clean create ──────────────────────
        self._register(incoming.key, phone, email, handle)
        return Resolution("create", "no matching identity")

    # -- internals -----------------------------------------------------
    def _merge(
        self,
        canonical: str,
        incoming: SourceIdentity,
        phone: str | None,
        email: str | None,
        handle: str | None,
        reason: str,
    ) -> Resolution:
        # Backfill identifiers the canonical record was missing.
        if phone and not self.phone_of.get(canonical):
            self.phone_of[canonical] = phone
            self.by_phone[phone] = canonical
        if email and not self.email_of.get(canonical):
            self.email_of[canonical] = email
            self.by_email[email] = canonical
        return Resolution("merge", reason, merge_into=canonical)

    def _register(self, key: str, phone: str | None, email: str | None, handle: str) -> None:
        if phone:
            self.by_phone[phone] = key
        if email:
            self.by_email[email] = key
        self.by_handle[handle] = key
        self.phone_of[key] = phone
        self.email_of[key] = email

    def _enqueue(self, incoming: SourceIdentity, canonical: str, reason: str) -> None:
        self.queue.append(
            {
                "source": incoming.source,
                "source_id": incoming.source_id,
                "display_name": incoming.display_name,
                "phone": incoming.phone,
                "email": incoming.email,
                "conflicts_with": canonical,
                "reason": reason,
            }
        )

    def _suffix(self, handle: str) -> str:
        n = 2
        while f"{handle}{n}" in self.by_handle:
            n += 1
        return f"{handle}{n}"


# ── normalisers -------------------------------------------------------------
def _norm_phone(raw: str | None) -> str | None:
    if not raw:
        return None
    digits = "".join(ch for ch in raw if ch.isdigit())
    return f"+{digits}" if digits else None


def _norm_email(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().lower()
    return cleaned or None


def _norm_handle(raw: str | None) -> str | None:
    if not raw:
        return None
    cleaned = raw.strip().lower().replace(" ", "_")
    return cleaned or None


def _derive_handle(identity: SourceIdentity) -> str:
    """A Labour Link user has no handle; derive a stable, collision-checked one."""
    base = _norm_handle(identity.display_name)
    if not base:
        base = f"user{identity.source_id}"
    # Keep it inside the schema's 3..30 [a-z0-9_.] contract.
    base = "".join(ch for ch in base if ch.isalnum() or ch in "_.")[:24]
    return base or f"user{identity.source_id}"
