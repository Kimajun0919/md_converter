import re
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from fastapi import HTTPException


SUPPORTED_EXTENSIONS = {
    ".pdf",
    ".docx",
    ".pptx",
    ".xlsx",
    ".csv",
    ".json",
    ".xml",
    ".html",
    ".htm",
    ".txt",
    ".md",
    ".zip",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
}

DANGEROUS_EXTENSIONS = {
    ".bat",
    ".cmd",
    ".com",
    ".dll",
    ".exe",
    ".js",
    ".jse",
    ".msi",
    ".ps1",
    ".scr",
    ".sh",
    ".vbs",
    ".wsf",
}

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def sanitize_segment(value: str) -> str:
    value = value.replace("\\", "/").split("/")[-1]
    value = re.sub(r"[\x00-\x1f]", "", value).strip()
    value = re.sub(r"[<>:\"|?*]", "_", value)
    value = value.strip(". ")
    return value or "unnamed"


def sanitize_relative_path(value: str | None, fallback_name: str) -> str:
    raw = (value or fallback_name).replace("\\", "/").strip()
    if not raw:
        raw = fallback_name
    if raw.startswith("/"):
        raise HTTPException(status_code=400, detail="Relative paths cannot be absolute.")
    pure = PurePosixPath(raw)
    safe_parts: list[str] = []
    for part in pure.parts:
        if part in {"", ".", "/"}:
            continue
        if part == "..":
            raise HTTPException(status_code=400, detail="Relative paths cannot contain traversal segments.")
        safe_parts.append(sanitize_segment(part))
    if not safe_parts:
        safe_parts = [sanitize_segment(fallback_name)]
    return "/".join(safe_parts)


def ensure_within(base: Path, candidate: Path) -> Path:
    base_resolved = base.resolve()
    candidate_resolved = candidate.resolve()
    if base_resolved != candidate_resolved and base_resolved not in candidate_resolved.parents:
        raise HTTPException(status_code=400, detail="Path is outside of the batch directory.")
    return candidate_resolved


def relative_storage_path(batch_dir: Path, path: Path) -> str:
    return path.resolve().relative_to(batch_dir.resolve()).as_posix()


def output_relative_path(input_relative_path: str) -> str:
    path = PurePosixPath(input_relative_path)
    return path.with_suffix(".md").as_posix()


def safe_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPException):
        return str(exc.detail)
    if isinstance(exc, ValueError):
        return str(exc)
    return "The file could not be converted. Check the source format or server converter configuration."


def remove_tree(path: Path) -> None:
    if path.exists():
        shutil.rmtree(path)
