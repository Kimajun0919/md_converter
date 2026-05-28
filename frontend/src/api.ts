import type { BatchManifest, ConversionOptions } from "./types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    let detail = "Request failed.";
    try {
      const body = await response.json();
      detail = body.detail ?? detail;
    } catch {
      detail = response.statusText || detail;
    }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export function createBatch(options: ConversionOptions): Promise<BatchManifest> {
  return request<BatchManifest>("/api/batches", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options)
  });
}

export function updateBatchOptions(batchId: string, options: ConversionOptions): Promise<BatchManifest> {
  return request<BatchManifest>(`/api/batches/${batchId}/options`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(options)
  });
}

export function getStatus(batchId: string): Promise<BatchManifest> {
  return request<BatchManifest>(`/api/batches/${batchId}/status`);
}

export function startConversion(batchId: string): Promise<BatchManifest> {
  return request<BatchManifest>(`/api/batches/${batchId}/convert`, { method: "POST" });
}

export function retryFailed(batchId: string): Promise<BatchManifest> {
  return request<BatchManifest>(`/api/batches/${batchId}/retry-failed`, { method: "POST" });
}

export function cancelBatch(batchId: string): Promise<BatchManifest> {
  return request<BatchManifest>(`/api/batches/${batchId}/cancel`, { method: "POST" });
}

export async function deleteBatch(batchId: string): Promise<void> {
  await request<{ status: string }>(`/api/batches/${batchId}`, { method: "DELETE" });
}

export function uploadOneFile(
  batchId: string,
  file: File,
  relativePath: string,
  onProgress: (progress: number) => void
): Promise<BatchManifest> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("files", file);
    form.append("relative_paths", relativePath);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/batches/${batchId}/files`);
    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) {
        onProgress(Math.round((event.loaded / event.total) * 100));
      }
    };
    xhr.onerror = () => reject(new Error("Upload failed."));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(JSON.parse(xhr.responseText) as BatchManifest);
      } else {
        try {
          const body = JSON.parse(xhr.responseText);
          reject(new Error(body.detail ?? "Upload failed."));
        } catch {
          reject(new Error(xhr.statusText || "Upload failed."));
        }
      }
    };
    xhr.send(form);
  });
}

export function fileDownloadUrl(batchId: string, fileId: string): string {
  return `${API_BASE}/api/batches/${batchId}/files/${fileId}/download`;
}

export function zipDownloadUrl(batchId: string): string {
  return `${API_BASE}/api/batches/${batchId}/download`;
}
