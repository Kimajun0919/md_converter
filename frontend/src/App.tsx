import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelBatch,
  createBatch,
  deleteBatch,
  fileDownloadUrl,
  getStatus,
  retryFailed,
  startConversion,
  updateBatchOptions,
  uploadOneFile,
  zipDownloadUrl
} from "./api";
import type { BatchManifest, ConversionOptions, FileRecord, FileStatus, LocalUpload } from "./types";

const terminalStatuses = new Set(["completed", "completed_with_errors", "failed", "cancelled"]);

const defaultOptions: ConversionOptions = {
  enable_ocr: false,
  ocr_languages: "eng+kor",
  enable_pandoc_fallback: false,
  enable_tika_fallback: false,
  enable_libreoffice_fallback: false,
  enable_zip_extraction: true
};

type Language = "ko" | "en";

const copy = {
  ko: {
    title: "대량 Markdown 변환기",
    subtitle: "RAG 및 문서 인덱싱 전처리를 위한 임시 파일-to-Markdown 변환 도구입니다.",
    noBatch: "생성된 배치 없음",
    uploadTitle: "파일 또는 폴더 업로드",
    uploadBody:
      "PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, HTML, TXT, MD, ZIP, PNG, JPG, JPEG, WEBP를 지원합니다. 매우 큰 파일은 서버 CPU, 메모리, 디스크, 타임아웃, 변환기 제한의 영향을 받습니다.",
    uploadNote: "복잡한 레이아웃은 완벽히 변환되지 않을 수 있습니다. 이미지 텍스트 변환은 OCR 옵션이 필요합니다.",
    selectFiles: "파일 선택",
    selectFolder: "폴더 선택",
    settingsTitle: "변환 설정",
    settingsBody: "옵션은 배치별로 저장되며 업로드와 변환 중 백엔드에서 사용됩니다.",
    openSettings: "변환 설정",
    closeSettings: "닫기",
    settingsSaved: "현재 배치에 저장됨",
    settingsPending: "배치 생성 시 적용됨",
    enableOcr: "OCR 활성화",
    enableOcrHelp: "단독 이미지 변환과 PDF/PPTX 내부 이미지 텍스트 추출에 필요합니다.",
    ocrLanguages: "OCR 언어",
    extractZip: "ZIP 업로드 추출",
    extractZipHelp: "ZIP 파일 업로드 시 적용됩니다. ZIP 업로드 전에 설정하세요.",
    pandoc: "Pandoc 폴백",
    pandocHelp: "백엔드에 Pandoc이 설치된 경우에만 사용됩니다.",
    tika: "Tika 폴백",
    tikaHelp: "향후 백엔드 통합을 위해 배치 설정에 저장됩니다.",
    libreoffice: "LibreOffice 폴백",
    libreofficeHelp: "향후 백엔드 통합을 위해 배치 설정에 저장됩니다.",
    start: "변환 시작",
    cancel: "배치 취소",
    retry: "실패 항목 재시도",
    downloadZip: "ZIP 다운로드",
    deleteBatch: "배치 삭제",
    total: "전체",
    completed: "완료",
    failed: "실패",
    skipped: "건너뜀",
    cancelled: "취소됨",
    elapsed: "소요 시간",
    file: "파일",
    relativePath: "상대 경로",
    size: "크기",
    type: "유형",
    status: "상태",
    progress: "진행",
    error: "오류",
    download: "다운로드",
    empty: "아직 업로드된 파일이 없습니다.",
    uploadProgress: "업로드",
    md: ".md",
    refreshError: "상태를 새로고침할 수 없습니다.",
    optionsError: "옵션을 저장할 수 없습니다.",
    uploadError: "업로드 실패",
    actionError: "작업 실패",
    language: "언어"
  },
  en: {
    title: "Bulk Markdown Converter",
    subtitle: "Temporary file-to-Markdown preprocessing for RAG and document indexing pipelines.",
    noBatch: "No batch created",
    uploadTitle: "Upload files or folders",
    uploadBody:
      "Supports PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, HTML, TXT, MD, ZIP, PNG, JPG, JPEG, and WEBP. Very large files depend on server CPU, memory, disk, timeouts, and converter limits.",
    uploadNote: "Complex layouts may not convert perfectly. Image text conversion requires OCR.",
    selectFiles: "Select files",
    selectFolder: "Select folder",
    settingsTitle: "Conversion settings",
    settingsBody: "These options are saved per batch and used by the backend during upload and conversion.",
    openSettings: "Conversion settings",
    closeSettings: "Close",
    settingsSaved: "Saved to current batch",
    settingsPending: "Applied when a batch is created",
    enableOcr: "Enable OCR",
    enableOcrHelp: "Required for standalone image conversion and image text inside PDF/PPTX.",
    ocrLanguages: "OCR languages",
    extractZip: "Extract ZIP uploads",
    extractZipHelp: "Applies when ZIP files are uploaded. Set this before uploading ZIPs.",
    pandoc: "Pandoc fallback",
    pandocHelp: "Used only if Pandoc is installed on the backend.",
    tika: "Tika fallback",
    tikaHelp: "Stored for future backend integration.",
    libreoffice: "LibreOffice fallback",
    libreofficeHelp: "Stored for future backend integration.",
    start: "Start conversion",
    cancel: "Cancel batch",
    retry: "Retry failed",
    downloadZip: "Download ZIP",
    deleteBatch: "Delete batch",
    total: "Total",
    completed: "Completed",
    failed: "Failed",
    skipped: "Skipped",
    cancelled: "Cancelled",
    elapsed: "Elapsed",
    file: "File",
    relativePath: "Relative path",
    size: "Size",
    type: "Type",
    status: "Status",
    progress: "Progress",
    error: "Error",
    download: "Download",
    empty: "No files uploaded yet.",
    uploadProgress: "upload",
    md: ".md",
    refreshError: "Could not refresh status.",
    optionsError: "Options could not be saved.",
    uploadError: "Upload failed",
    actionError: "Action failed",
    language: "Language"
  }
};

