import json
import threading
from collections.abc import Callable
from pathlib import Path

from .models import BatchManifest
from .utils import utc_now


class ManifestStore:
    def __init__(self) -> None:
        self._locks: dict[str, threading.RLock] = {}
        self._guard = threading.RLock()

    def _lock_for(self, batch_id: str) -> threading.RLock:
        with self._guard:
            if batch_id not in self._locks:
                self._locks[batch_id] = threading.RLock()
            return self._locks[batch_id]

    def manifest_path(self, batch_dir: Path) -> Path:
        return batch_dir / "manifest.json"

    def create(self, batch_dir: Path, manifest: BatchManifest) -> BatchManifest:
        batch_dir.mkdir(parents=True, exist_ok=True)
        self.write(batch_dir, manifest)
        return manifest

    def read(self, batch_dir: Path) -> BatchManifest:
        with self.manifest_path(batch_dir).open("r", encoding="utf-8") as handle:
            return BatchManifest.model_validate(json.load(handle))

    def write(self, batch_dir: Path, manifest: BatchManifest) -> None:
        manifest.updated_at = utc_now()
        self._recount(manifest)
        path = self.manifest_path(batch_dir)
        tmp = path.with_suffix(".json.tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            json.dump(manifest.model_dump(), handle, indent=2, ensure_ascii=False)
            handle.write("\n")
        tmp.replace(path)

    def update(self, batch_dir: Path, fn: Callable[[BatchManifest], None]) -> BatchManifest:
        batch_id = batch_dir.name
        with self._lock_for(batch_id):
            manifest = self.read(batch_dir)
            fn(manifest)
            self.write(batch_dir, manifest)
            return manifest

    def _recount(self, manifest: BatchManifest) -> None:
        manifest.total_files = len(manifest.files)
        manifest.completed_files = sum(1 for file in manifest.files if file.status == "completed")
        manifest.failed_files = sum(1 for file in manifest.files if file.status == "failed")
        manifest.skipped_files = sum(1 for file in manifest.files if file.status == "skipped")
        manifest.cancelled_files = sum(1 for file in manifest.files if file.status == "cancelled")


manifest_store = ManifestStore()

