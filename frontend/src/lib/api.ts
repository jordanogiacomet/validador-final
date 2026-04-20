import type {
  AuditEventResponse,
  APIKeyRenewalResponse,
  InitialAdminSetupPayload,
  InitialSetupState,
  DuplicateResolutionResponse,
  JobListItemResponse,
  LoginRequestPayload,
  LoginResponse,
  JobResultPayload,
  JobStatusResponse,
  OperatorResponse,
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
const API_KEY_HEADER = "X-API-Key";
const API_SESSION_STORAGE_KEY = "validator.api_session.v1";

let currentSession: LoginResponse | null = null;
let sessionInvalidHandler: (() => void) | null = null;

export class ApiError extends Error {
  status: number;
  detail: string;
  requestId: string | null;

  constructor(
    message: string,
    status: number,
    options: { detail?: string; requestId?: string | null } = {},
  ) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = options.detail ?? message;
    this.requestId = options.requestId ?? null;
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

function canUseSessionStorage(): boolean {
  return typeof window !== "undefined" && typeof window.sessionStorage !== "undefined";
}

function isLoginResponse(value: unknown): value is LoginResponse {
  if (!value || typeof value !== "object") {
    return false;
  }

  const candidate = value as Partial<LoginResponse>;
  return (
    typeof candidate.tenant_id === "string" &&
    typeof candidate.operator_id === "string" &&
    typeof candidate.api_key_id === "string" &&
    typeof candidate.x_api_key === "string" &&
    typeof candidate.header_name === "string"
  );
}

export function getApiSessionExpiresAtMs(): number | null {
  const session = getApiSession();
  if (!session?.expires_at) {
    return null;
  }
  const expiresAtMs = Date.parse(session.expires_at);
  return Number.isFinite(expiresAtMs) ? expiresAtMs : null;
}

function readPersistedApiSession(): LoginResponse | null {
  if (!canUseSessionStorage()) {
    return null;
  }

  const rawSession = window.sessionStorage.getItem(API_SESSION_STORAGE_KEY);
  if (!rawSession) {
    return null;
  }

  try {
    const parsedSession = JSON.parse(rawSession) as unknown;
    if (isLoginResponse(parsedSession)) {
      return parsedSession;
    }
  } catch {
    // Invalid persisted payloads should not keep the operator locked out.
  }

  window.sessionStorage.removeItem(API_SESSION_STORAGE_KEY);
  return null;
}

function persistApiSession(session: LoginResponse | null): void {
  if (!canUseSessionStorage()) {
    return;
  }

  if (!session) {
    window.sessionStorage.removeItem(API_SESSION_STORAGE_KEY);
    return;
  }

  window.sessionStorage.setItem(API_SESSION_STORAGE_KEY, JSON.stringify(session));
}

export function buildApiUrl(path: string): string {
  const normalizedPath = path.startsWith("/") ? path : `/${path}`;
  return `${getApiBaseUrl()}${normalizedPath}`;
}

export function getApiSession(): LoginResponse | null {
  if (!currentSession) {
    currentSession = readPersistedApiSession();
  }
  return currentSession;
}

export function setApiSession(session: LoginResponse | null): void {
  currentSession = session;
  persistApiSession(session);
}

export function clearApiSession(): void {
  currentSession = null;
  persistApiSession(null);
}

export function setApiSessionInvalidHandler(handler: (() => void) | null): void {
  sessionInvalidHandler = handler;
}

function buildRequestHeaders(headers?: HeadersInit, includeAuth = true): Headers {
  const nextHeaders = new Headers(headers);
  const apiKey = includeAuth ? getApiSession()?.x_api_key?.trim() : "";
  if (apiKey) {
    nextHeaders.set(API_KEY_HEADER, apiKey);
  }
  return nextHeaders;
}

async function readErrorDetail(response: Response): Promise<string> {
  const responseClone = response.clone();
  const contentType = responseClone.headers.get("content-type") || "";

  if (contentType.includes("application/json")) {
    try {
      const payload = (await responseClone.json()) as Record<string, unknown>;
      return typeof payload.detail === "string" ? payload.detail : "";
    } catch {
      return "";
    }
  }

  try {
    return await responseClone.text();
  } catch {
    return "";
  }
}

function readRequestId(response: Response): string | null {
  return response.headers.get("x-request-id") || response.headers.get("X-Request-ID");
}

function appendSupportCode(message: string, requestId: string | null): string {
  if (!requestId) {
    return message;
  }

  return `${message} Código de suporte: ${requestId}.`;
}

function mapApiErrorDetail(detail: string, status: number): string {
  const normalizedDetail = detail.toLowerCase();

  if (status === 401) {
    if (normalizedDetail.includes("missing x-api-key")) {
      return "Sessão operacional não encontrada. Entre novamente para continuar.";
    }

    if (normalizedDetail.includes("expired api key")) {
      return "Sua sessão expirou. Entre novamente para continuar.";
    }

    if (normalizedDetail.includes("revoked api key")) {
      return "Sua sessão foi encerrada. Entre novamente para continuar.";
    }

    if (normalizedDetail.includes("invalid api key")) {
      return "Sessão inválida. Entre novamente para continuar.";
    }

    return "Credenciais inválidas ou sessão expirada.";
  }

  if (status === 403) {
    if (
      normalizedDetail.includes("does not grant access") ||
      normalizedDetail.includes("not allowed for this tenant")
    ) {
      return "A sessão atual não permite acessar esta empresa. Entre com o usuário correto.";
    }

    if (normalizedDetail.includes("operator is disabled")) {
      return "Este usuário está desabilitado para a operação.";
    }

    return "Acesso negado para esta operação.";
  }

  if (status === 404) {
    if (normalizedDetail.includes("tenant")) {
      return "Empresa não encontrada. Revise o código informado.";
    }

    if (normalizedDetail.includes("job")) {
      return "Lote não encontrado. Atualize a lista de lotes e tente novamente.";
    }

    return "Registro não encontrado.";
  }

  if (
    normalizedDetail.includes("job not completed") ||
    normalizedDetail.includes("not completed")
  ) {
    return "O lote ainda não foi concluído. Aguarde o fim do processamento para baixar ou revisar.";
  }

  if (
    normalizedDetail.includes("csv") ||
    normalizedDetail.includes("delimiter") ||
    normalizedDetail.includes("encoding") ||
    normalizedDetail.includes("codec") ||
    normalizedDetail.includes("tokenizing") ||
    normalizedDetail.includes("column")
  ) {
    return "Não foi possível ler o CSV. Revise o arquivo, delimitador, codificação e cabeçalho.";
  }

  if (status >= 500) {
    return "A API operacional encontrou uma falha interna. Tente novamente ou acione o suporte.";
  }

  return detail || "Falha na comunicação com a API operacional.";
}

export function formatApiErrorMessage(
  error: unknown,
  fallbackMessage = "Falha na comunicação com a API operacional.",
): string {
  if (error instanceof ApiError) {
    return error.message || appendSupportCode(fallbackMessage, error.requestId);
  }

  if (error instanceof Error && error.message) {
    return error.message;
  }

  return fallbackMessage;
}

async function shouldInvalidateSession(
  response: Response,
  includeAuth: boolean,
): Promise<boolean> {
  if (!includeAuth || !getApiSession()) {
    return false;
  }

  if (response.status === 401) {
    return true;
  }

  if (response.status !== 403) {
    return false;
  }

  const detail = await readErrorDetail(response);
  return /invalid api key|expired api key|revoked api key/i.test(detail);
}

function invalidateSession(): void {
  if (!getApiSession()) {
    return;
  }

  clearApiSession();
  sessionInvalidHandler?.();
}

async function apiFetch(
  path: string,
  init: RequestInit = {},
  options: { includeAuth?: boolean } = {},
): Promise<Response> {
  const includeAuth = options.includeAuth ?? true;
  const response = await fetch(buildApiUrl(path), {
    ...init,
    headers: buildRequestHeaders(init.headers, includeAuth),
  });
  if (await shouldInvalidateSession(response, includeAuth)) {
    invalidateSession();
  }
  return response;
}

async function readResponse<T>(response: Response): Promise<T> {
  const contentType = response.headers.get("content-type") || "";
  const payload = contentType.includes("application/json")
    ? ((await response.json()) as Record<string, unknown>)
    : { detail: await response.text() };

  if (!response.ok) {
    const requestId = readRequestId(response);
    const detail =
      typeof payload.detail === "string" && payload.detail
        ? payload.detail
        : "Falha na comunicação com a API operacional.";
    throw new ApiError(
      appendSupportCode(mapApiErrorDetail(detail, response.status), requestId),
      response.status,
      { detail, requestId },
    );
  }

  return payload as T;
}

export async function listTenants(): Promise<TenantListItem[]> {
  const response = await apiFetch("/tenants");
  return readResponse<TenantListItem[]>(response);
}

export async function listAuditEvents(params: {
  tenantId?: string | null;
  limit?: number;
} = {}): Promise<AuditEventResponse[]> {
  const query = new URLSearchParams();
  if (params.tenantId?.trim()) {
    query.set("tenant_id", params.tenantId.trim());
  }
  if (params.limit) {
    query.set("limit", String(params.limit));
  }

  const queryString = query.toString();
  const response = await apiFetch(`/audit${queryString ? `?${queryString}` : ""}`);
  return readResponse<AuditEventResponse[]>(response);
}

export async function renewApiSession(): Promise<LoginResponse> {
  const response = await apiFetch("/api-keys/renew", { method: "POST" });
  const renewal = await readResponse<APIKeyRenewalResponse>(response);

  const nextSession: LoginResponse = {
    tenant_id: renewal.tenant_id,
    operator_id: renewal.operator_id,
    role: renewal.role,
    api_key_id: renewal.api_key_id,
    x_api_key: renewal.x_api_key,
    header_name: renewal.header_name,
    expires_at: renewal.expires_at,
  };
  setApiSession(nextSession);
  return nextSession;
}

export async function loginOperator(payload: LoginRequestPayload): Promise<LoginResponse> {
  const response = await apiFetch(
    "/login",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        tenant_id: payload.tenantId.trim(),
        username: payload.username.trim(),
        password: payload.password,
      }),
    },
    { includeAuth: false },
  );
  return readResponse<LoginResponse>(response);
}

