from __future__ import annotations

import base64
import binascii
import hashlib
import ipaddress
import os
import socket
import sqlite3
import struct
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

import requests

from app.config.settings import BASE_DIR, settings
from app.db.postgres import get_postgres_connection, postgres_configured


ALLOWED_MIME_TYPES = {"image/png", "image/jpeg", "image/webp", "image/gif"}
EXTENSIONS = {"image/png": "png", "image/jpeg": "jpg", "image/webp": "webp", "image/gif": "gif"}


@dataclass(frozen=True)
class ImagePayload:
    data: bytes
    mime_type: str
    width: int | None
    height: int | None
    sha256: str


@dataclass(frozen=True)
class StoredObject:
    key: str
    size: int
    mime_type: str


class LocalStorage:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def _path(self, key: str) -> Path:
        path = (self.root / key).resolve()
        if self.root.resolve() not in path.parents:
            raise ValueError("Invalid storage object key")
        return path

    def put(self, key: str, data: bytes, mime_type: str) -> StoredObject:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        temporary.write_bytes(data)
        os.replace(temporary, path)
        return StoredObject(key, len(data), mime_type)

    def get(self, key: str) -> bytes:
        return self._path(key).read_bytes()

    def delete(self, key: str) -> None:
        path = self._path(key)
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    def presign(self, key: str, expires: int) -> str | None:
        return None


