import type {
  DuplicateResolutionResponse,
  JobListItemResponse,
  JobResultPayload,
  JobStatusResponse,
  ReviewFlagActionStatus,
  RowReadResponse,
  RowReviewFlagResponse,
  RowUpdateResponse,
  TenantListItem,
  UploadResponse,
  ValidationScope,
} from "@/lib/types";

const DEFAULT_API_BASE_URL = "http://127.0.0.1:8000";
const DEPLOYED_BACKEND_PORT = "30091";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

export function getApiBaseUrl(): string {
  const configuredBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL?.trim();
  if (configuredBaseUrl) {
    return configuredBaseUrl.replace(/\/$/, "");
  }

  if (typeof window !== "undefined") {
    return `${window.location.protocol}//${window.location.hostname}:${DEPLOYED_BACKEND_PORT}`;
  }

  return DEFAULT_API_BASE_URL;
}

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}${normalizedPath}`;
}

async function readResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? ((await response.json()) as Record<string, unknown>)
    : { detail: await response.text() };

  if (!response.ok) {
    const detail =
      typeof payload.detail === "string" && payload.detail
        ? payload.detail
        : "Falha na comunicação com a API operacional.";
    throw new ApiError(detail, response.status);
  }

  return payload as T;
}

export async function listTenants(): Promise<TenantListItem[]> {
  const response = await fetch(buildApiUrl("/tenants"));
  return readResponse<TenantListItem[]>(response);
}

export async function validateFile(params: {
  file: File;
  tenantId: string;
  validationScope: ValidationScope;
}): Promise<UploadResponse> {
  const formData = new FormData();
  formData.append("file", params.file);

  const query = new URLSearchParams({
    tenant_id: params.tenantId,
    validation_scope: params.validationScope,
  });
  const response = await fetch(buildApiUrl(`/validate?${query.toString()}`), {
    method: "POST",
    body: formData,
  });
  return readResponse<UploadResponse>(response);
}

export async function listActiveJobs(): Promise<JobListItemResponse[]> {
  const response = await fetch(buildApiUrl("/jobs?active_only=true"));
  return readResponse<JobListItemResponse[]>(response);
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const response = await fetch(buildApiUrl(`/jobs/${jobId}`));
  return readResponse<JobStatusResponse>(response);
}

export async function cancelJob(jobId: string): Promise<JobStatusResponse> {
  const response = await fetch(buildApiUrl(`/jobs/${jobId}/cancel`), {
    method: "POST",
  });
  return readResponse<JobStatusResponse>(response);
}

export async function getJobResult(jobId: string): Promise<JobResultPayload> {
  const response = await fetch(buildApiUrl(`/jobs/${jobId}/result`));
  return readResponse<JobResultPayload>(response);
}

export async function getJobRow(
  jobId: string,
  rowIndex: number,
): Promise<RowReadResponse> {
  const response = await fetch(buildApiUrl(`/jobs/${jobId}/rows/${rowIndex}`));
  return readResponse<RowReadResponse>(response);
}

export async function updateJobRow(
  jobId: string,
  rowIndex: number,
  updates: Record<string, string>,
): Promise<RowUpdateResponse> {
  const response = await fetch(buildApiUrl(`/jobs/${jobId}/rows/${rowIndex}`), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ updates }),
  });
  return readResponse<RowUpdateResponse>(response);
}

export async function setJobRowReviewFlag(
  jobId: string,
  rowIndex: number,
  status: ReviewFlagActionStatus,
): Promise<RowReviewFlagResponse> {
  const response = await fetch(buildApiUrl(`/jobs/${jobId}/rows/${rowIndex}/flag`), {
    method: "PATCH",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ status }),
  });
  return readResponse<RowReviewFlagResponse>(response);
}

export async function resolveDuplicateRows(params: {
  jobId: string;
  rowIndices: number[];
  keepRowIndex: number;
}): Promise<DuplicateResolutionResponse> {
  const response = await fetch(buildApiUrl(`/jobs/${params.jobId}/duplicates/resolve`), {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({
      row_indices: params.rowIndices,
      keep_row_index: params.keepRowIndex,
    }),
  });
  return readResponse<DuplicateResolutionResponse>(response);
}

export async function reprocessJob(jobId: string): Promise<UploadResponse> {
  const response = await fetch(buildApiUrl(`/jobs/${jobId}/reprocess`), {
    method: "POST",
  });
  return readResponse<UploadResponse>(response);
}

export function buildReportUrl(jobId: string): string {
  return buildApiUrl(`/jobs/${jobId}/report`);
}

export function buildResultUrl(jobId: string): string {
  return buildApiUrl(`/jobs/${jobId}/result`);
}

export function buildCorrectedCsvUrl(jobId: string): string {
  return buildApiUrl(`/jobs/${jobId}/csv`);
}

export function buildOperationalExportUrl(
  jobId: string,
  kind: "duplicates" | "problem_group",
  problemCode?: string,
): string {
  const query = new URLSearchParams({ kind });
  if (problemCode) {
    query.set("problem_code", problemCode);
  }
  return buildApiUrl(`/jobs/${jobId}/exports/csv?${query.toString()}`);
}
