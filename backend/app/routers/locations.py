"""Consented address search and reverse-geocoding contracts."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException

from app.core.deps import CurrentUser
from app.schemas.media import (
    GeocodedPlaceOut,
    GeocodeRequest,
    GeocodingCapabilitiesOut,
    ReverseGeocodeRequest,
)
from app.services.geocoding import (
    GeocodingRateLimited,
    GeocodingUnavailable,
    geocoder,
)

router = APIRouter(prefix="/locations", tags=["Locations"])


@router.get("/capabilities", response_model=GeocodingCapabilitiesOut)
async def capabilities(user: CurrentUser) -> GeocodingCapabilitiesOut:
    del user
    return GeocodingCapabilitiesOut(
        enabled=geocoder.enabled,
        provider=geocoder.provider_name,
        attribution=geocoder.attribution,
    )


def _provider_error(exc: Exception) -> HTTPException:
    if isinstance(exc, GeocodingRateLimited):
        return HTTPException(status_code=429, detail=str(exc))
    return HTTPException(status_code=503, detail=str(exc))


@router.post("/geocode", response_model=list[GeocodedPlaceOut])
async def geocode(payload: GeocodeRequest, user: CurrentUser) -> list[GeocodedPlaceOut]:
    del user  # authentication prevents an open proxy; consent is validated by the schema
    try:
        places = await geocoder.search(payload.query)
    except (GeocodingUnavailable, GeocodingRateLimited) as exc:
        raise _provider_error(exc) from exc
    return [GeocodedPlaceOut(**place.__dict__) for place in places[: payload.limit]]


@router.post("/reverse", response_model=GeocodedPlaceOut | None)
async def reverse_geocode(
    payload: ReverseGeocodeRequest,
    user: CurrentUser,
) -> GeocodedPlaceOut | None:
    del user
    try:
        place = await geocoder.reverse(payload.lat, payload.lng)
    except (GeocodingUnavailable, GeocodingRateLimited) as exc:
        raise _provider_error(exc) from exc
    return None if place is None else GeocodedPlaceOut(**place.__dict__)