class S3Storage:
    def __init__(self) -> None:
        if not settings.s3_bucket:
            raise RuntimeError("S3_BUCKET is required when IMAGE_STORAGE_BACKEND=s3")
        try:
            import boto3
        except ImportError as exc:
            raise RuntimeError("boto3 is required for S3-compatible image storage") from exc
        self.bucket = settings.s3_bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url or None,
            region_name=settings.s3_region,
            aws_access_key_id=settings.s3_access_key_id or None,
            aws_secret_access_key=settings.s3_secret_access_key or None,
            aws_session_token=settings.s3_session_token or None,
        )

    def put(self, key: str, data: bytes, mime_type: str) -> StoredObject:
        self.client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType=mime_type,
        )
        return StoredObject(key, len(data), mime_type)

    def get(self, key: str) -> bytes:
        return self.client.get_object(Bucket=self.bucket, Key=key)["Body"].read()

    def delete(self, key: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def presign(self, key: str, expires: int) -> str:
        return self.client.generate_presigned_url(
            "get_object",
            Params={"Bucket": self.bucket, "Key": key},
            ExpiresIn=max(60, min(3600, int(expires))),
        )


class StorageService:
    def __init__(self, backend: Any | None = None, backend_name: str | None = None) -> None:
        self._name = backend_name
        if backend is not None:
            self.backend = backend
            self._name = self._name or getattr(backend, "storage_name", None)
            return
        name = str(settings.image_storage_backend or "local").strip().lower()
        if name in {"s3", "s3-compatible", "s3_compatible"}:
            self.backend = S3Storage()
        elif name == "local":
            root = Path(settings.image_storage_path)
            if not root.is_absolute():
                root = BASE_DIR / root
            self.backend = LocalStorage(root)
        else:
            raise RuntimeError(f"Unsupported image storage backend: {name}")

    @property
    def name(self) -> str:
        return self._name or ("s3" if isinstance(self.backend, S3Storage) else "local")

    def put(self, key: str, data: bytes, mime_type: str) -> StoredObject:
        return self.backend.put(key, data, mime_type)

    def get(self, key: str) -> bytes:
        return self.backend.get(key)

    def delete(self, key: str) -> None:
        self.backend.delete(key)

    def presign(self, key: str) -> str | None:
        return self.backend.presign(key, settings.image_presign_ttl)


def _content_type(value: str | None) -> str:
    value = (value or "").split(";", 1)[0].strip().lower()
    return value if value in ALLOWED_MIME_TYPES else ""


def _jpeg_size(data: bytes) -> tuple[int, int] | tuple[None, None]:
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        return None, None
    index = 2
    while index + 9 < len(data):
        if data[index] != 0xFF:
            index += 1
            continue
        marker = data[index + 1]
        index += 2
        if marker in {0xD8, 0xD9}:
            continue
        if index + 2 > len(data):
            break
        length = struct.unpack(">H", data[index:index + 2])[0]
        if length < 2 or index + length > len(data):
            break
        if marker in set(range(0xC0, 0xC4)) | set(range(0xC5, 0xC8)) | set(range(0xC9, 0xCC)) | set(range(0xCD, 0xD0)):
            if length >= 7:
                return struct.unpack(">H", data[index + 5:index + 7])[0], struct.unpack(">H", data[index + 3:index + 5])[0]
        index += length
    return None, None


def inspect_image(data: bytes, declared_type: str | None = None) -> tuple[str, int | None, int | None]:
    if data.startswith(b"\x89PNG\r\n\x1a\n") and len(data) >= 24:
        return "image/png", *struct.unpack(">II", data[16:24])
    if data[:3] == b"GIF" and len(data) >= 10:
        return "image/gif", *struct.unpack("<HH", data[6:10])
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        if len(data) >= 30 and data[12:16] == b"VP8X":
            width = 1 + int.from_bytes(data[24:27], "little")
            height = 1 + int.from_bytes(data[27:30], "little")
            return "image/webp", width, height
        return "image/webp", None, None
    if data[:2] == b"\xff\xd8":
        width, height = _jpeg_size(data)
        return "image/jpeg", width, height
    mime = _content_type(declared_type)
    if mime:
        raise ValueError("Image content does not match its declared type")
    raise ValueError("Unsupported image type")


class ImageFetcher:
    def __init__(self, max_bytes: int | None = None, timeout: float | None = None, allowed_hosts: set[str] | None = None) -> None:
        self.max_bytes = int(max_bytes or settings.image_max_bytes)
        self.timeout = float(timeout or settings.image_fetch_timeout)
        configured = allowed_hosts or {item.strip().lower() for item in str(settings.image_source_allowlist).split(",") if item.strip()}
        base_host = (urlsplit(settings.qwen_image_base_url).hostname or "").lower()
        if base_host:
            configured.add(base_host)
        self.allowed_hosts = configured

    def _validate_url(self, value: str) -> None:
        parsed = urlsplit(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not host or parsed.username or parsed.password:
            raise ValueError("Image source must be an HTTPS provider URL")
        if not any(host == item or host.endswith("." + item) for item in self.allowed_hosts):
            raise ValueError("Image source host is not allowed")
        try:
            addresses = {info[4][0] for info in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)}
        except OSError as exc:
            raise ValueError("Image source host could not be resolved") from exc
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
                raise ValueError("Image source resolves to a private network")

    def _payload(self, data: bytes, declared_type: str | None = None) -> ImagePayload:
        if not data or len(data) > self.max_bytes:
            raise ValueError(f"Image exceeds the {self.max_bytes} byte limit")
        mime_type, width, height = inspect_image(data, declared_type)
        if mime_type not in ALLOWED_MIME_TYPES:
            raise ValueError("Unsupported image MIME type")
        return ImagePayload(data, mime_type, width, height, hashlib.sha256(data).hexdigest())

    def fetch(self, value: str) -> ImagePayload:
        if value.startswith("data:"):
            header, separator, encoded = value.partition(",")
            if not separator or ";base64" not in header.lower():
                raise ValueError("Only base64 image data URLs are supported")
            declared = _content_type(header[5:].split(";", 1)[0])
            try:
                data = base64.b64decode(unquote(encoded), validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValueError("Invalid image data URL") from exc
            return self._payload(data, declared)
        self._validate_url(value)
        response = None
        try:
            response = requests.get(value, timeout=(5, self.timeout), stream=True, allow_redirects=False)
            if response.status_code >= 300 and response.status_code < 400:
                raise ValueError("Image source redirects are not allowed")
            response.raise_for_status()
            length = int(response.headers.get("Content-Length") or 0)
            if length > self.max_bytes:
                raise ValueError(f"Image exceeds the {self.max_bytes} byte limit")
            chunks: list[bytes] = []
            total = 0
            for chunk in response.iter_content(64 * 1024):
                total += len(chunk)
                if total > self.max_bytes:
                    raise ValueError(f"Image exceeds the {self.max_bytes} byte limit")
                chunks.append(chunk)
            return self._payload(b"".join(chunks), response.headers.get("Content-Type"))
        except requests.RequestException as exc:
            raise RuntimeError("Unable to download generated image") from exc
        finally:
            if response is not None:
                response.close()


class ImageAssetRepository:
    def __init__(self, path: str | Path | None = None) -> None:
        self.use_postgres = path is None and postgres_configured()
        self.path = Path(path) if path else BASE_DIR / "data" / "image_assets.db"
        if not self.use_postgres:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with self._sqlite() as conn:
                conn.execute("""CREATE TABLE IF NOT EXISTS image_assets (
                    id TEXT PRIMARY KEY, workspace_id INTEGER NOT NULL, user_id INTEGER,
                    request_id TEXT, conversation_id TEXT, image_index INTEGER NOT NULL DEFAULT 0,
                    storage_backend TEXT NOT NULL, object_key TEXT NOT NULL, mime_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL, width INTEGER, height INTEGER, content_sha256 TEXT,
                    status TEXT NOT NULL DEFAULT 'ready', error TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                    UNIQUE(workspace_id, request_id, image_index)
                )""")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_image_assets_workspace ON image_assets(workspace_id, created_at DESC)")

    @contextmanager
    def _sqlite(self):
        conn = sqlite3.connect(self.path)
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _row(self, row: Any) -> dict[str, Any] | None:
        return dict(row) if row else None

    def get(self, asset_id: str, workspace_id: int | str) -> dict[str, Any] | None:
        if self.use_postgres:
            with get_postgres_connection() as conn:
                return self._row(conn.execute("SELECT * FROM image_assets WHERE id = %s AND workspace_id = %s AND status = 'ready'", (asset_id, int(workspace_id))).fetchone())
        with self._sqlite() as conn:
            conn.row_factory = sqlite3.Row
            return self._row(conn.execute("SELECT * FROM image_assets WHERE id = ? AND workspace_id = ? AND status = 'ready'", (asset_id, int(workspace_id))).fetchone())

    def by_request(self, request_id: str, workspace_id: int | str) -> list[dict[str, Any]]:
        query = "SELECT * FROM image_assets WHERE request_id = %s AND workspace_id = %s AND status = 'ready' ORDER BY image_index" if self.use_postgres else "SELECT * FROM image_assets WHERE request_id = ? AND workspace_id = ? AND status = 'ready' ORDER BY image_index"
        params = (request_id, int(workspace_id))
        if self.use_postgres:
            with get_postgres_connection() as conn:
                return [dict(row) for row in conn.execute(query, params).fetchall()]
        with self._sqlite() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, params).fetchall()]

    def by_hash(self, content_sha256: str, workspace_id: int | str) -> dict[str, Any] | None:
        query = "SELECT * FROM image_assets WHERE content_sha256 = %s AND workspace_id = %s AND status = 'ready' ORDER BY created_at LIMIT 1" if self.use_postgres else "SELECT * FROM image_assets WHERE content_sha256 = ? AND workspace_id = ? AND status = 'ready' ORDER BY created_at LIMIT 1"
        params = (content_sha256, int(workspace_id))
        if self.use_postgres:
            with get_postgres_connection() as conn:
                return self._row(conn.execute(query, params).fetchone())
        with self._sqlite() as conn:
            conn.row_factory = sqlite3.Row
            return self._row(conn.execute(query, params).fetchone())

    def save(self, asset: dict[str, Any]) -> dict[str, Any]:
        columns = ("id", "workspace_id", "user_id", "request_id", "conversation_id", "image_index", "storage_backend", "object_key", "mime_type", "file_size", "width", "height", "content_sha256", "status", "error", "created_at", "updated_at")
        values = tuple(asset.get(key) for key in columns)
        if self.use_postgres:
            with get_postgres_connection() as conn:
                conn.execute("""INSERT INTO image_assets
                    (id, workspace_id, user_id, request_id, conversation_id, image_index, storage_backend, object_key, mime_type, file_size, width, height, content_sha256, status, error, created_at, updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(workspace_id, request_id, image_index) DO UPDATE SET id=EXCLUDED.id, object_key=EXCLUDED.object_key, mime_type=EXCLUDED.mime_type, file_size=EXCLUDED.file_size, width=EXCLUDED.width, height=EXCLUDED.height, content_sha256=EXCLUDED.content_sha256, status=EXCLUDED.status, error=EXCLUDED.error, updated_at=EXCLUDED.updated_at""", values)
        else:
            with self._sqlite() as conn:
                conn.execute("INSERT OR REPLACE INTO image_assets (" + ",".join(columns) + ") VALUES (" + ",".join("?" for _ in columns) + ")", values)
        return asset

    def usage(self, workspace_id: int | str) -> tuple[int, int]:
        query = "SELECT COUNT(*) AS count, COALESCE(SUM(file_size), 0) AS bytes FROM image_assets WHERE workspace_id = %s AND status = 'ready'" if self.use_postgres else "SELECT COUNT(*) AS count, COALESCE(SUM(file_size), 0) AS bytes FROM image_assets WHERE workspace_id = ? AND status = 'ready'"
        if self.use_postgres:
            with get_postgres_connection() as conn:
                row = conn.execute(query, (int(workspace_id),)).fetchone()
        else:
            with self._sqlite() as conn:
                row = conn.execute(query, (int(workspace_id),)).fetchone()
        return int(row["count"] if self.use_postgres else row[0]), int(row["bytes"] if self.use_postgres else row[1])

    def list_workspace(self, workspace_id: int | str) -> list[dict[str, Any]]:
        query = "SELECT * FROM image_assets WHERE workspace_id = %s AND status = 'ready' ORDER BY created_at" if self.use_postgres else "SELECT * FROM image_assets WHERE workspace_id = ? AND status = 'ready' ORDER BY created_at"
        if self.use_postgres:
            with get_postgres_connection() as conn:
                return [dict(row) for row in conn.execute(query, (int(workspace_id),)).fetchall()]
        with self._sqlite() as conn:
            conn.row_factory = sqlite3.Row
            return [dict(row) for row in conn.execute(query, (int(workspace_id),)).fetchall()]

    def active_object_keys(self) -> set[str]:
        query = "SELECT object_key FROM image_assets WHERE status = 'ready'"
        if self.use_postgres:
            with get_postgres_connection() as conn:
                return {str(row["object_key"]) for row in conn.execute(query).fetchall()}
        with self._sqlite() as conn:
            return {str(row[0]) for row in conn.execute(query).fetchall()}

    def delete(self, asset_id: str, workspace_id: int | str) -> dict[str, Any] | None:
        asset = self.get(asset_id, workspace_id)
        if not asset:
            return None
        query = "UPDATE image_assets SET status = 'deleted', updated_at = %s WHERE id = %s AND workspace_id = %s" if self.use_postgres else "UPDATE image_assets SET status = 'deleted', updated_at = ? WHERE id = ? AND workspace_id = ?"
        params = (datetime.now(timezone.utc).isoformat(), asset_id, int(workspace_id))
        if self.use_postgres:
            with get_postgres_connection() as conn:
                conn.execute(query, params)
        else:
            with self._sqlite() as conn:
                conn.execute(query, params)
        return asset


