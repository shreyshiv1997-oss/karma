"""Object upload ownership and explicit location-consent contracts."""

from __future__ import annotations

import hashlib
from io import BytesIO

import httpx
import pytest
from botocore.exceptions import ClientError

from app.core.ports import MemoryCache
from app.services.geocoding import GeocodedPlace
from app.services.storage import StoredObject
from tests.conftest import add_category, auth, register_user

pytestmark = pytest.mark.asyncio
_PNG = b"\x89PNG\r\n\x1a\n" + b"validated-image-bytes"


class _ObjectStorage:
    backend_name = "test"

    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str]] = {}

    async def start(self) -> None:
        pass

    async def close(self) -> None:
        pass

    async def put(self, key, data, *, content_type, sha256) -> None:
        assert hashlib.sha256(data).hexdigest() == sha256
        self.objects[key] = (data, content_type)

    async def get(self, key) -> StoredObject | None:
        value = self.objects.get(key)
        return None if value is None else StoredObject(data=value[0], content_type=value[1])

    async def delete(self, key) -> None:
        self.objects.pop(key, None)


@pytest.fixture
def object_storage(monkeypatch):
    from app.routers import media

    storage = _ObjectStorage()
    monkeypatch.setattr(media, "object_storage", storage)
    return storage


async def _upload(client, account: dict, purpose: str = "post", data: bytes = _PNG):
    return await client.post(
        "/api/v1/media/uploads",
        headers=auth(account["token"]),
        data={"purpose": purpose},
        files={"file": ("evidence.png", data, "image/png")},
    )


async def test_an_uploaded_image_has_immutable_metadata_and_can_be_read(
    client, session_factory, object_storage
):
    await add_category(session_factory)
    account = await register_user(client, handle="uploader")

    uploaded = await _upload(client, account)
    assert uploaded.status_code == 201, uploaded.text
    body = uploaded.json()
    assert body["purpose"] == "post"
    assert body["content_type"] == "image/png"
    assert body["byte_size"] == len(_PNG)
    assert body["sha256"] == hashlib.sha256(_PNG).hexdigest()
    assert body["url"].startswith("/api/v1/media/objects/")

    fetched = await client.get(body["url"])
    assert fetched.status_code == 200
    assert fetched.content == _PNG
    assert fetched.headers["content-type"] == "image/png"
    assert fetched.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert fetched.headers["x-content-type-options"] == "nosniff"

    post = await client.post(
        "/api/v1/feed/posts",
        headers=auth(account["token"]),
        json={"kind": "post", "body": "Uploaded, not linked.", "media_urls": [body["url"]]},
    )
    assert post.status_code == 201, post.text
    assert post.json()["media_urls"] == [body["url"]]

    key = next(iter(object_storage.objects))
    object_storage.objects[key] = (b"corrupted", "image/png")
    corrupted = await client.get(body["url"])
    assert corrupted.status_code == 503
    assert corrupted.json()["detail"] == "Media object failed its integrity check"


async def test_remote_wrong_purpose_and_other_users_objects_are_rejected(
    client, session_factory, object_storage
):
    await add_category(session_factory)
    owner = await register_user(client, handle="owner")
    stranger = await register_user(client, handle="stranger")
    uploaded = (await _upload(client, owner, purpose="gig")).json()

    for account, reference in (
        (owner, "https://attacker.example/image.jpg"),
        (owner, f"https://attacker.example{uploaded['url']}"),
        (owner, uploaded["url"]),
        (stranger, uploaded["url"]),
    ):
        response = await client.post(
            "/api/v1/feed/posts",
            headers=auth(account["token"]),
            json={"kind": "post", "body": "No remote references", "media_urls": [reference]},
        )
        assert response.status_code == 422, response.text


async def test_upload_sniffs_bytes_and_enforces_the_configured_limit(
    client, session_factory, object_storage, monkeypatch
):
    from app.routers import media

    await add_category(session_factory)
    account = await register_user(client, handle="uploader")
    not_an_image = await _upload(client, account, data=b"<svg onload=alert(1)>")
    assert not_an_image.status_code == 415

    mismatch = await client.post(
        "/api/v1/media/uploads",
        headers=auth(account["token"]),
        data={"purpose": "post"},
        files={"file": ("fake.jpg", _PNG, "image/jpeg")},
    )
    assert mismatch.status_code == 415

    monkeypatch.setattr(media.settings, "MAX_UPLOAD_SIZE_MB", 1)
    too_large = await _upload(client, account, data=_PNG + b"x" * (1024 * 1024))
    assert too_large.status_code == 413


