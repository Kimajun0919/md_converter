import asyncio
import shutil
from datetime import datetime, timedelta, timezone

from .config import settings


async def cleanup_loop() -> None:
    while True:
        cleanup_once()
        await asyncio.sleep(3600)


def cleanup_once() -> None:
    root = settings.upload_dir
    root.mkdir(parents=True, exist_ok=True)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=settings.temp_file_ttl_hours)
    for batch_dir in root.glob("batch_*"):
        if not batch_dir.is_dir():
            continue
        modified = datetime.fromtimestamp(batch_dir.stat().st_mtime, timezone.utc)
        if modified < cutoff:
            shutil.rmtree(batch_dir, ignore_errors=True)