export async function getInitialSetupState(): Promise<InitialSetupState> {
  const response = await apiFetch("/setup", {}, { includeAuth: false });
  return readResponse<InitialSetupState>(response);
}

export async function createInitialAdmin(
  payload: InitialAdminSetupPayload,
): Promise<OperatorResponse> {
  const response = await apiFetch(
    "/setup",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        username: payload.username.trim(),
        password: payload.password,
        setup_token: payload.setupToken?.trim() || null,
      }),
    },
    { includeAuth: false },
  );
  return readResponse<OperatorResponse>(response);
}

export async function completePasswordSetup(params: {
  apiKey: string;
  newPassword: string;
}): Promise<OperatorResponse> {
  const response = await apiFetch(
    "/operators/me/complete-password-setup",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        [API_KEY_HEADER]: params.apiKey.trim(),
      },
      body: JSON.stringify({
        new_password: params.newPassword,
      }),
    },
    { includeAuth: false },
  );
  return readResponse<OperatorResponse>(response);
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
  const response = await apiFetch(`/validate?${query.toString()}`, {
    method: "POST",
    body: formData,
  });
  return readResponse<UploadResponse>(response);
}

export async function listJobs(params: {
  activeOnly?: boolean;
  limit?: number;
} = {}): Promise<JobListItemResponse[]> {
  const query = new URLSearchParams();
  if (params.activeOnly) {
    query.set("active_only", "true");
  }
  if (params.limit) {
    query.set("limit", String(params.limit));
  }

  const queryString = query.toString();
  const response = await apiFetch(`/jobs${queryString ? `?${queryString}` : ""}`);
  return readResponse<JobListItemResponse[]>(response);
}