class _Geocoder:
    enabled = True
    provider_name = "Test Maps"
    attribution = "© Test Maps"

    def __init__(self) -> None:
        self.queries: list[str] = []
        self.coordinates: list[tuple[float, float]] = []

    async def search(self, query: str) -> list[GeocodedPlace]:
        self.queries.append(query)
        return [
            GeocodedPlace(
                place_id="node:42",
                label="Vijay Nagar, Indore, Madhya Pradesh",
                lat=22.7533,
                lng=75.8937,
                provider="Test Maps",
                attribution="© Test Maps",
            )
        ]

    async def reverse(self, lat: float, lng: float) -> GeocodedPlace:
        self.coordinates.append((lat, lng))
        return GeocodedPlace(
            place_id="node:43",
            label="Device location, Indore",
            lat=lat,
            lng=lng,
            provider="Test Maps",
            attribution="© Test Maps",
        )

    async def close(self) -> None:
        pass


async def test_geocoding_requires_wire_level_consent_and_returns_attribution(
    client, session_factory, monkeypatch
):
    from app.routers import locations

    await add_category(session_factory)
    account = await register_user(client, handle="locator")
    fake = _Geocoder()
    monkeypatch.setattr(locations, "geocoder", fake)

    refused = await client.post(
        "/api/v1/locations/geocode",
        headers=auth(account["token"]),
        json={"query": "Vijay Nagar, Indore", "consent": False},
    )
    assert refused.status_code == 422
    assert fake.queries == []

    found = await client.post(
        "/api/v1/locations/geocode",
        headers=auth(account["token"]),
        json={"query": "Vijay Nagar, Indore", "consent": True},
    )
    assert found.status_code == 200, found.text
    assert found.json()[0] == {
        "place_id": "node:42",
        "label": "Vijay Nagar, Indore, Madhya Pradesh",
        "lat": 22.7533,
        "lng": 75.8937,
        "provider": "Test Maps",
        "attribution": "© Test Maps",
    }
    assert fake.queries == ["Vijay Nagar, Indore"]

    reverse_refused = await client.post(
        "/api/v1/locations/reverse",
        headers=auth(account["token"]),
        json={"lat": 22.7533, "lng": 75.8937, "consent": False},
    )
    assert reverse_refused.status_code == 422
    assert fake.coordinates == []

    reverse = await client.post(
        "/api/v1/locations/reverse",
        headers=auth(account["token"]),
        json={"lat": 22.7533, "lng": 75.8937, "consent": True},
    )
    assert reverse.status_code == 200, reverse.text
    assert reverse.json()["label"] == "Device location, Indore"
    assert reverse.json()["provider"] == "Test Maps"
    assert reverse.json()["attribution"] == "© Test Maps"
    assert fake.coordinates == [(22.7533, 75.8937)]


async def test_nominatim_adapter_parses_attributed_results_and_caches_by_request_hash(
    monkeypatch,
):
    from app.services import geocoding
    from app.services.geocoding import NominatimGeocoder

    # Exercise one search and one reverse upstream call in the same test window. Production's
    # public-provider default remains one request per second.
    monkeypatch.setattr(geocoding.settings, "GEOCODING_REQUESTS_PER_SECOND", 2)
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        place = {
            "osm_type": "node",
            "osm_id": 42,
            "display_name": "Vijay Nagar, Indore",
            "lat": "22.7533",
            "lon": "75.8937",
        }
        return httpx.Response(
            200,
            json=place if request.url.path.endswith("/reverse") else [place],
        )

    client = httpx.AsyncClient(
        base_url="https://maps.test",
        transport=httpx.MockTransport(respond),
        headers={"User-Agent": "KARMA-test"},
    )
    cache = MemoryCache()
    geocoder = NominatimGeocoder(
        base_url="https://maps.test",
        user_agent="KARMA-test",
        country_codes="in",
        client=client,
        cache=cache,
    )
    try:
        first = await geocoder.search(" Vijay   Nagar ")
        second = await geocoder.search("vijay nagar")
        reverse_first = await geocoder.reverse(22.753301, 75.893699)
        reverse_second = await geocoder.reverse(22.7533, 75.8937)
    finally:
        await geocoder.close()

    assert first == second
    assert reverse_first == reverse_second
    assert first[0].place_id == "node:42"
    assert first[0].provider == "OpenStreetMap Nominatim"
    assert len(requests) == 2
    assert requests[0].url.params["countrycodes"] == "in"
    assert requests[1].url.params["lat"] == "22.75330"
    assert all("22.75330" not in key and "75.89370" not in key for key in cache._values)


