"""Contracts for immutable object uploads and consented geocoding."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

MediaPurpose = Literal["post", "gig", "proof_before", "proof_after"]


class MediaObjectOut(BaseModel):
    id: str
    purpose: MediaPurpose
    url: str
    content_type: str
    byte_size: int
    sha256: str


class GeocodeRequest(BaseModel):
    query: str = Field(min_length=3, max_length=200)
    # Literal true makes consent part of the wire contract rather than a UI-only convention.
    consent: Literal[True]
    limit: int = Field(default=5, ge=1, le=8)


class ReverseGeocodeRequest(BaseModel):
    lat: float = Field(ge=-90, le=90)
    lng: float = Field(ge=-180, le=180)
    consent: Literal[True]


class GeocodedPlaceOut(BaseModel):
    place_id: str
    label: str = Field(min_length=1, max_length=200)
    lat: float
    lng: float
    provider: str
    attribution: str


class GeocodingCapabilitiesOut(BaseModel):
    enabled: bool
    provider: str | None = None
    attribution: str | None = None
    consent_required: bool = True


class WorkerLocationUpdate(BaseModel):
    lat: float | None = Field(default=None, ge=-90, le=90)
    lng: float | None = Field(default=None, ge=-180, le=180)
    accuracy_m: float | None = Field(default=None, ge=0, le=100_000)
    location_source: Literal["device"] | None = None
    location_consent: bool = False
    is_available: bool | None = None
