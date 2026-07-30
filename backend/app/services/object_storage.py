"""Fail-closed object storage for retryable private source objects.

Production dietary images must survive API/worker container replacement, so
the default backend is the repository's existing S3-compatible configuration.
The local implementation exists only for explicitly identified development or
test processes and is never an automatic runtime fallback for S3 failures.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping, Protocol
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

    def identity(self) -> "StoredObjectIdentity":
        return StoredObjectIdentity(
            key=self.key,
            sha256=self.sha256,
            content_type=self.content_type,
            owner_user_id=self.owner_user_id,
            subject_user_id=self.subject_user_id,
        )


@dataclass(frozen=True)
class StoredObjectIdentity:
    """读取对象所需的稳定身份；大小由受信 provider 元数据发现并做上限校验。"""

    key: str
    sha256: str
    content_type: str
    owner_user_id: int
    subject_user_id: int

    def provider_metadata(self) -> dict[str, str]:
        return {
            "sha256": self.sha256,
            "content-type": self.content_type,
            "owner-user-id": str(self.owner_user_id),
            "subject-user-id": str(self.subject_user_id),
        }


class PrivateObjectStore(Protocol):
    backend_name: str

    def put(self, *, content: bytes, metadata: StoredObjectMetadata) -> bool: ...

    def get(self, *, metadata: StoredObjectMetadata, max_bytes: int) -> bytes: ...

    def get_bounded(
        self, *, identity: StoredObjectIdentity, max_bytes: int
    ) -> bytes: ...

    def delete(
        self, *, identity: StoredObjectIdentity, max_bytes: int
    ) -> bool: ...


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


def _validate_identity(identity: StoredObjectIdentity) -> None:
    if (
        not identity.key
        or len(identity.key.encode("utf-8")) > MAX_OBJECT_KEY_LENGTH
        or identity.key.startswith("/")
        or "\\" in identity.key
        or any(part in {"", ".", ".."} for part in identity.key.split("/"))
    ):
        raise ObjectStorageIntegrityError("Object storage key is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", identity.sha256):
        raise ObjectStorageIntegrityError("Object storage digest is invalid")
    if (
        identity.owner_user_id <= 0
        or identity.subject_user_id <= 0
        or not identity.content_type
        or len(identity.content_type) > 128
        or any(character in identity.content_type for character in "\0\r\n")
    ):
        raise ObjectStorageIntegrityError("Object storage identity is invalid")


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

    @staticmethod
    def _metadata_target(target: Path) -> Path:
        return target.parent / f".{target.name}.xjie-metadata.json"

    @staticmethod
    def _encoded_metadata(metadata: StoredObjectMetadata) -> bytes:
        return json.dumps(
            metadata.provider_metadata(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    def _verify_local_identity(
        self,
        *,
        target: Path,
        identity: StoredObjectIdentity,
        expected_size: int | None = None,
    ) -> None:
        sidecar = self._metadata_target(target)
        if not sidecar.is_file() or sidecar.is_symlink():
            raise ObjectStorageIntegrityError("Local object metadata is unavailable")
        try:
            provider_metadata = json.loads(sidecar.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ObjectStorageIntegrityError("Local object metadata is invalid") from exc
        expected = identity.provider_metadata()
        if (
            not isinstance(provider_metadata, dict)
            or any(provider_metadata.get(key) != value for key, value in expected.items())
            or (
                expected_size is not None
                and provider_metadata.get("size-bytes") != str(expected_size)
            )
        ):
            raise ObjectStorageIntegrityError("Local object metadata mismatch")

    def put(self, *, content: bytes, metadata: StoredObjectMetadata) -> bool:
        target = self._target(metadata, max_bytes=metadata.size_bytes)
        _verify_content(content, metadata, max_bytes=metadata.size_bytes)
        self._root.mkdir(parents=True, exist_ok=True)
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            if not target.is_file():
                raise ObjectStorageIntegrityError("Local object collision")
            _verify_content(target.read_bytes(), metadata, max_bytes=metadata.size_bytes)
            metadata_target = self._metadata_target(target)
            if metadata_target.exists():
                self._verify_local_identity(
                    target=target,
                    identity=metadata.identity(),
                    expected_size=metadata.size_bytes,
                )
            else:
                # 升级前的开发/测试对象可能没有 sidecar；精确字节重放可补齐
                # 租户元数据，但绝不接受摘要或大小不一致的现有对象。
                temporary_metadata = (
                    target.parent / f".{target.name}.{uuid.uuid4().hex}.metadata"
                )
                try:
                    with temporary_metadata.open("xb") as handle:
                        handle.write(self._encoded_metadata(metadata))
                        handle.flush()
                    temporary_metadata.replace(metadata_target)
                finally:
                    temporary_metadata.unlink(missing_ok=True)
            return False
        temporary = target.parent / f".{target.name}.{uuid.uuid4().hex}.upload"
        metadata_target = self._metadata_target(target)
        temporary_metadata = (
            target.parent / f".{target.name}.{uuid.uuid4().hex}.metadata"
        )
        try:
            with temporary.open("xb") as handle:
                handle.write(content)
                handle.flush()
            with temporary_metadata.open("xb") as handle:
                handle.write(self._encoded_metadata(metadata))
                handle.flush()
            if metadata_target.exists():
                self._verify_local_identity(
                    target=target,
                    identity=metadata.identity(),
                    expected_size=metadata.size_bytes,
                )
            else:
                temporary_metadata.replace(metadata_target)
            temporary.replace(target)
            return True
        finally:
            temporary.unlink(missing_ok=True)
            temporary_metadata.unlink(missing_ok=True)

    def get(self, *, metadata: StoredObjectMetadata, max_bytes: int) -> bytes:
        target = self._target(metadata, max_bytes=max_bytes)
        if not target.is_file():
            raise ObjectStorageNotFoundError("Object storage object not found")
        self._verify_local_identity(
            target=target,
            identity=metadata.identity(),
            expected_size=metadata.size_bytes,
        )
        content = target.read_bytes()
        _verify_content(content, metadata, max_bytes=max_bytes)
        return content

    def get_bounded(
        self, *, identity: StoredObjectIdentity, max_bytes: int
    ) -> bytes:
        _validate_identity(identity)
        if max_bytes <= 0:
            raise ObjectStorageIntegrityError("Object storage size limit is invalid")
        target = self._target_for_key(identity.key)
        if not target.is_file():
            raise ObjectStorageNotFoundError("Object storage object not found")
        size = target.stat().st_size
        if size <= 0 or size > max_bytes:
            raise ObjectStorageIntegrityError("Object storage size is invalid")
        self._verify_local_identity(
            target=target,
            identity=identity,
            expected_size=size,
        )
        content = target.read_bytes()
        if len(content) != size or hashlib.sha256(content).hexdigest() != identity.sha256:
            raise ObjectStorageIntegrityError("Object storage digest mismatch")
        return content

    def delete(
        self, *, identity: StoredObjectIdentity, max_bytes: int
    ) -> bool:
        """Delete only the exact tenant-bound object; a missing key is idempotent."""

        _validate_identity(identity)
        target = self._target_for_key(identity.key)
        if not target.exists():
            sidecar = self._metadata_target(target)
            if sidecar.exists():
                self._verify_local_identity(
                    target=target,
                    identity=identity,
                )
                sidecar.unlink()
            return False
        if not target.is_file() or target.is_symlink():
            raise ObjectStorageIntegrityError("Local object is not a regular file")
        # Reading before unlinking proves that a stale row cannot delete a
        # different tenant's or different digest's object at the same key.
        self.get_bounded(identity=identity, max_bytes=max_bytes)
        target.unlink()
        self._metadata_target(target).unlink()
        return True

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

    @staticmethod
    def _content_length(head: Mapping) -> int:
        try:
            return int(head.get("ContentLength", -1))
        except (TypeError, ValueError) as exc:
            raise ObjectStorageIntegrityError("Object storage size is invalid") from exc

    def _verify_identity_head(
        self,
        head: Mapping,
        identity: StoredObjectIdentity,
        *,
        max_bytes: int,
    ) -> int:
        _validate_identity(identity)
        provider_metadata = {
            str(key).lower(): str(value)
            for key, value in (head.get("Metadata") or {}).items()
        }
        size = self._content_length(head)
        if size <= 0 or size > max_bytes:
            raise ObjectStorageIntegrityError("Object storage size is invalid")
        if head.get("ContentType") != identity.content_type:
            raise ObjectStorageIntegrityError("Object storage content type mismatch")
        expected = identity.provider_metadata()
        if any(provider_metadata.get(key) != value for key, value in expected.items()):
            raise ObjectStorageIntegrityError("Object storage metadata mismatch")
        if provider_metadata.get("size-bytes") != str(size):
            raise ObjectStorageIntegrityError("Object storage size metadata mismatch")
        if head.get("ServerSideEncryption") != self._server_side_encryption:
            raise ObjectStorageIntegrityError("Object storage encryption mismatch")
        if (
            self._server_side_encryption == "aws:kms"
            and head.get("SSEKMSKeyId") != self._sse_kms_key_id
        ):
            raise ObjectStorageIntegrityError("Object storage KMS key mismatch")
        return size

    def _verify_head(self, head: Mapping, metadata: StoredObjectMetadata) -> None:
        size = self._verify_identity_head(
            head,
            metadata.identity(),
            max_bytes=metadata.size_bytes,
        )
        if size != metadata.size_bytes:
            raise ObjectStorageIntegrityError("Object storage size mismatch")

    def put(self, *, content: bytes, metadata: StoredObjectMetadata) -> bool:
        _validate_metadata(metadata, max_bytes=metadata.size_bytes)
        _verify_content(content, metadata, max_bytes=metadata.size_bytes)
        existing = self._head(metadata.key)
        if existing is not None:
            self._verify_head(existing, metadata)
            if self.get(metadata=metadata, max_bytes=metadata.size_bytes) != content:
                raise ObjectStorageIntegrityError("Object storage collision")
            return False
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
        try:
            written = self._head(metadata.key)
            if written is None:
                raise ObjectStorageUnavailableError(
                    "Object storage write was not durable"
                )
            self._verify_head(written, metadata)
            if self.get(metadata=metadata, max_bytes=metadata.size_bytes) != content:
                raise ObjectStorageIntegrityError(
                    "Object storage write verification failed"
                )
        except ObjectStorageError as exc:
            # The key was absent before this put, so raw cleanup is safe even
            # when malformed provider metadata prevents exact delete.
            try:
                self._client.delete_object(Bucket=self._bucket, Key=metadata.key)
            except (BotoCoreError, ClientError, OSError) as cleanup_exc:
                raise ObjectStorageUnavailableError(
                    "Object storage write cleanup failed"
                ) from cleanup_exc
            raise exc
        return True

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

    def get_bounded(
        self, *, identity: StoredObjectIdentity, max_bytes: int
    ) -> bytes:
        if max_bytes <= 0:
            raise ObjectStorageIntegrityError("Object storage size limit is invalid")
        _validate_identity(identity)
        head = self._head(identity.key)
        if head is None:
            raise ObjectStorageNotFoundError("Object storage object not found")
        size = self._verify_identity_head(head, identity, max_bytes=max_bytes)
        try:
            response = self._client.get_object(Bucket=self._bucket, Key=identity.key)
            body = response["Body"]
            try:
                content = body.read(max_bytes + 1)
            finally:
                close = getattr(body, "close", None)
                if callable(close):
                    close()
        except (BotoCoreError, ClientError, KeyError, OSError) as exc:
            raise ObjectStorageUnavailableError("Object storage is unavailable") from exc
        if (
            len(content) != size
            or len(content) > max_bytes
            or hashlib.sha256(content).hexdigest() != identity.sha256
        ):
            raise ObjectStorageIntegrityError("Object storage digest mismatch")
        return content

    def delete(
        self, *, identity: StoredObjectIdentity, max_bytes: int
    ) -> bool:
        """Delete an exact verified object; absent objects are safe idempotent replays."""

        if max_bytes <= 0:
            raise ObjectStorageIntegrityError("Object storage size limit is invalid")
        _validate_identity(identity)
        head = self._head(identity.key)
        if head is None:
            return False
        # Verify provider metadata, tenant identity, encryption and payload
        # digest before deletion. Never authorize deletion from a bare key.
        self.get_bounded(identity=identity, max_bytes=max_bytes)
        try:
            self._client.delete_object(Bucket=self._bucket, Key=identity.key)
        except ClientError as exc:
            if self._is_not_found(exc):
                return False
            raise ObjectStorageUnavailableError("Object storage is unavailable") from exc
        except (BotoCoreError, OSError) as exc:
            raise ObjectStorageUnavailableError("Object storage is unavailable") from exc
        if self._head(identity.key) is not None:
            raise ObjectStorageUnavailableError("Object storage deletion was not durable")
        return True


class PrivateObjectWriteLifecycle:
    """Couple newly-created private objects to one database commit boundary.

    Callers must write through :meth:`put` and finish through :meth:`commit`.
    Any exception before a successful commit triggers exact, tenant-bound
    compensation. Objects that already existed before the operation are never
    registered as new and therefore can never be removed by compensation.
    """

    def __init__(self, *, db: Any, object_store: PrivateObjectStore) -> None:
        self.db = db
        self.object_store = object_store
        self._new_objects: list[StoredObjectMetadata] = []
        self._committed = False
        self._compensated = False

    @property
    def committed(self) -> bool:
        return self._committed

    def put(self, *, content: bytes, metadata: StoredObjectMetadata) -> bool:
        created = self.object_store.put(content=content, metadata=metadata)
        # Store implementations return True only after proving that this call
        # created and verified a new object. Probe/read failures on an existing
        # object must never register it for compensation.
        if created is True:
            self._new_objects.append(metadata)
        return created is True

    def commit(self) -> None:
        try:
            self.db.commit()
        except Exception:
            self.db.rollback()
            self.compensate()
            raise
        self._committed = True

    def compensate(self) -> None:
        if self._committed or self._compensated:
            return
        self.db.rollback()
        failures: list[Exception] = []
        # Reverse order mirrors creation and minimizes partially-built trees.
        for metadata in reversed(self._new_objects):
            try:
                self.object_store.delete(
                    identity=metadata.identity(),
                    max_bytes=metadata.size_bytes,
                )
            except ObjectStorageError as exc:
                failures.append(exc)
        self._compensated = True
        if failures:
            raise failures[0]

    def __enter__(self) -> "PrivateObjectWriteLifecycle":
        return self

    def __exit__(self, exc_type, _exc, _traceback) -> bool:
        if exc_type is not None and not self._committed:
            self.compensate()
        return False


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