const statusCopy: Record<Language, Record<string, string>> = {
  ko: {
    waiting: "대기",
    uploading: "업로드 중",
    uploaded: "업로드됨",
    queued: "대기열",
    converting: "변환 중",
    completed: "완료",
    failed: "실패",
    skipped: "건너뜀",
    cancelled: "취소됨"
  },
  en: {
    waiting: "waiting",
    uploading: "uploading",
    uploaded: "uploaded",
    queued: "queued",
    converting: "converting",
    completed: "completed",
    failed: "failed",
    skipped: "skipped",
    cancelled: "cancelled"
  }
};

const ocrLanguageOptions = [
  { value: "eng+kor", ko: "한국어 + 영어", en: "Korean + English" },
  { value: "kor", ko: "한국어", en: "Korean" },
  { value: "eng", ko: "영어", en: "English" }
];

function relativePathFor(file: File): string {
  const withFolder = (file as File & { webkitRelativePath?: string }).webkitRelativePath;
  return withFolder || file.name;
}

function formatBytes(bytes: number): string {
  if (!bytes) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const index = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  return `${(bytes / 1024 ** index).toFixed(index === 0 ? 0 : 1)} ${units[index]}`;
}

function elapsed(manifest: BatchManifest | null): string {
  if (!manifest?.started_at) return "-";
  const start = new Date(manifest.started_at).getTime();
  const end = manifest.completed_at ? new Date(manifest.completed_at).getTime() : Date.now();
  return `${Math.max(0, Math.round((end - start) / 1000))}s`;
}

function statusLabel(status: FileStatus | string, language: Language): string {
  return statusCopy[language][status] ?? status.replaceAll("_", " ");
}

