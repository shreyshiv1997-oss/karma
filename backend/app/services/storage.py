"""Immutable object-storage boundary used by authenticated media uploads.

Development stores objects under ``UPLOAD_DIR``. Production is required to use S3-compatible
storage (the Compose stack supplies SeaweedFS through its S3 endpoint). Routes and database rows
never know which backend is active, and clients never receive storage credentials or internal
bucket keys.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from app.core.config import settings


class StorageUnavailable(RuntimeError):
    """The configured object store could not complete an operation."""


@dataclass(frozen=True)
class StoredObject:
    data: bytes
    content_type: str


class ObjectStoragePort(Protocol):
    backend_name: str

    async def start(self) -> None: ...
    async def close(self) -> None: ...
    async def put(self, key: str, data: bytes, *, content_type: str, sha256: str) -> None: ...
    async def get(self, key: str) -> StoredObject | None: ...
    async def delete(self, key: str) -> None: ...


class LocalObjectStorage:
    backend_name = "local"

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root).resolve()

    def _path(self, key: str) -> Path:
        path = (self._root / key).resolve()
        if self._root not in path.parents:
            raise ValueError("Invalid object key")
        return path

    async def start(self) -> None:
        await asyncio.to_thread(self._root.mkdir, parents=True, exist_ok=True)

    async def close(self) -> None:
        """The filesystem backend owns no persistent handles."""

    async def put(self, key: str, data: bytes, *, content_type: str, sha256: str) -> None:
        del content_type, sha256
        path = self._path(key)

        def write() -> None:
            path.parent.mkdir(parents=True, exist_ok=True)
            temporary = path.with_suffix(f"{path.suffix}.tmp")
            temporary.write_bytes(data)
            temporary.replace(path)

        await asyncio.to_thread(write)

    async def get(self, key: str) -> StoredObject | None:
        path = self._path(key)
        try:
            data = await asyncio.to_thread(path.read_bytes)
        except FileNotFoundError:
            return None
        return StoredObject(data=data, content_type="application/octet-stream")

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(self._path(key).unlink)
        except FileNotFoundError:
            pass


class S3ObjectStorage:
    backend_name = "s3"

    def __init__(
        self,
        *,
        endpoint: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
        region: str,
        client: object | None = None,
    ) -> None:
        self._bucket = bucket
        self._region = region
        if client is None:
            # boto3 is deliberately imported only for the S3 implementation. Local development
            # and tests remain zero-service even though production fails closed onto storage.
            import boto3
            from botocore.config import Config

            client = boto3.client(
                "s3",
                endpoint_url=endpoint,
                aws_access_key_id=access_key,
                aws_secret_access_key=secret_key,
                region_name=region,
                config=Config(s3={"addressing_style": "path"}),
            )
        self._client = client

    async def start(self) -> None:
        from botocore.exceptions import ClientError

        try:
            await asyncio.to_thread(self._client.head_bucket, Bucket=self._bucket)
            return
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)
            if code not in {"404", "NoSuchBucket", "NotFound"} and status != 404:
                raise StorageUnavailable("Object storage bucket is unavailable") from exc
        except Exception as exc:
            raise StorageUnavailable("Object storage endpoint is unavailable") from exc

        args: dict[str, object] = {"Bucket": self._bucket}
        if self._region != "us-east-1":
            args["CreateBucketConfiguration"] = {"LocationConstraint": self._region}
        try:
            await asyncio.to_thread(self._client.create_bucket, **args)
        except Exception as exc:
            raise StorageUnavailable("Object storage bucket could not be created") from exc

    async def close(self) -> None:
        close = getattr(self._client, "close", None)
        if close is not None:
            await asyncio.to_thread(close)

    async def put(self, key: str, data: bytes, *, content_type: str, sha256: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.put_object,
                Bucket=self._bucket,
                Key=key,
                Body=data,
                ContentLength=len(data),
                ContentType=content_type,
                CacheControl="public, max-age=31536000, immutable",
                Metadata={"sha256": sha256},
            )
        except Exception as exc:
            raise StorageUnavailable("Object upload failed") from exc

    async def get(self, key: str) -> StoredObject | None:
        from botocore.exceptions import ClientError

        try:
            response = await asyncio.to_thread(
                self._client.get_object,
                Bucket=self._bucket,
                Key=key,
            )
            data = await asyncio.to_thread(response["Body"].read)
            return StoredObject(
                data=data,
                content_type=str(response.get("ContentType") or "application/octet-stream"),
            )
        except ClientError as exc:
            code = str(exc.response.get("Error", {}).get("Code", ""))
            status = int(exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0) or 0)
            if code in {"404", "NoSuchKey", "NotFound"} or status == 404:
                return None
            raise StorageUnavailable("Object storage read failed") from exc
        except Exception as exc:
            raise StorageUnavailable("Object storage read failed") from exc

    async def delete(self, key: str) -> None:
        try:
            await asyncio.to_thread(
                self._client.delete_object,
                Bucket=self._bucket,
                Key=key,
            )
        except Exception as exc:
            raise StorageUnavailable("Object deletion failed") from exc


def build_object_storage() -> ObjectStoragePort:
    if settings.OBJECT_STORAGE_BACKEND == "s3":
        if settings.S3_ACCESS_KEY is None or settings.S3_SECRET_KEY is None:
            raise RuntimeError("S3 object storage credentials are incomplete")
        return S3ObjectStorage(
            endpoint=settings.S3_ENDPOINT,
            access_key=settings.S3_ACCESS_KEY.get_secret_value(),
            secret_key=settings.S3_SECRET_KEY.get_secret_value(),
            bucket=settings.S3_BUCKET,
            region=settings.S3_REGION,
        )
    return LocalObjectStorage(settings.UPLOAD_DIR)


object_storage: ObjectStoragePort = build_object_storage()