export async function listActiveJobs(): Promise<JobListItemResponse[]> {
  return listJobs({ activeOnly: true });
}

export async function getJob(jobId: string): Promise<JobStatusResponse> {
  const response = await apiFetch(`/jobs/${jobId}`);
  return readResponse<JobStatusResponse>(response);
}

export async function cancelJob(jobId: string): Promise<JobStatusResponse> {
  const response = await apiFetch(`/jobs/${jobId}/cancel`, {
    method: "POST",
  });
  return readResponse<JobStatusResponse>(response);
}

export async function getJobResult(jobId: string): Promise<JobResultPayload> {
  const response = await apiFetch(`/jobs/${jobId}/result`);
  return readResponse<JobResultPayload>(response);
}

export async function getJobRow(
  jobId: string,
  rowIndex: number,
): Promise<RowReadResponse> {
  const response = await apiFetch(`/jobs/${jobId}/rows/${rowIndex}`);
  return readResponse<RowReadResponse>(response);
}

export async function updateJobRow(
  jobId: string,
  rowIndex: number,
  updates: Record<string, string>,
): Promise<RowUpdateResponse> {
  const response = await apiFetch(`/jobs/${jobId}/rows/${rowIndex}`, {
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
  const response = await apiFetch(`/jobs/${jobId}/rows/${rowIndex}/flag`, {
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
  const response = await apiFetch(`/jobs/${params.jobId}/duplicates/resolve`, {
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
  const response = await apiFetch(`/jobs/${jobId}/reprocess`, {
    method: "POST",
  });
  return readResponse<UploadResponse>(response);
}

function resolveDownloadFileName(
  contentDisposition: string | null,
  fallbackFileName: string,
): string {
  if (!contentDisposition) {
    return fallbackFileName;
  }

  const encodedMatch = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
  if (encodedMatch?.[1]) {
    try {
      return decodeURIComponent(encodedMatch[1]);
    } catch {
      return fallbackFileName;
    }
  }

  const plainMatch = contentDisposition.match(/filename="?([^";]+)"?/i);
  return plainMatch?.[1] || fallbackFileName;
}

function triggerBrowserDownload(blob: Blob, fileName: string): void {
  const objectUrl = window.URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = objectUrl;
  link.download = fileName;
  link.rel = "noreferrer";
  link.style.display = "none";
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.URL.revokeObjectURL(objectUrl);
}

export function downloadGeneratedFile(
  content: string | Blob,
  fileName: string,
  options: { type?: string } = {},
): void {
  const blob =
    content instanceof Blob
      ? content
      : new Blob([content], { type: options.type ?? "application/octet-stream" });
  triggerBrowserDownload(blob, fileName);
}

export async function downloadApiFile(
  path: string,
  fallbackFileName: string,
): Promise<void> {
  const response = await apiFetch(path);
  if (!response.ok) {
    await readResponse<Record<string, never>>(response);
    return;
  }

  const blob = await response.blob();
  triggerBrowserDownload(
    blob,
    resolveDownloadFileName(response.headers.get("content-disposition"), fallbackFileName),
  );
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

export function buildCorrectedXlsxUrl(jobId: string): string {
  return buildApiUrl(`/jobs/${jobId}/export?format=xlsx`);
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
