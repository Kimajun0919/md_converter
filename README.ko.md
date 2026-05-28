# 대량 Markdown 변환기

여러 파일을 업로드해 RAG 및 문서 인덱싱 전처리에 적합한 Markdown으로 변환하는 웹 애플리케이션입니다. 데이터베이스 없이 로컬 파일 시스템과 배치별 `manifest.json`으로 동작합니다.

## 구조

- 프론트엔드: React + TypeScript + Vite
- 백엔드: Python FastAPI
- 저장소: `storage/batches` 아래 로컬 임시 파일
- 상태 관리: 배치별 `manifest.json`
- 워커: FastAPI 프로세스 내부 백그라운드 작업
- 데이터베이스: 사용하지 않음

대용량 파일은 디스크 기반 업로드, 백그라운드 변환, 선택적 청크 업로드, 설정 가능한 제한값, 명확한 오류 처리로 지원합니다. 실제 처리 가능한 크기는 서버 CPU, 메모리, 디스크, 타임아웃, 프록시 제한, 변환기 한계에 따라 달라집니다.

## 지원 형식

PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, HTML, TXT, MD, ZIP, PNG, JPG, JPEG, WEBP를 지원합니다.

이미지 파일의 텍스트 추출은 OCR이 필요합니다. 기본 OCR 언어는 `eng+kor`이며, OCR은 기본적으로 꺼져 있습니다. OCR을 사용하려면 `ENABLE_OCR=true`와 Tesseract 설치 또는 Docker 실행 환경이 필요합니다.

PDF/PPTX 안의 이미지는 가능한 경우 Markdown 옆 `_assets` 폴더로 추출되고, Markdown 본문에는 표준 이미지 링크가 추가됩니다. OCR이 켜져 있으면 추출된 이미지 아래에 OCR 텍스트도 함께 들어갑니다.

## 로컬 실행

환경 파일을 준비합니다.

```bash
cp .env.example .env
```

Docker Compose로 실행합니다.

```bash
docker compose up --build
```

접속 주소:

- 프론트엔드: http://localhost:5173
- 백엔드 API 문서: http://localhost:8000/docs

Docker 이미지는 영어와 한국어 Tesseract 언어팩을 설치합니다.

## Windows에서 OCR 사용

Windows 로컬 실행 시 Tesseract를 설치하고 `.env`에 다음처럼 설정합니다.

```env
ENABLE_OCR=true
OCR_LANGUAGES=eng+kor
TESSERACT_CMD=C:\Program Files\Tesseract-OCR\tesseract.exe
```

영어만 사용할 경우 사용자 페이지의 OCR 언어 설정에서 `eng`를 입력하면 됩니다.

## 사용자 페이지 옵션

웹 UI는 한국어가 기본이며, 우측 상단에서 English로 전환할 수 있습니다.

배치별로 다음 옵션을 설정할 수 있습니다.

- OCR 활성화
- OCR 언어 코드: 기본 `eng+kor`, 영어만 사용 시 `eng`
- ZIP 업로드 추출
- Pandoc 폴백
- Tika 폴백
- LibreOffice 폴백

옵션은 배치의 `manifest.json`에 저장됩니다. ZIP 추출 옵션은 ZIP 업로드 전에 설정해야 합니다.

## API

- `POST /api/batches`
- `PATCH /api/batches/{batch_id}/options`
- `POST /api/batches/{batch_id}/files`
- `POST /api/batches/{batch_id}/files/chunks`
- `POST /api/batches/{batch_id}/convert`
- `GET /api/batches/{batch_id}/status`
- `GET /api/batches/{batch_id}/files/{file_id}/download`
- `GET /api/batches/{batch_id}/download`
- `POST /api/batches/{batch_id}/retry-failed`
- `POST /api/batches/{batch_id}/cancel`
- `DELETE /api/batches/{batch_id}`

## 저장 구조

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

임시 파일은 `TEMP_FILE_TTL_HOURS` 이후 cleanup 작업으로 삭제되며, `DELETE /api/batches/{batch_id}`로 즉시 삭제할 수 있습니다.

## 빠른 점검

1. TXT, MD, CSV, JSON, HTML, 이미지, 미지원 파일, 중첩 파일이 있는 ZIP을 업로드합니다.
2. 변환을 시작합니다.
3. 실패한 파일이 숨겨지지 않고 나머지 파일이 계속 처리되는지 확인합니다.
4. 완료된 Markdown 파일 하나를 다운로드합니다.
5. ZIP 다운로드에 성공한 `.md`와 `_assets` 파일만 포함되는지 확인합니다.
6. `storage/batches/{batch_id}/manifest.json`을 확인합니다.
