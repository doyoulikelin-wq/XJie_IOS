"""Fail-closed object storage for retryable private source objects.

Production dietary images must survive API/worker container replacement, so
the default backend is the repository's existing S3-compatible configuration.
The local implementation exists only for explicitly identified development or
test processes and is never an automatic runtime fallback for S3 failures.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Mapping, Protocol
from urllib.parse import urlparse
import uuid

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from app.core.config import Settings, settings


DEVELOPMENT_ENVIRONMENTS = frozenset({"dev", "development", "test", "testing"})
MAX_OBJECT_KEY_LENGTH = 1024
_BUCKET_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]$")
_PLACEHOLDER_ENDPOINTS = frozenset({"http://minio:9000", "http://localhost:9000"})
_PLACEHOLDER_CREDENTIALS = frozenset({"minioadmin", "change_me", "changeme"})


class ObjectStorageError(RuntimeError):
    """Base error whose message is safe to return without provider details."""


class ObjectStorageConfigurationError(ObjectStorageError):
    pass


class ObjectStorageUnavailableError(ObjectStorageError):
    pass


class ObjectStorageNotFoundError(ObjectStorageError):
    pass


class ObjectStorageIntegrityError(ObjectStorageError):
    pass


@dataclass(frozen=True)
class StoredObjectMetadata:
    key: str
    sha256: str
    size_bytes: int
    content_type: str
    owner_user_id: int
    subject_user_id: int

    def provider_metadata(self) -> dict[str, str]:
        return {
            "sha256": self.sha256,
            "size-bytes": str(self.size_bytes),
            "content-type": self.content_type,
            "owner-user-id": str(self.owner_user_id),
            "subject-user-id": str(self.subject_user_id),
        }


class PrivateObjectStore(Protocol):
    backend_name: str

    def put(self, *, content: bytes, metadata: StoredObjectMetadata) -> None: ...

    def get(self, *, metadata: StoredObjectMetadata, max_bytes: int) -> bytes: ...


def _validate_metadata(metadata: StoredObjectMetadata, *, max_bytes: int) -> None:
    key = metadata.key
    if (
        not key
        or len(key.encode("utf-8")) > MAX_OBJECT_KEY_LENGTH
        or key.startswith("/")
        or "\\" in key
        or any(part in {"", ".", ".."} for part in key.split("/"))
    ):
        raise ObjectStorageIntegrityError("Object storage key is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", metadata.sha256):
        raise ObjectStorageIntegrityError("Object storage digest is invalid")
    if metadata.size_bytes <= 0 or metadata.size_bytes > max_bytes:
        raise ObjectStorageIntegrityError("Object storage size is invalid")
    if (
        metadata.owner_user_id <= 0
        or metadata.subject_user_id <= 0
        or not metadata.content_type
        or len(metadata.content_type) > 128
        or any(character in metadata.content_type for character in "\0\r\n")
    ):
        raise ObjectStorageIntegrityError("Object storage metadata is invalid")


def _verify_content(content: bytes, metadata: StoredObjectMetadata, *, max_bytes: int) -> None:
    if len(content) != metadata.size_bytes or len(content) > max_bytes:
        raise ObjectStorageIntegrityError("Object storage size mismatch")
    if hashlib.sha256(content).hexdigest() != metadata.sha256:
        raise ObjectStorageIntegrityError("Object storage digest mismatch")


class LocalPrivateObjectStore:
    backend_name = "local"

    def __init__(self, root: str) -> None:
        self._root = Path(root).expanduser().resolve()

    def _target_for_key(self, key: str) -> Path:
        if (
            not key
            or len(key.encode("utf-8")) > MAX_OBJECT_KEY_LENGTH
            or key.startswith("/")
            or "\\" in key
            or any(part in {"", ".", ".."} for part in key.split("/"))
        ):
            raise ObjectStorageIntegrityError("Local object key is invalid")
        relative = Path(key)
        candidate = self._root / relative
        if candidate.is_symlink():
            raise ObjectStorageIntegrityError("Local object cannot be a symlink")
        resolved_parent = candidate.parent.resolve()
        if self._root != resolved_parent and self._root not in resolved_parent.parents:
            raise ObjectStorageIntegrityError("Local object path is invalid")
        return resolved_parent / candidate.name

    def _target(self, metadata: StoredObjectMetadata, *, max_bytes: int) -> Path:
        _validate_metadata(metadata, max_bytes=max_bytes)
        return self._target_for_key(metadata.key)

    def put(self, *, content: bytes, metadata: StoredObjectMetadata) -> None:
        target = self._target(metadata, max_bytes=metadata.size_bytes)
        _verify_content(content, metadata, max_bytes=metadata.size_bytes)
        self._root.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file():
                raise ObjectStorageIntegrityError("Local object collision")
            _verify_content(target.read_bytes(), metadata, max_bytes=metadata.size_bytes)
            return
        temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.upload"
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)

    def get(self, *, metadata: StoredObjectMetadata, max_bytes: int) -> bytes:
        target = self._target(metadata, max_bytes=max_bytes)
        if not target.is_file():
            raise ObjectStorageNotFoundError("Object storage object not found")
        content = target.read_bytes()
        _verify_content(content, metadata, max_bytes=max_bytes)
        return content

    def get_legacy(self, *, key: str, sha256: str, max_bytes: int) -> bytes:
        """Read an unreleased v1 local draft only in explicit dev/test mode."""

        if not re.fullmatch(r"[0-9a-f]{64}", sha256):
            raise ObjectStorageIntegrityError("Legacy object digest is invalid")
        target = self._target_for_key(key)
        if not target.is_file():
            raise ObjectStorageNotFoundError("Object storage object not found")
        if target.stat().st_size <= 0 or target.stat().st_size > max_bytes:
            raise ObjectStorageIntegrityError("Legacy object size is invalid")
        content = target.read_bytes()
        if hashlib.sha256(content).hexdigest() != sha256:
            raise ObjectStorageIntegrityError("Legacy object digest mismatch")
        return content


class S3PrivateObjectStore:
    backend_name = "s3"

    def __init__(
        self,
        *,
        client,
        bucket: str,
        server_side_encryption: str,
        sse_kms_key_id: str | None,
    ) -> None:
        self._client = client
        self._bucket = bucket
        self._server_side_encryption = server_side_encryption
        self._sse_kms_key_id = sse_kms_key_id

    @staticmethod
    def _is_not_found(exc: ClientError) -> bool:
        error = exc.response.get("Error") if isinstance(exc.response, dict) else None
        code = str((error or {}).get("Code", "")).lower()
        status = (exc.response.get("ResponseMetadata") or {}).get("HTTPStatusCode")
        return code in {"404", "nosuchkey", "notfound"} or status == 404

    def _head(self, key: str) -> Mapping | None:
        try:
            return self._client.head_object(Bucket=self._bucket, Key=key)
        except ClientError as exc:
            if self._is_not_found(exc):
                return None
            raise ObjectStorageUnavailableError("Object storage is unavailable") from exc
        except (BotoCoreError, OSError) as exc:
            raise ObjectStorageUnavailableError("Object storage is unavailable") from exc

    def _verify_head(self, head: Mapping, metadata: StoredObjectMetadata) -> None:
        provider_metadata = {
            str(key).lower(): str(value)
            for key, value in (head.get("Metadata") or {}).items()
        }
        if int(head.get("ContentLength", -1)) != metadata.size_bytes:
            raise ObjectStorageIntegrityError("Object storage size mismatch")
        if head.get("ContentType") != metadata.content_type:
            raise ObjectStorageIntegrityError("Object storage content type mismatch")
        expected = metadata.provider_metadata()
        if any(provider_metadata.get(key) != value for key, value in expected.items()):
            raise ObjectStorageIntegrityError("Object storage metadata mismatch")
        if head.get("ServerSideEncryption") != self._server_side_encryption:
            raise ObjectStorageIntegrityError("Object storage encryption mismatch")
        if (
            self._server_side_encryption == "aws:kms"
            and head.get("SSEKMSKeyId") != self._sse_kms_key_id
        ):
            raise ObjectStorageIntegrityError("Object storage KMS key mismatch")

    def put(self, *, content: bytes, metadata: StoredObjectMetadata) -> None:
        _validate_metadata(metadata, max_bytes=metadata.size_bytes)
        _verify_content(content, metadata, max_bytes=metadata.size_bytes)
        existing = self._head(metadata.key)
        if existing is not None:
            self._verify_head(existing, metadata)
            if self.get(metadata=metadata, max_bytes=metadata.size_bytes) != content:
                raise ObjectStorageIntegrityError("Object storage collision")
            return
        encryption_arguments = {
            "ServerSideEncryption": self._server_side_encryption,
        }
        if self._sse_kms_key_id is not None:
            encryption_arguments["SSEKMSKeyId"] = self._sse_kms_key_id
        try:
            self._client.put_object(
                Bucket=self._bucket,
                Key=metadata.key,
                Body=content,
                ContentLength=metadata.size_bytes,
                ContentType=metadata.content_type,
                Metadata=metadata.provider_metadata(),
                **encryption_arguments,
            )
        except (BotoCoreError, ClientError, OSError) as exc:
            raise ObjectStorageUnavailableError("Object storage is unavailable") from exc
        written = self._head(metadata.key)
        if written is None:
            raise ObjectStorageUnavailableError("Object storage write was not durable")
        self._verify_head(written, metadata)
        if self.get(metadata=metadata, max_bytes=metadata.size_bytes) != content:
            raise ObjectStorageIntegrityError("Object storage write verification failed")

    def get(self, *, metadata: StoredObjectMetadata, max_bytes: int) -> bytes:
        _validate_metadata(metadata, max_bytes=max_bytes)
        head = self._head(metadata.key)
        if head is None:
            raise ObjectStorageNotFoundError("Object storage object not found")
        self._verify_head(head, metadata)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=metadata.key)
            body = response["Body"]
            try:
                content = body.read(metadata.size_bytes + 1)
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        except (BotoCoreError, ClientError, KeyError, OSError) as exc:
            raise ObjectStorageUnavailableError("Object storage is unavailable") from exc
        _verify_content(content, metadata, max_bytes=max_bytes)
        return content


def validate_private_object_storage_configuration(
    configured_settings: Settings = settings,
) -> None:
    """Validate storage selection without contacting or exposing the provider."""

    backend = configured_settings.DIETARY_IMAGE_STORAGE_BACKEND.strip().lower()
    environment = configured_settings.APP_ENV.strip().lower()
    if backend == "local":
        if environment not in DEVELOPMENT_ENVIRONMENTS:
            raise ObjectStorageConfigurationError(
                "Local object storage is forbidden outside development or test"
            )
        root = configured_settings.LOCAL_STORAGE_DIR.strip()
        if not root:
            raise ObjectStorageConfigurationError("Local object storage is not configured")
        return
    if backend != "s3":
        raise ObjectStorageConfigurationError("Object storage backend is invalid")

    endpoint = configured_settings.S3_ENDPOINT_URL.strip()
    bucket = configured_settings.S3_BUCKET.strip()
    region = configured_settings.S3_REGION.strip()
    access_key = configured_settings.S3_ACCESS_KEY.strip()
    secret_key = configured_settings.S3_SECRET_KEY.strip()
    server_side_encryption = (
        configured_settings.S3_SERVER_SIDE_ENCRYPTION.strip()
    )
    sse_kms_key_id = configured_settings.S3_SSE_KMS_KEY_ID.strip() or None
    parsed_endpoint = urlparse(endpoint)
    if (
        parsed_endpoint.scheme not in {"http", "https"}
        or not parsed_endpoint.netloc
        or parsed_endpoint.username is not None
        or parsed_endpoint.password is not None
        or parsed_endpoint.query
        or parsed_endpoint.fragment
        or not _BUCKET_PATTERN.fullmatch(bucket)
        or not region
        or not access_key
        or not secret_key
        or server_side_encryption not in {"AES256", "aws:kms"}
        or (server_side_encryption == "aws:kms" and sse_kms_key_id is None)
        or (server_side_encryption == "AES256" and sse_kms_key_id is not None)
        or (
            sse_kms_key_id is not None
            and (
                len(sse_kms_key_id) > 2048
                or any(character in sse_kms_key_id for character in "\0\r\n")
            )
        )
    ):
        raise ObjectStorageConfigurationError("S3 object storage is not configured")
    if environment not in DEVELOPMENT_ENVIRONMENTS and (
        parsed_endpoint.scheme != "https"
        or endpoint.rstrip("/").lower() in _PLACEHOLDER_ENDPOINTS
        or access_key.lower() in _PLACEHOLDER_CREDENTIALS
        or secret_key.lower() in _PLACEHOLDER_CREDENTIALS
        or len(access_key) < 8
        or len(secret_key) < 16
    ):
        raise ObjectStorageConfigurationError(
            "Production S3 object storage configuration is insecure"
        )
    return


def configured_private_object_store(
    configured_settings: Settings = settings,
) -> PrivateObjectStore:
    """Construct a fresh store; never cache clients or fall back after errors."""

    validate_private_object_storage_configuration(configured_settings)
    if configured_settings.DIETARY_IMAGE_STORAGE_BACKEND.strip().lower() == "local":
        return LocalPrivateObjectStore(configured_settings.LOCAL_STORAGE_DIR.strip())
    endpoint = configured_settings.S3_ENDPOINT_URL.strip()
    bucket = configured_settings.S3_BUCKET.strip()
    region = configured_settings.S3_REGION.strip()
    access_key = configured_settings.S3_ACCESS_KEY.strip()
    secret_key = configured_settings.S3_SECRET_KEY.strip()
    server_side_encryption = configured_settings.S3_SERVER_SIDE_ENCRYPTION.strip()
    sse_kms_key_id = configured_settings.S3_SSE_KMS_KEY_ID.strip() or None
    try:
        client = boto3.client(
            "s3",
            endpoint_url=endpoint,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                connect_timeout=3,
                read_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
                s3={"addressing_style": "path"},
            ),
        )
    except (BotoCoreError, ValueError) as exc:
        raise ObjectStorageConfigurationError(
            "S3 object storage is not configured"
        ) from exc
    return S3PrivateObjectStore(
        client=client,
        bucket=bucket,
        server_side_encryption=server_side_encryption,
        sse_kms_key_id=sse_kms_key_id,
    )