async def test_gig_records_selected_location_provenance_and_uploaded_photos(
    client, session_factory, object_storage
):
    category_id = await add_category(session_factory)
    customer = await register_user(client, handle="customer")
    enabled = await client.post(
        "/api/v1/auth/capability/can_hire",
        headers=auth(customer["token"]),
    )
    assert enabled.status_code == 200
    photo = (await _upload(client, customer, purpose="gig")).json()
    payload = {
        "category_id": category_id,
        "title": "Repair kitchen wiring",
        "description": "Two sockets are dead.",
        "lat": 22.7533,
        "lng": 75.8937,
        "address_label": "Vijay Nagar, Indore",
        "location_source": "geocoded",
        "location_accuracy_m": 15,
        "geocoder": "Test Maps",
        "estimated_hours": 2,
        "photos": [photo["url"]],
    }

    no_consent = await client.post(
        "/api/v1/gigs",
        headers=auth(customer["token"]),
        json=payload,
    )
    assert no_consent.status_code == 422

    created = await client.post(
        "/api/v1/gigs",
        headers=auth(customer["token"]),
        json={**payload, "location_consent": True},
    )
    assert created.status_code == 201, created.text
    assert created.json()["location_source"] == "geocoded"
    assert created.json()["geocoder"] == "Test Maps"
    assert created.json()["photos"] == [photo["url"]]


class _S3Client:
    def __init__(self) -> None:
        self.created = False
        self.objects: dict[str, tuple[bytes, str]] = {}
        self.closed = False

    def head_bucket(self, **kwargs) -> None:
        del kwargs
        if not self.created:
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchBucket"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "HeadBucket",
            )

    def create_bucket(self, **kwargs) -> None:
        assert kwargs["Bucket"] == "karma-media"
        self.created = True

    def put_object(self, **kwargs) -> None:
        self.objects[kwargs["Key"]] = (kwargs["Body"], kwargs["ContentType"])

    def get_object(self, **kwargs) -> dict:
        try:
            data, content_type = self.objects[kwargs["Key"]]
        except KeyError as exc:
            raise ClientError(
                {
                    "Error": {"Code": "NoSuchKey"},
                    "ResponseMetadata": {"HTTPStatusCode": 404},
                },
                "GetObject",
            ) from exc
        return {"Body": BytesIO(data), "ContentType": content_type}

    def delete_object(self, **kwargs) -> None:
        self.objects.pop(kwargs["Key"], None)

    def close(self) -> None:
        self.closed = True


async def test_s3_port_creates_bucket_and_round_trips_without_exposing_credentials():
    from app.services.storage import S3ObjectStorage

    client = _S3Client()
    storage = S3ObjectStorage(
        endpoint="http://storage:8333",
        access_key="not-returned",
        secret_key="not-returned",
        bucket="karma-media",
        region="us-east-1",
        client=client,
    )
    await storage.start()
    assert client.created is True
    await storage.put(
        "users/1/example.png",
        _PNG,
        content_type="image/png",
        sha256=hashlib.sha256(_PNG).hexdigest(),
    )
    result = await storage.get("users/1/example.png")
    assert result == StoredObject(data=_PNG, content_type="image/png")
    await storage.delete("users/1/example.png")
    assert await storage.get("users/1/example.png") is None
    await storage.close()
    assert client.closed is True