export default function App() {
  const [batch, setBatch] = useState<BatchManifest | null>(null);
  const [localUploads, setLocalUploads] = useState<LocalUpload[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [options, setOptions] = useState<ConversionOptions>(defaultOptions);
  const [language, setLanguage] = useState<Language>("ko");
  const [isSettingsOpen, setIsSettingsOpen] = useState(false);
  const folderInputRef = useRef<HTMLInputElement | null>(null);
  const t = copy[language];

  useEffect(() => {
    if (folderInputRef.current) {
      folderInputRef.current.setAttribute("webkitdirectory", "");
      folderInputRef.current.setAttribute("directory", "");
    }
  }, []);

  useEffect(() => {
    if (!batch?.batch_id || terminalStatuses.has(batch.status)) return;
    const id = window.setInterval(async () => {
      try {
        setBatch(await getStatus(batch.batch_id));
      } catch (error) {
        setMessage(error instanceof Error ? error.message : t.refreshError);
      }
    }, 1500);
    return () => window.clearInterval(id);
  }, [batch?.batch_id, batch?.status, t.refreshError]);

  const rows = useMemo(() => {
    const remote = batch?.files ?? [];
    const remotePaths = new Set(remote.map((file) => file.relative_path));
    const pending = localUploads.filter((file) => !remotePaths.has(file.relativePath));
    return { pending, remote };
  }, [batch?.files, localUploads]);

  async function ensureBatch(): Promise<BatchManifest> {
    if (batch) return batch;
    const created = await createBatch(options);
    setBatch(created);
    setOptions(created.options);
    return created;
  }

  async function changeOptions(next: ConversionOptions) {
    setOptions(next);
    if (!batch) return;
    try {
      const updated = await updateBatchOptions(batch.batch_id, next);
      setBatch(updated);
      setOptions(updated.options);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t.optionsError);
    }
  }

  async function uploadFiles(files: File[]) {
    if (!files.length) return;
    setMessage(null);
    setIsUploading(true);
    const current = await ensureBatch();
    const locals: LocalUpload[] = files.map((file) => ({
      key: `${relativePathFor(file)}-${file.size}-${file.lastModified}`,
      name: file.name,
      relativePath: relativePathFor(file),
      size: file.size,
      type: file.type || file.name.split(".").pop() || "",
      progress: 0,
      status: "waiting"
    }));
    setLocalUploads((existing) => [...existing, ...locals]);

    let latest = current;
    for (const file of files) {
      const path = relativePathFor(file);
      setLocalUploads((existing) =>
        existing.map((item) => (item.relativePath === path ? { ...item, status: "uploading", progress: 0 } : item))
      );
      try {
        latest = await uploadOneFile(current.batch_id, file, path, (progress) => {
          setLocalUploads((existing) =>
            existing.map((item) => (item.relativePath === path ? { ...item, progress } : item))
          );
        });
        setBatch(latest);
        setLocalUploads((existing) =>
          existing.map((item) => (item.relativePath === path ? { ...item, status: "uploaded", progress: 100 } : item))
        );
      } catch (error) {
        const text = error instanceof Error ? error.message : t.uploadError;
        setLocalUploads((existing) =>
          existing.map((item) => (item.relativePath === path ? { ...item, status: "failed", error: text } : item))
        );
      }
    }
    setIsUploading(false);
  }

  function onDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    setIsDragging(false);
    uploadFiles(Array.from(event.dataTransfer.files));
  }

  async function runAction(action: () => Promise<BatchManifest | void>) {
    setMessage(null);
    try {
      const result = await action();
      if (result) setBatch(result);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : t.actionError);
    }
  }

  async function resetBatch() {
    if (batch) await deleteBatch(batch.batch_id);
    setBatch(null);
    setLocalUploads([]);
    setMessage(null);
  }

  const canConvert = !!batch && batch.files.some((file) => ["uploaded", "failed"].includes(file.status));
  const hasFailures = !!batch && batch.files.some((file) => file.status === "failed");
  const hasCompleted = !!batch && batch.completed_files > 0;

  return (
    <main className="app-shell">
      <section className="topbar">
        <div>
          <h1>{t.title}</h1>
          <p>{t.subtitle}</p>
        </div>
        <div className="topbar-actions">
          <label className="language-control">
            <span>{t.language}</span>
            <select value={language} onChange={(event) => setLanguage(event.target.value as Language)}>
              <option value="ko">한국어</option>
              <option value="en">English</option>
            </select>
          </label>
          <button type="button" onClick={() => setIsSettingsOpen(true)}>
            {t.openSettings}
          </button>
          <div className="batch-pill">{batch ? batch.batch_id : t.noBatch}</div>
        </div>
      </section>

      <section
        className={`upload-zone ${isDragging ? "dragging" : ""}`}
        onDragOver={(event) => {
          event.preventDefault();
          setIsDragging(true);
        }}
        onDragLeave={() => setIsDragging(false)}
        onDrop={onDrop}
      >
        <div>
          <h2>{t.uploadTitle}</h2>
          <p>{t.uploadBody}</p>
          <p>{t.uploadNote}</p>
        </div>
        <div className="upload-actions">
          <label className="button primary">
            {t.selectFiles}
            <input type="file" multiple hidden onChange={(event) => uploadFiles(Array.from(event.target.files ?? []))} />
          </label>
          <label className="button">
            {t.selectFolder}
            <input
              ref={folderInputRef}
              type="file"
              multiple
              hidden
              onChange={(event) => uploadFiles(Array.from(event.target.files ?? []))}
            />
          </label>
        </div>
      </section>

      <section className="controls">
        <button disabled={!canConvert || isUploading} onClick={() => runAction(() => startConversion(batch!.batch_id))}>
          {t.start}
        </button>
        <button type="button" onClick={() => setIsSettingsOpen(true)}>
          {t.openSettings}
        </button>
        <button disabled={!batch} onClick={() => runAction(() => cancelBatch(batch!.batch_id))}>
          {t.cancel}
        </button>
        <button disabled={!hasFailures} onClick={() => runAction(() => retryFailed(batch!.batch_id))}>
          {t.retry}
        </button>
        <a className={`button ${hasCompleted ? "" : "disabled"}`} href={batch && hasCompleted ? zipDownloadUrl(batch.batch_id) : undefined}>
          {t.downloadZip}
        </a>
        <button disabled={!batch} onClick={() => runAction(resetBatch)}>
          {t.deleteBatch}
        </button>
      </section>

      {message && <div className="message">{message}</div>}

      <section className="summary-grid">
        <Summary label={t.total} value={batch?.total_files ?? localUploads.length} />
        <Summary label={t.completed} value={batch?.completed_files ?? 0} />
        <Summary label={t.failed} value={batch?.failed_files ?? 0} />
        <Summary label={t.skipped} value={batch?.skipped_files ?? 0} />
        <Summary label={t.cancelled} value={batch?.cancelled_files ?? 0} />
        <Summary label={t.elapsed} value={elapsed(batch)} />
      </section>

      <section className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>{t.file}</th>
              <th>{t.relativePath}</th>
              <th>{t.size}</th>
              <th>{t.type}</th>
              <th>{t.status}</th>
              <th>{t.progress}</th>
              <th>{t.error}</th>
              <th>{t.download}</th>
            </tr>
          </thead>
          <tbody>
            {rows.pending.map((file) => (
              <LocalRow key={file.key} file={file} language={language} uploadProgressLabel={t.uploadProgress} />
            ))}
            {rows.remote.map((file) => (
              <RemoteRow key={file.file_id} batchId={batch!.batch_id} file={file} language={language} mdLabel={t.md} />
            ))}
            {!rows.pending.length && !rows.remote.length && (
              <tr>
                <td colSpan={8} className="empty">
                  {t.empty}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>

      {isSettingsOpen && (
        <div className="modal-backdrop" role="presentation" onMouseDown={() => setIsSettingsOpen(false)}>
          <section
            className="settings-modal"
            role="dialog"
            aria-modal="true"
            aria-labelledby="settings-title"
            onMouseDown={(event) => event.stopPropagation()}
          >
            <div className="settings-header">
              <div>
                <h2 id="settings-title">{t.settingsTitle}</h2>
                <p>{t.settingsBody}</p>
              </div>
              <div className="settings-actions">
                <span className="settings-state">{batch ? t.settingsSaved : t.settingsPending}</span>
                <button type="button" onClick={() => setIsSettingsOpen(false)}>
                  {t.closeSettings}
                </button>
              </div>
            </div>
            <div className="settings-grid">
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={options.enable_ocr}
                  onChange={(event) => changeOptions({ ...options, enable_ocr: event.target.checked })}
                />
                <span>
                  {t.enableOcr}
                  <small>{t.enableOcrHelp}</small>
                </span>
              </label>
              <label className="field-row">
                <span>{t.ocrLanguages}</span>
                <select
                  value={options.ocr_languages}
                  onChange={(event) => changeOptions({ ...options, ocr_languages: event.target.value })}
                >
                  {ocrLanguageOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {language === "ko" ? option.ko : option.en}
                    </option>
                  ))}
                </select>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={options.enable_zip_extraction}
                  disabled={!!batch && batch.files.length > 0}
                  onChange={(event) => changeOptions({ ...options, enable_zip_extraction: event.target.checked })}
                />
                <span>
                  {t.extractZip}
                  <small>{t.extractZipHelp}</small>
                </span>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={options.enable_pandoc_fallback}
                  onChange={(event) => changeOptions({ ...options, enable_pandoc_fallback: event.target.checked })}
                />
                <span>
                  {t.pandoc}
                  <small>{t.pandocHelp}</small>
                </span>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={options.enable_tika_fallback}
                  onChange={(event) => changeOptions({ ...options, enable_tika_fallback: event.target.checked })}
                />
                <span>
                  {t.tika}
                  <small>{t.tikaHelp}</small>
                </span>
              </label>
              <label className="toggle-row">
                <input
                  type="checkbox"
                  checked={options.enable_libreoffice_fallback}
                  onChange={(event) => changeOptions({ ...options, enable_libreoffice_fallback: event.target.checked })}
                />
                <span>
                  {t.libreoffice}
                  <small>{t.libreofficeHelp}</small>
                </span>
              </label>
            </div>
          </section>
        </div>
      )}
    </main>
  );
}

