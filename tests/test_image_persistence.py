from __future__ import annotations

import base64
import hashlib
import os
import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from app.api.server import create_app
from app.auth.dependencies import get_current_user
from app.config.settings import settings
from app.storage.service import ImageAssetService, ImageFetcher, ImagePayload, ImageAssetRepository, LocalStorage, StorageService


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=")


class FakeFetcher:
    def __init__(self, payload: bytes = PNG):
        self.payload = payload

    def fetch(self, _source: str) -> ImagePayload:
        return ImagePayload(self.payload, "image/png", 1, 1, hashlib.sha256(self.payload).hexdigest())


class MemoryS3:
    storage_name = "s3"

    def __init__(self):
        self.objects = {}
        self.put_count = 0

    def put(self, key, data, mime_type):
        from app.storage.service import StoredObject
        self.put_count += 1
        self.objects[key] = (data, mime_type)
        return StoredObject(key, len(data), mime_type)

    def get(self, key):
        return self.objects[key][0]

    def delete(self, key):
        self.objects.pop(key, None)

    def presign(self, key, _expires):
        return f"https://storage.test/{key}"


class FailingStorage:
    def __init__(self):
        self.storage_name = "s3"
        self.calls = 0

    def put(self, *_args):
        self.calls += 1
        raise OSError("storage offline")

    def get(self, _key):
        raise AssertionError("not reached")

    def delete(self, _key):
        pass

    def presign(self, _key, _expires):
        return None


class ImagePersistenceTests(unittest.TestCase):
    def test_local_persistence_restart_deduplication_and_workspace_isolation(self):
        with tempfile.TemporaryDirectory() as directory:
            storage = StorageService(LocalStorage(Path(directory) / "objects"))
            repository = ImageAssetRepository(Path(directory) / "assets.db")
            service = ImageAssetService(storage, repository, FakeFetcher())
            first = service.persist(["https://provider.test/result"], workspace_id=1, user_id=1, request_id="req-a")[0]
            repeated = service.persist(["https://provider.test/result"], workspace_id=1, user_id=1, request_id="req-a")[0]
            second = service.persist(["https://provider.test/result"], workspace_id=1, user_id=1, request_id="req-b")[0]
            self.assertEqual(first["id"], repeated["id"])
            self.assertEqual(first["object_key"], second["object_key"])
            self.assertEqual(len(list((Path(directory) / "objects").rglob("*.png"))), 1)
            self.assertIsNone(service.get(first["id"], 2))
            restarted = ImageAssetService(storage, repository, FakeFetcher())
            self.assertEqual(restarted.content(restarted.get(first["id"], 1)), PNG)
            restarted.delete(first["id"], 1)
            self.assertEqual(len(list((Path(directory) / "objects").rglob("*.png"))), 1)
            restarted.delete(second["id"], 1)
            self.assertEqual(list((Path(directory) / "objects").rglob("*.png")), [])

    def test_s3_compatible_backend_and_retry_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ImageAssetRepository(Path(directory) / "assets.db")
            backend = MemoryS3()
            service = ImageAssetService(StorageService(backend), repository, FakeFetcher())
            asset = service.persist(["provider-result"], workspace_id=1, user_id=1, request_id="req-s3")[0]
            self.assertEqual(asset["storage_backend"], "s3")
            self.assertEqual(service.storage.presign(asset["object_key"]), f"https://storage.test/{asset['object_key']}")
            self.assertEqual(backend.put_count, 1)

            failing = FailingStorage()
            old_retries = settings.image_upload_retries
            settings.image_upload_retries = 2
            try:
                with self.assertRaisesRegex(RuntimeError, "upload failed"):
                    ImageAssetService(StorageService(failing), ImageAssetRepository(Path(directory) / "failed.db"), FakeFetcher()).persist(["provider-result"], workspace_id=1, user_id=1, request_id="req-fail")
            finally:
                settings.image_upload_retries = old_retries
            self.assertEqual(failing.calls, 3)

    def test_fetcher_rejects_ssrf_and_accepts_valid_image_data(self):
        fetcher = ImageFetcher(allowed_hosts={"aliyuncs.com"})
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            fetcher.fetch("http://127.0.0.1/image.png")
        encoded = base64.b64encode(PNG).decode()
        payload = fetcher.fetch(f"data:image/png;base64,{encoded}")
        self.assertEqual(payload.mime_type, "image/png")
        self.assertEqual(payload.width, 1)
        self.assertEqual(payload.height, 1)

    def test_authenticated_image_endpoint_is_workspace_scoped(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = ImageAssetRepository(Path(directory) / "assets.db")
            service = ImageAssetService(StorageService(LocalStorage(Path(directory) / "objects")), repository, FakeFetcher())
            asset = service.persist(["provider-result"], workspace_id=1, user_id=1, request_id="req-api")[0]
            import app.api.images as image_api
            original = image_api.get_image_asset_service
            image_api.get_image_asset_service = lambda: service
            app = create_app()
            current_user = {"id": 1, "workspace": {"id": 1}}
            app.dependency_overrides[get_current_user] = lambda: current_user
            try:
                with TestClient(app) as client:
                    response = client.get(f"/api/images/{asset['id']}")
                    current_user["id"] = 2
                    current_user["workspace"] = {"id": 2}
                    denied = client.get(f"/api/images/{asset['id']}")
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.content, PNG)
                self.assertEqual(denied.status_code, 404)
            finally:
                image_api.get_image_asset_service = original
                app.dependency_overrides.clear()

    @unittest.skipUnless(os.getenv("STAGE4_TEST_DATABASE_URL"), "isolated PostgreSQL is not configured")
    def test_postgres_metadata_roundtrip(self):
        from app.config.settings import settings
        from app.db.postgres import direct_connection

        settings.database_url = os.environ["STAGE4_TEST_DATABASE_URL"]
        with direct_connection(settings.database_url) as conn:
            request_id = conn.execute("SELECT request_id FROM gateway_history ORDER BY id LIMIT 1").fetchone()["request_id"]
        repository = ImageAssetRepository()
        backend = MemoryS3()
        service = ImageAssetService(StorageService(backend), repository, FakeFetcher())
        asset = service.persist(["provider-result"], workspace_id=1, user_id=1, request_id=request_id)[0]
        try:
            self.assertEqual(service.get(asset["id"], 1)["id"], asset["id"])
            self.assertIsNone(service.get(asset["id"], 2))
        finally:
            service.delete(asset["id"], 1)


if __name__ == "__main__":
    unittest.main()
