import { DragEvent, useEffect, useMemo, useRef, useState } from "react";
import {
  cancelBatch,
  createBatch,
  deleteBatch,
  fileDownloadUrl,
  getStatus,
  retryFailed,
  startConversion,
  uploadOneFile,
  zipDownloadUrl
} from "./api";
import type { BatchManifest, FileRecord, FileStatus, LocalUpload } from "./types";

const terminalStatuses = new Set(["completed", "completed_with_errors", "failed", "cancelled"]);

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

function statusLabel(status: FileStatus | string): string {
  return status.replaceAll("_", " ");
}

export default function App() {
  const [batch, setBatch] = useState<BatchManifest | null>(null);
  const [localUploads, setLocalUploads] = useState<LocalUpload[]>([]);
  const [isDragging, setIsDragging] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const folderInputRef = useRef<HTMLInputElement | null>(null);

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
        setMessage(error instanceof Error ? error.message : "Could not refresh status.");
      }
    }, 1500);
    return () => window.clearInterval(id);
  }, [batch?.batch_id, batch?.status]);

  const rows = useMemo(() => {
    const remote = batch?.files ?? [];
    const remotePaths = new Set(remote.map((file) => file.relative_path));
    const pending = localUploads.filter((file) => !remotePaths.has(file.relativePath));
    return { pending, remote };
  }, [batch?.files, localUploads]);

  async function ensureBatch(): Promise<BatchManifest> {
    if (batch) return batch;
    const created = await createBatch();
    setBatch(created);
    return created;
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
        const text = error instanceof Error ? error.message : "Upload failed.";
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
      setMessage(error instanceof Error ? error.message : "Action failed.");
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
          <h1>Bulk Markdown Converter</h1>
          <p>Temporary file-to-Markdown preprocessing for RAG and document indexing pipelines.</p>
        </div>
        <div className="batch-pill">{batch ? batch.batch_id : "No batch created"}</div>
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
          <h2>Upload files or folders</h2>
          <p>
            Supports PDF, DOCX, PPTX, XLSX, CSV, JSON, XML, HTML, TXT, MD, ZIP, PNG, JPG, JPEG, and WEBP. Very large
            files depend on server CPU, memory, disk, timeouts, and converter limits.
          </p>
          <p>Complex layouts may not convert perfectly. Image conversion requires OCR to be enabled on the backend.</p>
        </div>
        <div className="upload-actions">
          <label className="button primary">
            Select files
            <input type="file" multiple hidden onChange={(event) => uploadFiles(Array.from(event.target.files ?? []))} />
          </label>
          <label className="button">
            Select folder
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
          Start conversion
        </button>
        <button disabled={!batch} onClick={() => runAction(() => cancelBatch(batch!.batch_id))}>
          Cancel batch
        </button>
        <button disabled={!hasFailures} onClick={() => runAction(() => retryFailed(batch!.batch_id))}>
          Retry failed
        </button>
        <a className={`button ${hasCompleted ? "" : "disabled"}`} href={batch && hasCompleted ? zipDownloadUrl(batch.batch_id) : undefined}>
          Download ZIP
        </a>
        <button disabled={!batch} onClick={() => runAction(resetBatch)}>
          Delete batch
        </button>
      </section>

      {message && <div className="message">{message}</div>}

      <section className="summary-grid">
        <Summary label="Total" value={batch?.total_files ?? localUploads.length} />
        <Summary label="Completed" value={batch?.completed_files ?? 0} />
        <Summary label="Failed" value={batch?.failed_files ?? 0} />
        <Summary label="Skipped" value={batch?.skipped_files ?? 0} />
        <Summary label="Cancelled" value={batch?.cancelled_files ?? 0} />
        <Summary label="Elapsed" value={elapsed(batch)} />
      </section>

      <section className="table-wrap">
        <table>
          <thead>
            <tr>
              <th>File</th>
              <th>Relative path</th>
              <th>Size</th>
              <th>Type</th>
              <th>Status</th>
              <th>Progress</th>
              <th>Error</th>
              <th>Download</th>
            </tr>
          </thead>
          <tbody>
            {rows.pending.map((file) => (
              <LocalRow key={file.key} file={file} />
            ))}
            {rows.remote.map((file) => (
              <RemoteRow key={file.file_id} batchId={batch!.batch_id} file={file} />
            ))}
            {!rows.pending.length && !rows.remote.length && (
              <tr>
                <td colSpan={8} className="empty">
                  No files uploaded yet.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </section>
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

function LocalRow({ file }: { file: LocalUpload }) {
  return (
    <tr>
      <td>{file.name}</td>
      <td>{file.relativePath}</td>
      <td>{formatBytes(file.size)}</td>
      <td>{file.type || "-"}</td>
      <td>
        <Status status={file.status} />
      </td>
      <td>
        <Progress value={file.progress} label={`${file.progress}% upload`} />
      </td>
      <td className="error-cell">{file.error ?? "-"}</td>
      <td>-</td>
    </tr>
  );
}

function RemoteRow({ batchId, file }: { batchId: string; file: FileRecord }) {
  const progress = file.status === "completed" ? 100 : file.status === "converting" ? 65 : file.status === "queued" ? 35 : file.upload_progress;
  return (
    <tr>
      <td>{file.original_name}</td>
      <td>{file.relative_path}</td>
      <td>{formatBytes(file.size_bytes)}</td>
      <td>{file.extension || file.mime_type || "-"}</td>
      <td>
        <Status status={file.status} />
      </td>
      <td>
        <Progress value={progress} label={file.conversion_stage || `${progress}%`} />
      </td>
      <td className="error-cell">{file.error ?? "-"}</td>
      <td>
        {file.status === "completed" ? (
          <a className="download-link" href={fileDownloadUrl(batchId, file.file_id)}>
            .md
          </a>
        ) : (
          "-"
        )}
      </td>
    </tr>
  );
}

function Status({ status }: { status: FileStatus }) {
  return <span className={`status status-${status}`}>{statusLabel(status)}</span>;
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

