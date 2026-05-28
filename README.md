# Bulk Markdown Converter

A no-database web app for uploading many files and converting supported inputs into clean Markdown for RAG and document indexing preprocessing.

## Architecture

- Frontend: React + TypeScript + Vite
- Backend: Python FastAPI
- Storage: local filesystem under `storage/batches`
- Status: per-batch `manifest.json`
- Worker: in-process FastAPI background task manager
- Database: none

The app is designed for large files through disk-backed uploads, background conversion, optional chunk upload, configurable limits, and clear errors. It does not claim literal unlimited file size; real capacity depends on CPU, memory, disk, server timeouts, proxy limits, and converter behavior.

## Supported Formats

PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, HTML, TXT, MD, ZIP, PNG, JPG, JPEG, and WEBP.

Images require OCR. OCR is disabled by default, so image files return a clear failure unless `ENABLE_OCR=true` and an OCR converter is added.

## Local Development

Copy the example environment file:

```bash
cp .env.example .env
```

Run with Docker Compose:

```bash
docker compose up --build
```

Open:

- Frontend: http://localhost:5173
- Backend API docs: http://localhost:8000/docs

To run without Docker:

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

## Runtime Storage

Each batch uses:

```txt
storage/
  batches/
    {batch_id}/
      manifest.json
      uploads/
      outputs/
      logs/
      downloads/
      chunks/
```

Temporary files are deleted by a cleanup task after `TEMP_FILE_TTL_HOURS`, or immediately through `DELETE /api/batches/{batch_id}`.

## API

- `POST /api/batches`
- `POST /api/batches/{batch_id}/files`
- `POST /api/batches/{batch_id}/files/chunks`
- `POST /api/batches/{batch_id}/convert`
- `GET /api/batches/{batch_id}/status`
- `GET /api/batches/{batch_id}/files/{file_id}/download`
- `GET /api/batches/{batch_id}/download`
- `POST /api/batches/{batch_id}/retry-failed`
- `POST /api/batches/{batch_id}/cancel`
- `DELETE /api/batches/{batch_id}`

## Environment Variables

See `.env.example` for all settings:

- `UPLOAD_DIR`
- `MAX_FILE_SIZE_MB`
- `MAX_BATCH_SIZE_MB`
- `FILE_CONVERSION_TIMEOUT_SECONDS`
- `TEMP_FILE_TTL_HOURS`
- `ENABLE_OCR`
- `ENABLE_PANDOC_FALLBACK`
- `ENABLE_TIKA_FALLBACK`
- `ENABLE_LIBREOFFICE_FALLBACK`
- `ENABLE_ZIP_EXTRACTION`
- `CORS_ORIGINS`

## Smoke Test

1. Upload a mix of TXT, MD, CSV, JSON, HTML, image, unsupported file, and a ZIP with nested files.
2. Start conversion.
3. Confirm the UI keeps failed files visible and continues converting remaining files.
4. Download a single completed Markdown file.
5. Download the ZIP and confirm it includes only successful `.md` outputs with folders preserved.
6. Inspect `storage/batches/{batch_id}/manifest.json`.