function Summary({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="summary-item">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function LocalRow({
  file,
  language,
  uploadProgressLabel
}: {
  file: LocalUpload;
  language: Language;
  uploadProgressLabel: string;
}) {
  return (
    <tr>
      <td>{file.name}</td>
      <td>{file.relativePath}</td>
      <td>{formatBytes(file.size)}</td>
      <td>{file.type || "-"}</td>
      <td>
        <Status status={file.status} language={language} />
      </td>
      <td>
        <Progress value={file.progress} label={`${file.progress}% ${uploadProgressLabel}`} />
      </td>
      <td className="error-cell">{file.error ?? "-"}</td>
      <td>-</td>
    </tr>
  );
}

function RemoteRow({
  batchId,
  file,
  language,
  mdLabel
}: {
  batchId: string;
  file: FileRecord;
  language: Language;
  mdLabel: string;
}) {
  const progress = file.status === "completed" ? 100 : file.status === "converting" ? 65 : file.status === "queued" ? 35 : file.upload_progress;
  return (
    <tr>
      <td>{file.original_name}</td>
      <td>{file.relative_path}</td>
      <td>{formatBytes(file.size_bytes)}</td>
      <td>{file.extension || file.mime_type || "-"}</td>
      <td>
        <Status status={file.status} language={language} />
      </td>
      <td>
        <Progress value={progress} label={file.conversion_stage || `${progress}%`} />
      </td>
      <td className="error-cell">{file.error ?? "-"}</td>
      <td>
        {file.status === "completed" ? (
          <a className="download-link" href={fileDownloadUrl(batchId, file.file_id)}>
            {mdLabel}
          </a>
        ) : (
          "-"
        )}
      </td>
    </tr>
  );
}

function Status({ status, language }: { status: FileStatus; language: Language }) {
  return <span className={`status status-${status}`}>{statusLabel(status, language)}</span>;
}

function Progress({ value, label }: { value: number; label: string }) {
  return (
    <div className="progress-cell">
      <div className="progress-track">
        <div className="progress-fill" style={{ width: `${Math.max(0, Math.min(100, value))}%` }} />
      </div>
      <span>{label}</span>
    </div>
  );
}