class ImageAssetService:
    def __init__(self, storage: StorageService | None = None, repository: ImageAssetRepository | None = None, fetcher: ImageFetcher | None = None) -> None:
        self.storage = storage or StorageService()
        self.repository = repository or ImageAssetRepository()
        self.fetcher = fetcher or ImageFetcher()

    @staticmethod
    def _public_url(asset_id: str) -> str:
        return f"/api/images/{asset_id}"

    def persist(self, image_urls: list[str], *, workspace_id: int | str, user_id: int | str | None, request_id: str, conversation_id: str | None = None) -> list[dict[str, Any]]:
        existing = self.repository.by_request(request_id, workspace_id)
        if len(existing) >= len(image_urls):
            return [{**item, "url": self._public_url(item["id"])} for item in existing[:len(image_urls)]]
        count, total_bytes = self.repository.usage(workspace_id)
        assets: list[dict[str, Any]] = []
        for index, source in enumerate(image_urls):
            if index < len(existing):
                assets.append({**existing[index], "url": self._public_url(existing[index]["id"])})
                continue
            payload = self.fetcher.fetch(str(source))
            duplicate = self.repository.by_hash(payload.sha256, workspace_id)
            if duplicate:
                object_key = duplicate["object_key"]
            else:
                if count >= int(settings.image_max_per_workspace):
                    raise RuntimeError("Workspace image limit reached")
                if total_bytes + len(payload.data) > int(settings.image_max_workspace_bytes):
                    raise RuntimeError("Workspace image storage limit reached")
                asset_id = "img_" + uuid.uuid4().hex
                object_key = f"workspaces/{int(workspace_id)}/images/{asset_id}.{EXTENSIONS[payload.mime_type]}"
                self._put_with_retry(object_key, payload.data, payload.mime_type)
                count += 1
                total_bytes += len(payload.data)
            asset = {
                "id": "img_" + uuid.uuid4().hex,
                "workspace_id": int(workspace_id),
                "user_id": int(user_id) if user_id is not None and str(user_id).isdigit() else None,
                "request_id": request_id,
                "conversation_id": conversation_id,
                "image_index": index,
                "storage_backend": self.storage.name,
                "object_key": object_key,
                "mime_type": payload.mime_type,
                "file_size": len(payload.data),
                "width": payload.width,
                "height": payload.height,
                "content_sha256": payload.sha256,
                "status": "ready",
                "error": None,
                "created_at": datetime.now(timezone.utc).isoformat(),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                self.repository.save(asset)
            except Exception:
                if not duplicate:
                    self.storage.delete(object_key)
                raise
            assets.append({**asset, "url": self._public_url(asset["id"])})
        return assets

    def _put_with_retry(self, key: str, data: bytes, mime_type: str) -> StoredObject:
        attempts = max(0, int(settings.image_upload_retries)) + 1
        last_error: Exception | None = None
        for _ in range(attempts):
            try:
                return self.storage.put(key, data, mime_type)
            except Exception as exc:
                last_error = exc
        raise RuntimeError("Image storage upload failed after retries") from last_error

    def get(self, asset_id: str, workspace_id: int | str) -> dict[str, Any] | None:
        asset = self.repository.get(asset_id, workspace_id)
        if not asset:
            return None
        return {**asset, "url": self._public_url(asset["id"]), "download_url": f"/api/images/{asset['id']}/download"}

    def content(self, asset: dict[str, Any]) -> bytes:
        return self.storage.get(asset["object_key"])

    def delete(self, asset_id: str, workspace_id: int | str) -> dict[str, Any] | None:
        asset = self.repository.delete(asset_id, workspace_id)
        if not asset:
            return None
        # A deduplicated object may still be referenced by another request.
        if not self.repository.by_hash(asset.get("content_sha256") or "", workspace_id):
            self.storage.delete(asset["object_key"])
        return asset

    def usage(self, workspace_id: int | str) -> dict[str, int]:
        count, total_bytes = self.repository.usage(workspace_id)
        return {"count": count, "bytes": total_bytes}

    def clear_workspace(self, workspace_id: int | str) -> int:
        assets = self.repository.list_workspace(workspace_id)
        for asset in assets:
            self.delete(asset["id"], workspace_id)
        return len(assets)

    def cleanup_orphans(self) -> int:
        """Delete storage objects no longer referenced by ready metadata."""
        referenced = self.repository.active_object_keys()
        if isinstance(self.storage.backend, LocalStorage):
            removed = 0
            for path in self.storage.backend.root.rglob("*"):
                if path.is_file() and path.relative_to(self.storage.backend.root).as_posix() not in referenced:
                    path.unlink()
                    removed += 1
            return removed
        if isinstance(self.storage.backend, S3Storage):
            removed = 0
            paginator = self.storage.backend.client.get_paginator("list_objects_v2")
            for page in paginator.paginate(Bucket=self.storage.backend.bucket):
                for item in page.get("Contents", []):
                    if item["Key"] not in referenced:
                        self.storage.backend.delete(item["Key"])
                        removed += 1
            return removed
        return 0


_image_asset_service: ImageAssetService | None = None


def get_image_asset_service() -> ImageAssetService:
    global _image_asset_service
    if _image_asset_service is None:
        _image_asset_service = ImageAssetService()
    return _image_asset_service


__all__ = [
    "ALLOWED_MIME_TYPES",
    "ImageAssetRepository",
    "ImageAssetService",
    "ImageFetcher",
    "ImagePayload",
    "LocalStorage",
    "S3Storage",
    "StorageService",
    "get_image_asset_service",
    "inspect_image",
]
