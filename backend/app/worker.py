import asyncio
from pathlib import Path

from .config import settings
from .conversion import conversion_service
from .manifest import manifest_store
from .models import BatchManifest, FileRecord
from .storage import storage_service
from .utils import relative_storage_path, safe_error_message, utc_now


class WorkerManager:
    def __init__(self) -> None:
        self._tasks: dict[str, asyncio.Task] = {}

    def start(self, batch_id: str, failed_only: bool = False) -> None:
        task = self._tasks.get(batch_id)
        if task and not task.done():
            return
        self._tasks[batch_id] = asyncio.create_task(self._process(batch_id, failed_only))

    async def _process(self, batch_id: str, failed_only: bool) -> None:
        batch_dir = storage_service.batch_dir(batch_id)

        def queue(manifest: BatchManifest) -> None:
            manifest.status = "queued"
            manifest.started_at = manifest.started_at or utc_now()
            manifest.completed_at = None
            manifest.cancellation_requested = False
            for file in manifest.files:
                if failed_only and file.status != "failed":
                    continue
                if file.status in {"uploaded", "failed"}:
                    supported, reason = storage_service.classify_file(file)
                    file.status = "queued" if supported else "skipped"
                    file.error = None if supported else reason
                    file.updated_at = utc_now()

        manifest = manifest_store.update(batch_dir, queue)
        for record in list(manifest.files):
            latest = manifest_store.read(batch_dir)
            current = self._find(latest, record.file_id)
            if not current or current.status != "queued":
                continue
            if latest.cancellation_requested:
                self._mark_cancelled(batch_dir, current.file_id)
                continue
            await self._convert_one(batch_dir, current)

        self._finalize(batch_dir)

    async def _convert_one(self, batch_dir: Path, record: FileRecord) -> None:
        def converting(manifest: BatchManifest) -> None:
            manifest.status = "converting"
            file = self._find(manifest, record.file_id)
            if file:
                file.status = "converting"
                file.conversion_stage = "extracting content"
                file.updated_at = utc_now()

        manifest_store.update(batch_dir, converting)
        input_path = batch_dir / record.upload_path
        output_path = conversion_service.output_path(batch_dir, record)

        try:
            result = await asyncio.wait_for(
                conversion_service.convert(record, input_path),
                timeout=settings.file_conversion_timeout_seconds,
            )
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(conversion_service.with_frontmatter(record, result), encoding="utf-8")

            def complete(manifest: BatchManifest) -> None:
                file = self._find(manifest, record.file_id)
                if file:
                    file.status = "completed"
                    file.output_path = relative_storage_path(batch_dir, output_path)
                    file.converter = result.converter
                    file.error = result.warning
                    file.conversion_stage = "completed"
                    file.updated_at = utc_now()

            manifest_store.update(batch_dir, complete)
        except Exception as exc:
            message = safe_error_message(exc)
            storage_service.log_error(batch_dir, record.file_id, message, repr(exc))

            def fail(manifest: BatchManifest) -> None:
                file = self._find(manifest, record.file_id)
                if file:
                    file.status = "failed"
                    file.output_path = None
                    file.converter = None
                    file.error = message
                    file.conversion_stage = "failed"
                    file.updated_at = utc_now()

            manifest_store.update(batch_dir, fail)

    def request_cancel(self, batch_id: str) -> BatchManifest:
        batch_dir = storage_service.batch_dir(batch_id)

        def cancel(manifest: BatchManifest) -> None:
            manifest.cancellation_requested = True
            manifest.status = "cancelled"
            for file in manifest.files:
                if file.status in {"waiting", "uploaded", "queued"}:
                    file.status = "cancelled"
                    file.updated_at = utc_now()

        return manifest_store.update(batch_dir, cancel)

    def _mark_cancelled(self, batch_dir: Path, file_id: str) -> None:
        def cancel(manifest: BatchManifest) -> None:
            file = self._find(manifest, file_id)
            if file:
                file.status = "cancelled"
                file.updated_at = utc_now()

        manifest_store.update(batch_dir, cancel)

    def _finalize(self, batch_dir: Path) -> None:
        def finalize(manifest: BatchManifest) -> None:
            if manifest.cancellation_requested:
                manifest.status = "cancelled"
            elif manifest.failed_files or manifest.skipped_files:
                manifest.status = "completed_with_errors"
            else:
                manifest.status = "completed"
            manifest.completed_at = utc_now()

        manifest_store.update(batch_dir, finalize)

    def _find(self, manifest: BatchManifest, file_id: str) -> FileRecord | None:
        return next((file for file in manifest.files if file.file_id == file_id), None)


worker_manager = WorkerManager()

