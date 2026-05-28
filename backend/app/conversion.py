import asyncio
import csv
import html
import json
import os
import re
import shutil
import subprocess
import zipfile
from pathlib import Path

from .config import settings
from .models import ConversionOptions, FileRecord
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
    async def convert(
        self,
        record: FileRecord,
        input_path: Path,
        output_path: Path | None = None,
        options: ConversionOptions | None = None,
    ) -> ConversionResult:
        options = options or ConversionOptions()
        ext = record.extension.lower()
        if ext in IMAGE_EXTENSIONS:
            if not output_path:
                raise ValueError("Image conversion requires an output path.")
            return self._image_to_markdown(record, input_path, output_path, options)
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

        if ext in {".pdf", ".pptx"}:
            return ConversionResult(
                "_No textual content was extracted by the configured text converters._",
                "asset-extraction",
                partial=True,
                warning="Text extraction was unavailable; embedded images were preserved when possible.",
            )

        if options.enable_pandoc_fallback and ext in {".docx", ".html", ".htm"}:
            result = await self._pandoc(input_path)
            if result:
                return result

        raise ValueError("No enabled converter could convert this file type.")

    def output_path(self, batch_dir: Path, record: FileRecord) -> Path:
        return batch_dir / "outputs" / output_relative_path(record.relative_path)

    def asset_dir(self, output_path: Path) -> Path:
        return output_path.with_name(f"{output_path.stem}_assets")

    def extract_embedded_assets(
        self,
        record: FileRecord,
        input_path: Path,
        output_path: Path,
        options: ConversionOptions | None = None,
    ) -> tuple[str, str | None]:
        options = options or ConversionOptions()
        if record.extension == ".pptx":
            return self._extract_pptx_assets(input_path, output_path, options)
        if record.extension == ".pdf":
            return self._extract_pdf_assets(input_path, output_path, options)
        return "", None

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

    def _extract_pptx_assets(
        self,
        input_path: Path,
        output_path: Path,
        options: ConversionOptions,
    ) -> tuple[str, str | None]:
        asset_dir = self.asset_dir(output_path)
        links: list[str] = []
        ocr_warnings: set[str] = set()
        try:
            with zipfile.ZipFile(input_path) as archive:
                media_files = [
                    info
                    for info in archive.infolist()
                    if not info.is_dir() and info.filename.startswith("ppt/media/")
                ]
                for index, info in enumerate(media_files, start=1):
                    source_name = Path(info.filename).name
                    extension = Path(source_name).suffix.lower() or ".bin"
                    if extension not in IMAGE_EXTENSIONS:
                        continue
                    asset_dir.mkdir(parents=True, exist_ok=True)
                    target = asset_dir / f"ppt-image-{index:03d}{extension}"
                    with archive.open(info) as source, target.open("wb") as dest:
                        shutil.copyfileobj(source, dest)
                    links.append(self._asset_markdown(output_path, target, f"PPT image {index}", ocr_warnings, options))
        except zipfile.BadZipFile:
            return "", "Embedded images could not be extracted because the PPTX archive is invalid."
        except Exception:
            return "", "Embedded images could not be extracted from this PPTX."

        if not links:
            return "", None
        return "\n\n## Extracted Images\n\n" + "\n\n".join(links), self._join_warnings(ocr_warnings)

    def _extract_pdf_assets(
        self,
        input_path: Path,
        output_path: Path,
        options: ConversionOptions,
    ) -> tuple[str, str | None]:
        try:
            import fitz
        except Exception:
            return "", "PDF image extraction requires PyMuPDF, but it is not available."

        asset_dir = self.asset_dir(output_path)
        links: list[str] = []
        ocr_warnings: set[str] = set()
        seen_xrefs: set[int] = set()
        try:
            document = fitz.open(input_path)
            for page_index in range(document.page_count):
                page = document.load_page(page_index)
                for image_index, image in enumerate(page.get_images(full=True), start=1):
                    xref = image[0]
                    if xref in seen_xrefs:
                        continue
                    seen_xrefs.add(xref)
                    extracted = document.extract_image(xref)
                    image_bytes = extracted.get("image")
                    extension = f".{extracted.get('ext', 'png').lower()}"
                    if not image_bytes:
                        continue
                    asset_dir.mkdir(parents=True, exist_ok=True)
                    target = asset_dir / f"page-{page_index + 1:03d}-image-{image_index:03d}{extension}"
                    target.write_bytes(image_bytes)
                    links.append(
                        self._asset_markdown(
                            output_path,
                            target,
                            f"PDF page {page_index + 1} image {image_index}",
                            ocr_warnings,
                            options,
                        )
                    )
        except Exception:
            return "", "Embedded images could not be extracted from this PDF."

        if not links:
            return "", None
        return "\n\n## Extracted Images\n\n" + "\n\n".join(links), self._join_warnings(ocr_warnings)

    def _markdown_image_link(self, output_path: Path, asset_path: Path, alt: str) -> str:
        relative = os.path.relpath(asset_path, output_path.parent).replace("\\", "/")
        return f"![{alt}]({relative})"

    def _image_to_markdown(
        self,
        record: FileRecord,
        input_path: Path,
        output_path: Path,
        options: ConversionOptions,
    ) -> ConversionResult:
        if not options.enable_ocr:
            raise ValueError("Image conversion requires OCR, but OCR is currently disabled.")

        asset_dir = self.asset_dir(output_path)
        asset_dir.mkdir(parents=True, exist_ok=True)
        target = asset_dir / record.safe_name
        shutil.copyfile(input_path, target)
        link = self._markdown_image_link(output_path, target, record.original_name)
        text = self._ocr_image(target, options)
        markdown = f"{link}\n\n**OCR Text**\n\n{text}"
        return ConversionResult(markdown, "tesseract-ocr")

    def _asset_markdown(
        self,
        output_path: Path,
        asset_path: Path,
        alt: str,
        warnings: set[str],
        options: ConversionOptions,
    ) -> str:
        link = self._markdown_image_link(output_path, asset_path, alt)
        if not options.enable_ocr:
            return link

        try:
            text = self._ocr_image(asset_path, options)
        except ValueError as exc:
            warning = str(exc)
            already_seen = warning in warnings
            warnings.add(warning)
            if already_seen:
                return link
            return f"{link}\n\n> OCR warning: {warning}"

        if not text:
            return f"{link}\n\n_OCR did not detect readable text in this image._"

        return f"{link}\n\n**OCR Text**\n\n{text}"

    def _ocr_image(self, path: Path, options: ConversionOptions) -> str:
        try:
            from PIL import Image
            import pytesseract
            from pytesseract import TesseractNotFoundError
        except Exception as exc:
            raise ValueError("OCR dependencies are not installed. Install Pillow and pytesseract.") from exc

        if settings.tesseract_cmd:
            pytesseract.pytesseract.tesseract_cmd = settings.tesseract_cmd

        config = ""
        if settings.tesseract_tessdata_dir:
            config = f"--tessdata-dir {settings.tesseract_tessdata_dir}"

        try:
            with Image.open(path) as image:
                text = pytesseract.image_to_string(image, lang=options.ocr_languages, config=config)
        except TesseractNotFoundError as exc:
            raise ValueError("Tesseract OCR is not installed or TESSERACT_CMD is not configured.") from exc
        except Exception as exc:
            raise ValueError("OCR failed for this image.") from exc

        return self._normalize_markdown(text)

    def _join_warnings(self, warnings: set[str]) -> str | None:
        if not warnings:
            return None
        return " ".join(sorted(warnings))


conversion_service = ConversionService()
