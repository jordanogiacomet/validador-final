export type ValidationScope = "zero_items" | "all_items" | "duplicate_items";

export type JobStatus = "queued" | "running" | "completed" | "failed" | "canceled";

export type StatusChipKind = "info" | "warning" | "success" | "error";

export type ReviewFlagStatus = "review";

export type ReviewFlagActionStatus = ReviewFlagStatus | "clear";

export type OperatorRole = "platform_admin" | "tenant_admin" | "operator";

export interface TenantListItem {
  tenant_id: string;
  display_name: string;
  is_default: boolean;
}

export interface LoginRequestPayload {
  tenantId: string;
  username: string;
  password: string;
}

export interface InitialSetupState {
  available: boolean;
  storage_configured: boolean;
  requires_setup_token: boolean;
  tenant_id: string | null;
}

export interface InitialAdminSetupPayload {
  username: string;
  password: string;
  setupToken?: string;
}

export interface OperatorResponse {
  tenant_id: string;
  operator_id: string;
  username: string;
  role?: OperatorRole;
  disabled: boolean;
  is_seed: boolean;
}

export interface LoginResponse {
  tenant_id: string;
  operator_id: string;
  role?: OperatorRole;
  api_key_id: string;
  x_api_key: string;
  header_name: string;
  expires_at?: string | null;
}

export interface APIKeyRenewalResponse {
  tenant_id: string;
  operator_id: string;
  role?: OperatorRole;
  api_key_id: string;
  previous_api_key_id: string;
  x_api_key: string;
  expires_at: string;
  header_name: string;
}

export type AuditEventType =
  | "job_created"
  | "job_completed"
  | "job_reprocessed"
  | "duplicates_resolved"
  | "api_key_issued"
  | "api_key_expired"
  | "api_key_revoked"
  | "api_key_renewed"
  | "initial_admin_created"
  | "operator_created"
  | "operator_disabled"
  | "operator_password_rotated"
  | "authorization_denied";

export interface AuditEventResponse {
  event_id: string;
  event_type: AuditEventType | string;
  tenant_id: string;
  job_id: string | null;
  api_key_id: string | null;
  created_at: string;
  details: Record<string, unknown>;
}

export interface UploadResponse {
  job_id: string;
  status: JobStatus;
  tenant_id: string;
  validation_scope: ValidationScope;
}

export interface SummaryPayload {
  total_rows: number;
  validated_rows?: number;
  source_total_rows?: number;
  rows_with_issues: number;
  total_issues: number;
  error_count: number;
  warning_count: number;
  processed_rows?: number;
}

export interface ValidationIssuePayload {
  code: string;
  severity: "error" | "warning";
  message: string;
  field: string | null;
}

export interface RowResult {
  row_index: number;
  item: string | null;
  descricao: string | null;
  issues: ValidationIssuePayload[];
  has_errors: boolean;
  has_warnings: boolean;
}

export interface ProblemOccurrence {
  row_index: number;
  item: string | null;
  descricao: string | null;
  severity: "error" | "warning";
  message: string;
  field: string | null;
}

export interface DuplicateGroup {
  item: string | null;
  descricao: string | null;
  has_description_conflict?: boolean;
  row_indices: number[];
  count: number;
}

export interface ReviewFlagPayload {
  row_index: number;
  status: ReviewFlagStatus;
}

export interface RowReviewFlagResponse {
  job_id: string;
  row_index: number;
  status: ReviewFlagActionStatus;
  review_flags: ReviewFlagPayload[];
}

export interface JobResultPayload {
  summary: SummaryPayload;
  row_results: RowResult[];
  duplicates: DuplicateGroup[];
  grouped_problems: Record<string, ProblemOccurrence[]>;
  review_flags?: ReviewFlagPayload[];
}

export interface JobStatusResponse {
  job_id: string;
  tenant_id: string;
  validation_scope: ValidationScope;
  status: JobStatus;
  total_rows: number;
  source_total_rows: number;
  rows_with_issues: number;
  total_issues: number;
  processed_rows: number;
  batch_size: number;
  error_message: string | null;
  partial_summary: Partial<SummaryPayload>;
  is_partial_result_available: boolean;
  partial_grouped_problems: Record<string, ProblemOccurrence[]>;
  partial_duplicates: DuplicateGroup[];
  row_results_preview: RowResult[];
  current_step: string | null;
  status_title: string | null;
  status_detail: string | null;
  created_at: string | null;
  updated_at: string | null;
  file_name: string | null;
  cancel_requested: boolean;
  parent_job_id?: string | null;
  latest_retry_job_id?: string | null;
}

export interface JobListItemResponse {
  job_id: string;
  tenant_id: string;
  validation_scope: ValidationScope;
  status: JobStatus;
  file_name: string | null;
  created_at: string | null;
  updated_at: string | null;
  current_step: string | null;
  status_title: string | null;
  status_detail: string | null;
  processed_rows: number;
  total_rows: number;
  source_total_rows: number;
  cancel_requested: boolean;
  parent_job_id?: string | null;
  latest_retry_job_id?: string | null;
}

export interface RowReadResponse {
  job_id: string;
  row_index: number;
  row: Record<string, string>;
  resolved_columns: Record<string, string>;
}

export interface RowUpdateResponse {
  job_id: string;
  row_index: number;
  updated_row: Record<string, string>;
}

export interface DuplicateResolutionResponse {
  job_id: string;
  kept_row_index: number;
  deleted_row_indices: number[];
  remaining_rows: number;
  merged_columns: string[];
}

export interface PreviewReportPayload {
  summary: Partial<SummaryPayload>;
  duplicates: DuplicateGroup[];
  grouped_problems: Record<string, ProblemOccurrence[]>;
  row_results: RowResult[];
  review_flags?: ReviewFlagPayload[];
}

export interface StatusChip {
  label: string;
  kind: StatusChipKind;
}

export interface BannerState {
  kind: StatusChipKind;
  label: string;
  detail: string;
}

export interface EditModalState {
  rowIndex: number;
  field: string;
  fieldKey: string;
  itemLabel: string;
  sourceColumn: string;
  currentValue: string;
}

export interface DuplicateRowOption {
  rowIndex: number;
  rowPayload: RowReadResponse;
}

export interface DuplicateModalState {
  duplicate: DuplicateGroup;
  rows: DuplicateRowOption[];
  suggestedKeepRowIndex: number;
}
