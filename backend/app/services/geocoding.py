"""Privacy-explicit geocoding boundary.

Coordinates are never invented from an address. A caller must opt in on every geocoding request;
the router then forwards only that request to the configured provider. Results are cached under a
one-way query hash and provider calls share a Redis-backed application-wide rate window in
production, which is required by public Nominatim-style services.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol

import httpx

from app.core.config import settings
from app.core.ports import build_cache

_PROVIDER = "OpenStreetMap Nominatim"
_ATTRIBUTION = "© OpenStreetMap contributors"


class GeocodingUnavailable(RuntimeError):
    pass


class GeocodingRateLimited(RuntimeError):
    pass


@dataclass(frozen=True)
class GeocodedPlace:
    place_id: str
    label: str
    lat: float
    lng: float
    provider: str = _PROVIDER
    attribution: str = _ATTRIBUTION


class GeocoderPort(Protocol):
    enabled: bool
    provider_name: str | None
    attribution: str | None

    async def search(self, query: str) -> list[GeocodedPlace]: ...
    async def reverse(self, lat: float, lng: float) -> GeocodedPlace | None: ...
    async def close(self) -> None: ...


class DisabledGeocoder:
    enabled = False
    provider_name = None
    attribution = None

    async def search(self, query: str) -> list[GeocodedPlace]:
        del query
        raise GeocodingUnavailable("Address search is not configured")

    async def reverse(self, lat: float, lng: float) -> GeocodedPlace | None:
        del lat, lng
        raise GeocodingUnavailable("Reverse geocoding is not configured")

    async def close(self) -> None:
        """No network client to close."""


class NominatimGeocoder:
    enabled = True
    provider_name = _PROVIDER
    attribution = _ATTRIBUTION

    def __init__(
        self,
        *,
        base_url: str,
        user_agent: str,
        country_codes: str,
        client: httpx.AsyncClient | None = None,
        cache=None,
    ) -> None:
        self._country_codes = country_codes
        self._client = client or httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
        )
        self._cache = cache or build_cache()

    async def _budget(self) -> None:
        try:
            count = await self._cache.incr_window("karma:geocoding:provider-budget", 1)
        except Exception as exc:
            # Without the shared budget, multiple API workers could exceed the provider's
            # policy. Fail closed rather than becoming an accidental open geocoding proxy.
            raise GeocodingUnavailable("Address lookup protections are unavailable") from exc
        if count > settings.GEOCODING_REQUESTS_PER_SECOND:
            raise GeocodingRateLimited("Address lookup is busy; wait a moment and try again")

    async def _get_cached(self, key: str) -> object | None:
        try:
            raw = await self._cache.get(key)
        except Exception as exc:
            raise GeocodingUnavailable("Address lookup cache is unavailable") from exc
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            try:
                await self._cache.delete(key)
            except Exception as exc:
                raise GeocodingUnavailable("Address lookup cache is unavailable") from exc
            return None

    async def _set_cached(self, key: str, value: object) -> None:
        try:
            await self._cache.set(
                key,
                json.dumps(value, separators=(",", ":"), ensure_ascii=False),
                ttl=settings.GEOCODING_CACHE_SECONDS,
            )
        except Exception as exc:
            raise GeocodingUnavailable("Address lookup cache is unavailable") from exc

    async def _request(self, path: str, params: dict[str, str | int]) -> object:
        await self._budget()
        try:
            response = await self._client.get(path, params=params)
            response.raise_for_status()
            return response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise GeocodingUnavailable("The address provider is temporarily unavailable") from exc

    @staticmethod
    def _place(item: object) -> GeocodedPlace | None:
        if not isinstance(item, dict):
            return None
        try:
            lat = float(item["lat"])
            lng = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            return None
        label = str(item.get("display_name") or "").strip()[:200]
        if not label or not (-90 <= lat <= 90) or not (-180 <= lng <= 180):
            return None
        osm_type = str(item.get("osm_type") or "place")[:20]
        osm_id = str(item.get("osm_id") or item.get("place_id") or "")[:80]
        if not osm_id:
            return None
        return GeocodedPlace(
            place_id=f"{osm_type}:{osm_id}",
            label=label,
            lat=lat,
            lng=lng,
        )

    async def search(self, query: str) -> list[GeocodedPlace]:
        normalized = " ".join(query.strip().split())
        digest = hashlib.sha256(
            f"{self._country_codes}\0{normalized.casefold()}".encode()
        ).hexdigest()
        key = f"karma:geocoding:search:{digest}"
        payload = await self._get_cached(key)
        if payload is None:
            payload = await self._request(
                "/search",
                {
                    "q": normalized,
                    "format": "jsonv2",
                    "limit": 8,
                    "countrycodes": self._country_codes,
                    "addressdetails": 0,
                },
            )
            await self._set_cached(key, payload)
        if not isinstance(payload, list):
            raise GeocodingUnavailable("The address provider returned an invalid response")
        return [place for item in payload if (place := self._place(item)) is not None]

    async def reverse(self, lat: float, lng: float) -> GeocodedPlace | None:
        rounded_lat = round(lat, 5)
        rounded_lng = round(lng, 5)
        digest = hashlib.sha256(
            f"{rounded_lat:.5f}\0{rounded_lng:.5f}".encode()
        ).hexdigest()
        key = f"karma:geocoding:reverse:{digest}"
        payload = await self._get_cached(key)
        if payload is None:
            payload = await self._request(
                "/reverse",
                {
                    "lat": f"{rounded_lat:.5f}",
                    "lon": f"{rounded_lng:.5f}",
                    "format": "jsonv2",
                    "addressdetails": 0,
                },
            )
            await self._set_cached(key, payload)
        return self._place(payload)

    async def close(self) -> None:
        await self._client.aclose()


def build_geocoder() -> GeocoderPort:
    if settings.GEOCODING_PROVIDER == "nominatim":
        return NominatimGeocoder(
            base_url=settings.GEOCODING_BASE_URL,
            user_agent=settings.GEOCODING_USER_AGENT,
            country_codes=settings.GEOCODING_COUNTRY_CODES,
        )
    return DisabledGeocoder()


geocoder: GeocoderPort = build_geocoder()
