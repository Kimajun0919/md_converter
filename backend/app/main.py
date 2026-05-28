from contextlib import asynccontextmanager
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

import asyncio
from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from .cleanup import cleanup_loop, cleanup_once
from .config import settings
from .manifest import manifest_store
from .models import BatchManifest
from .storage import storage_service
from .utils import ensure_within, relative_storage_path
from .worker import worker_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings.upload_dir.mkdir(parents=True, exist_ok=True)
    cleanup_once()
    task = asyncio.create_task(cleanup_loop())
    yield
    task.cancel()


app = FastAPI(title="Bulk Markdown Converter API", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/api/batches", response_model=BatchManifest)
async def create_batch() -> BatchManifest:
    return storage_service.create_batch()


@app.post("/api/batches/{batch_id}/files", response_model=BatchManifest)
async def upload_files(
    batch_id: str,
    files: list[UploadFile] = File(...),
    relative_paths: list[str] | None = Form(default=None),
) -> BatchManifest:
    return await storage_service.save_uploads(batch_id, files, relative_paths)


@app.post("/api/batches/{batch_id}/files/chunks", response_model=BatchManifest)
async def upload_chunk(
    batch_id: str,
    upload_id: str = Form(...),
    file_name: str = Form(...),
    relative_path: str | None = Form(default=None),
    chunk_index: int = Form(...),
    total_chunks: int = Form(...),
    chunk_size: int = Form(...),
    file_size: int = Form(...),
    checksum: str | None = Form(default=None),
    chunk: UploadFile = File(...),
) -> BatchManifest:
    if chunk_index < 0 or total_chunks < 1 or chunk_size < 1 or file_size < 0:
        raise HTTPException(status_code=400, detail="Invalid chunk metadata.")
    return await storage_service.save_chunk(
        batch_id,
        upload_id,
        file_name,
        relative_path,
        chunk_index,
        total_chunks,
        file_size,
        chunk,
    )


@app.post("/api/batches/{batch_id}/convert", response_model=BatchManifest)
async def start_conversion(batch_id: str, background_tasks: BackgroundTasks) -> BatchManifest:
    manifest = storage_service.get_manifest(batch_id)
    worker_manager.start(batch_id, failed_only=False)
    return manifest


@app.get("/api/batches/{batch_id}/status", response_model=BatchManifest)
async def get_status(batch_id: str) -> BatchManifest:
    return storage_service.get_manifest(batch_id)


@app.get("/api/batches/{batch_id}/files/{file_id}/download")
async def download_file(batch_id: str, file_id: str) -> FileResponse:
    batch_dir = storage_service.batch_dir(batch_id)
    manifest = storage_service.get_manifest(batch_id)
    record = next((file for file in manifest.files if file.file_id == file_id), None)
    if not record or record.status != "completed" or not record.output_path:
        raise HTTPException(status_code=404, detail="Converted Markdown file is not available.")
    path = ensure_within(batch_dir, batch_dir / record.output_path)
    return FileResponse(path, media_type="text/markdown", filename=Path(path).name)


@app.get("/api/batches/{batch_id}/download")
async def download_zip(batch_id: str) -> FileResponse:
    batch_dir = storage_service.batch_dir(batch_id)
    manifest = storage_service.get_manifest(batch_id)
    download_dir = batch_dir / "downloads"
    download_dir.mkdir(parents=True, exist_ok=True)
    zip_path = download_dir / "converted-files.zip"
    with ZipFile(zip_path, "w", ZIP_DEFLATED) as archive:
        for record in manifest.files:
            if record.status != "completed" or not record.output_path:
                continue
            output = ensure_within(batch_dir, batch_dir / record.output_path)
            archive.write(output, arcname=relative_storage_path(batch_dir / "outputs", output))
    return FileResponse(zip_path, media_type="application/zip", filename="converted-files.zip")


@app.post("/api/batches/{batch_id}/retry-failed", response_model=BatchManifest)
async def retry_failed(batch_id: str) -> BatchManifest:
    manifest = storage_service.get_manifest(batch_id)
    worker_manager.start(batch_id, failed_only=True)
    return manifest


@app.post("/api/batches/{batch_id}/cancel", response_model=BatchManifest)
async def cancel_batch(batch_id: str) -> BatchManifest:
    return worker_manager.request_cancel(batch_id)


@app.delete("/api/batches/{batch_id}")
async def delete_batch(batch_id: str) -> dict[str, str]:
    storage_service.delete_batch(batch_id)
    return {"status": "deleted"}

