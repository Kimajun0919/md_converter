export type FileStatus =
  | "waiting"
  | "uploading"
  | "uploaded"
  | "queued"
  | "converting"
  | "completed"
  | "failed"
  | "skipped"
  | "cancelled";

export type BatchStatus =
  | "created"
  | "uploading"
  | "uploaded"
  | "queued"
  | "converting"
  | "completed"
  | "completed_with_errors"
  | "failed"
  | "cancelled"
  | "deleted";

export interface FileRecord {
  file_id: string;
  original_name: string;
  safe_name: string;
  relative_path: string;
  size_bytes: number;
  mime_type: string | null;
  extension: string;
  status: FileStatus;
  upload_path: string;
  output_path: string | null;
  source_container: string | null;
  converter: string | null;
  error: string | null;
  upload_progress: number;
  conversion_stage: string | null;
  created_at: string;
  updated_at: string;
}

export interface ConversionOptions {
  enable_ocr: boolean;
  ocr_languages: string;
  enable_pandoc_fallback: boolean;
  enable_tika_fallback: boolean;
  enable_libreoffice_fallback: boolean;
  enable_zip_extraction: boolean;
}

export interface BatchManifest {
  batch_id: string;
  created_at: string;
  updated_at: string;
  status: BatchStatus;
  total_files: number;
  completed_files: number;
  failed_files: number;
  skipped_files: number;
  cancelled_files: number;
  started_at: string | null;
  completed_at: string | null;
  cancellation_requested: boolean;
  options: ConversionOptions;
  files: FileRecord[];
}

export interface LocalUpload {
  key: string;
  name: string;
  relativePath: string;
  size: number;
  type: string;
  progress: number;
  status: FileStatus;
  error?: string;
}
