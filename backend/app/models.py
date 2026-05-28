from typing import Literal

from pydantic import BaseModel, Field


FileStatus = Literal[
    "waiting",
    "uploading",
    "uploaded",
    "queued",
    "converting",
    "completed",
    "failed",
    "skipped",
    "cancelled",
]

BatchStatus = Literal[
    "created",
    "uploading",
    "uploaded",
    "queued",
    "converting",
    "completed",
    "completed_with_errors",
    "failed",
    "cancelled",
    "deleted",
]


class FileRecord(BaseModel):
    file_id: str
    original_name: str
    safe_name: str
    relative_path: str
    size_bytes: int
    mime_type: str | None = None
    extension: str
    status: FileStatus = "uploaded"
    upload_path: str
    output_path: str | None = None
    source_container: str | None = None
    converter: str | None = None
    error: str | None = None
    upload_progress: int = 100
    conversion_stage: str | None = None
    created_at: str
    updated_at: str


class BatchManifest(BaseModel):
    batch_id: str
    created_at: str
    updated_at: str
    status: BatchStatus = "created"
    total_files: int = 0
    completed_files: int = 0
    failed_files: int = 0
    skipped_files: int = 0
    cancelled_files: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    cancellation_requested: bool = False
    files: list[FileRecord] = Field(default_factory=list)

