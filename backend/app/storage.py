import json
import shutil
import zipfile
from pathlib import Path

import aiofiles
from fastapi import HTTPException, UploadFile

from .config import settings
from .manifest import manifest_store
from .models import BatchManifest, FileRecord
from .utils import (
    DANGEROUS_EXTENSIONS,
    SUPPORTED_EXTENSIONS,
    ensure_within,
    new_id,
    relative_storage_path,
    sanitize_relative_path,
    sanitize_segment,
    utc_now,
)


class StorageService:
    def __init__(self, root: Path) -> None:
        self.root = root

    def batch_dir(self, batch_id: str) -> Path:
        if not batch_id.startswith("batch_"):
            raise HTTPException(status_code=404, detail="Batch not found.")
        return ensure_within(self.root, self.root / batch_id)

    def create_batch(self) -> BatchManifest:
        batch_id = new_id("batch")
        batch_dir = self.batch_dir(batch_id)
        for name in ["uploads", "outputs", "logs", "downloads", "chunks"]:
            (batch_dir / name).mkdir(parents=True, exist_ok=True)
        now = utc_now()
        manifest = BatchManifest(batch_id=batch_id, created_at=now, updated_at=now)
        return manifest_store.create(batch_dir, manifest)

    def get_manifest(self, batch_id: str) -> BatchManifest:
        batch_dir = self.batch_dir(batch_id)
        if not (batch_dir / "manifest.json").exists():
            raise HTTPException(status_code=404, detail="Batch not found.")
        return manifest_store.read(batch_dir)

    async def save_uploads(
        self,
        batch_id: str,
        files: list[UploadFile],
        relative_paths: list[str] | None = None,
    ) -> BatchManifest:
        batch_dir = self.batch_dir(batch_id)
        if not (batch_dir / "manifest.json").exists():
            raise HTTPException(status_code=404, detail="Batch not found.")

        new_records: list[FileRecord] = []
        existing_size = self._batch_upload_size(batch_dir)
        rels = relative_paths or []

        for index, upload in enumerate(files):
            original_name = upload.filename or "uploaded-file"
            client_relative = rels[index] if index < len(rels) and rels[index] else original_name
            relative_path = sanitize_relative_path(client_relative, original_name)
            safe_name = sanitize_segment(Path(relative_path).name)
            extension = Path(safe_name).suffix.lower()
            target = ensure_within(batch_dir / "uploads", batch_dir / "uploads" / relative_path)
            target.parent.mkdir(parents=True, exist_ok=True)

            size = await self._copy_upload(upload, target, settings.max_file_size_bytes)
            existing_size += size
            if existing_size > settings.max_batch_size_bytes:
                target.unlink(missing_ok=True)
                raise HTTPException(status_code=413, detail="Batch size limit exceeded.")

            now = utc_now()
            record = FileRecord(
                file_id=new_id("file"),
                original_name=original_name,
                safe_name=safe_name,
                relative_path=relative_path,
                size_bytes=size,
                mime_type=upload.content_type,
                extension=extension,
                status="uploaded",
                upload_path=relative_storage_path(batch_dir, target),
                created_at=now,
                updated_at=now,
            )
            new_records.append(record)

            if extension == ".zip" and settings.enable_zip_extraction:
                new_records.extend(self.extract_zip(batch_dir, target, record))

        def add_records(manifest: BatchManifest) -> None:
            manifest.status = "uploaded"
            manifest.files.extend(new_records)

        return manifest_store.update(batch_dir, add_records)

    async def save_chunk(
        self,
        batch_id: str,
        upload_id: str,
        file_name: str,
        relative_path: str | None,
        chunk_index: int,
        total_chunks: int,
        file_size: int,
        chunk: UploadFile,
    ) -> BatchManifest:
        batch_dir = self.batch_dir(batch_id)
        safe_upload_id = sanitize_segment(upload_id)
        chunk_dir = ensure_within(batch_dir / "chunks", batch_dir / "chunks" / safe_upload_id)
        chunk_dir.mkdir(parents=True, exist_ok=True)
        chunk_path = ensure_within(chunk_dir, chunk_dir / f"{chunk_index:08d}.part")
        await self._copy_upload(chunk, chunk_path, settings.max_file_size_bytes)

        parts = list(chunk_dir.glob("*.part"))
        if len(parts) < total_chunks:
            return self.get_manifest(batch_id)

        final_relative = sanitize_relative_path(relative_path or file_name, file_name)
        final_path = ensure_within(batch_dir / "uploads", batch_dir / "uploads" / final_relative)
        final_path.parent.mkdir(parents=True, exist_ok=True)
        with final_path.open("wb") as out:
            for index in range(total_chunks):
                part = chunk_dir / f"{index:08d}.part"
                if not part.exists():
                    raise HTTPException(status_code=400, detail="Missing upload chunk.")
                with part.open("rb") as handle:
                    shutil.copyfileobj(handle, out)
        shutil.rmtree(chunk_dir, ignore_errors=True)
        if final_path.stat().st_size != file_size:
            final_path.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="Chunked upload size mismatch.")

        now = utc_now()
        record = FileRecord(
            file_id=new_id("file"),
            original_name=file_name,
            safe_name=sanitize_segment(Path(final_relative).name),
            relative_path=final_relative,
            size_bytes=final_path.stat().st_size,
            mime_type=None,
            extension=final_path.suffix.lower(),
            status="uploaded",
            upload_path=relative_storage_path(batch_dir, final_path),
            created_at=now,
            updated_at=now,
        )

        extracted = []
        if record.extension == ".zip" and settings.enable_zip_extraction:
            extracted = self.extract_zip(batch_dir, final_path, record)

        def add(manifest: BatchManifest) -> None:
            manifest.status = "uploaded"
            manifest.files.append(record)
            manifest.files.extend(extracted)

        return manifest_store.update(batch_dir, add)

    def extract_zip(self, batch_dir: Path, zip_path: Path, container: FileRecord) -> list[FileRecord]:
        records: list[FileRecord] = []
        extract_root = ensure_within(
            batch_dir / "uploads",
            batch_dir / "uploads" / Path(container.relative_path).with_suffix(""),
        )
        try:
            with zipfile.ZipFile(zip_path) as archive:
                for info in archive.infolist():
                    if info.is_dir():
                        continue
                    inner_path = sanitize_relative_path(info.filename, Path(info.filename).name)
                    target = ensure_within(extract_root, extract_root / inner_path)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(info) as source, target.open("wb") as dest:
                        shutil.copyfileobj(source, dest)
                    now = utc_now()
                    relative_path = relative_storage_path(batch_dir / "uploads", target)
                    records.append(
                        FileRecord(
                            file_id=new_id("file"),
                            original_name=Path(info.filename).name,
                            safe_name=sanitize_segment(Path(info.filename).name),
                            relative_path=relative_path,
                            size_bytes=target.stat().st_size,
                            mime_type=None,
                            extension=target.suffix.lower(),
                            status="uploaded",
                            upload_path=relative_storage_path(batch_dir, target),
                            source_container=container.relative_path,
                            created_at=now,
                            updated_at=now,
                        )
                    )
        except zipfile.BadZipFile as exc:
            self.log_error(batch_dir, container.file_id, "Invalid ZIP archive.", repr(exc))
        return records

    def classify_file(self, record: FileRecord) -> tuple[bool, str | None]:
        if record.extension in DANGEROUS_EXTENSIONS:
            return False, "This file type is restricted for safety."
        if record.extension not in SUPPORTED_EXTENSIONS:
            return False, f"Unsupported file type '{record.extension or 'unknown'}'. Try PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, HTML, TXT, MD, ZIP, PNG, JPG, JPEG, or WEBP."
        if record.extension == ".zip":
            return False, "ZIP archive was accepted as a container; extracted files are converted individually."
        return True, None

    def delete_batch(self, batch_id: str) -> None:
        batch_dir = self.batch_dir(batch_id)
        if batch_dir.exists():
            shutil.rmtree(batch_dir)

    def log_error(self, batch_dir: Path, file_id: str, message: str, detail: str | None = None) -> None:
        logs_dir = batch_dir / "logs"
        logs_dir.mkdir(parents=True, exist_ok=True)
        path = logs_dir / "errors.json"
        entries = []
        if path.exists():
            try:
                entries = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                entries = []
        entries.append({"file_id": file_id, "message": message, "detail": detail, "created_at": utc_now()})
        path.write_text(json.dumps(entries, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    async def _copy_upload(self, upload: UploadFile, target: Path, max_size: int) -> int:
        size = 0
        async with aiofiles.open(target, "wb") as out:
            while True:
                chunk = await upload.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > max_size:
                    await out.close()
                    target.unlink(missing_ok=True)
                    raise HTTPException(status_code=413, detail="File size limit exceeded.")
                await out.write(chunk)
        return size

    def _batch_upload_size(self, batch_dir: Path) -> int:
        upload_dir = batch_dir / "uploads"
        if not upload_dir.exists():
            return 0
        return sum(path.stat().st_size for path in upload_dir.rglob("*") if path.is_file())


storage_service = StorageService(settings.upload_dir)

