import asyncio
import csv
import html
import json
import re
import subprocess
from pathlib import Path

from .config import settings
from .models import FileRecord
from .utils import IMAGE_EXTENSIONS, output_relative_path, utc_now


class ConversionResult:
    def __init__(
        self,
        markdown: str,
        converter: str,
        partial: bool = False,
        warning: str | None = None,
    ) -> None:
        self.markdown = markdown
        self.converter = converter
        self.partial = partial
        self.warning = warning


class ConversionService:
    async def convert(self, record: FileRecord, input_path: Path) -> ConversionResult:
        ext = record.extension.lower()
        if ext in IMAGE_EXTENSIONS and not settings.enable_ocr:
            raise ValueError("Image conversion requires OCR, but OCR is currently disabled.")
        if ext == ".md":
            return ConversionResult(input_path.read_text(encoding="utf-8", errors="replace"), "passthrough")
        if ext == ".txt":
            return ConversionResult(self._text_to_markdown(input_path), "builtin-text")
        if ext == ".csv":
            return ConversionResult(self._csv_to_markdown(input_path), "builtin-csv")
        if ext == ".json":
            return ConversionResult(self._json_to_markdown(input_path), "builtin-json")
        if ext in {".xml", ".html", ".htm"}:
            return ConversionResult(self._markup_to_markdown(input_path, ext), f"builtin-{ext.lstrip('.')}")

        result = await self._markitdown(input_path)
        if result:
            return result

        if settings.enable_pandoc_fallback and ext in {".docx", ".html", ".htm"}:
            result = await self._pandoc(input_path)
            if result:
                return result

        raise ValueError("No enabled converter could convert this file type.")

    def output_path(self, batch_dir: Path, record: FileRecord) -> Path:
        return batch_dir / "outputs" / output_relative_path(record.relative_path)

    def with_frontmatter(self, record: FileRecord, result: ConversionResult) -> str:
        warning = ""
        if result.partial:
            warning = "\n> Warning: This file was converted partially. Some layout, image, table, or OCR content may be missing.\n"
        body = self._normalize_markdown(result.markdown)
        return (
            "---\n"
            f"source_file: {json.dumps(record.original_name)}\n"
            f"source_relative_path: {json.dumps(record.relative_path)}\n"
            f"converted_at: {json.dumps(utc_now())}\n"
            f"converter: {json.dumps(result.converter)}\n"
            'status: "completed"\n'
            "---\n\n"
            f"{warning}\n"
            f"{body}\n"
        )

    def _text_to_markdown(self, path: Path) -> str:
        content = path.read_text(encoding="utf-8", errors="replace")
        return content if content.strip() else "_Empty text file._"

    def _json_to_markdown(self, path: Path) -> str:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return "```json\n" + json.dumps(data, indent=2, ensure_ascii=False) + "\n```"

    def _csv_to_markdown(self, path: Path) -> str:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            rows = list(csv.reader(handle))
        if not rows:
            return "_Empty CSV file._"
        header = rows[0]
        body = rows[1:]
        lines = [
            "| " + " | ".join(self._escape_cell(cell) for cell in header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        for row in body:
            padded = row + [""] * max(0, len(header) - len(row))
            lines.append("| " + " | ".join(self._escape_cell(cell) for cell in padded[: len(header)]) + " |")
        return "\n".join(lines)

    def _markup_to_markdown(self, path: Path, ext: str) -> str:
        raw = path.read_text(encoding="utf-8", errors="replace")
        if ext in {".html", ".htm"}:
            text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", "", raw)
            text = re.sub(r"(?i)<br\s*/?>", "\n", text)
            text = re.sub(r"(?i)</(p|div|h[1-6]|li|tr)>", "\n", text)
            text = re.sub(r"<[^>]+>", "", text)
            return html.unescape(text)
        return "```xml\n" + raw.strip() + "\n```"

    async def _markitdown(self, path: Path) -> ConversionResult | None:
        try:
            from markitdown import MarkItDown
        except Exception:
            return None

        def run() -> str:
            converter = MarkItDown()
            converted = converter.convert(str(path))
            return getattr(converted, "text_content", str(converted))

        try:
            text = await asyncio.wait_for(
                asyncio.to_thread(run),
                timeout=settings.file_conversion_timeout_seconds,
            )
            return ConversionResult(text, "markitdown")
        except Exception:
            return None

    async def _pandoc(self, path: Path) -> ConversionResult | None:
        try:
            proc = await asyncio.wait_for(
                asyncio.to_thread(
                    subprocess.run,
                    ["pandoc", str(path), "-t", "gfm"],
                    capture_output=True,
                    text=True,
                    check=False,
                ),
                timeout=settings.file_conversion_timeout_seconds,
            )
            if proc.returncode == 0 and proc.stdout.strip():
                return ConversionResult(proc.stdout, "pandoc")
        except Exception:
            return None
        return None

    def _escape_cell(self, value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ").strip()

    def _normalize_markdown(self, value: str) -> str:
        value = value.replace("\r\n", "\n").replace("\r", "\n")
        value = re.sub(r"\n{4,}", "\n\n\n", value)
        return value.strip() or "_No textual content was extracted._"


conversion_service = ConversionService()

