import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
  CorrectionHistoryEntryPayload,
  JobResultPayload,
  JobStatusResponse,
  SummaryPayload,
} from "@/lib/types";

import { ResultWorkspace } from "./result-workspace";

function buildJob(overrides: Partial<JobStatusResponse> = {}): JobStatusResponse {
  return {
    job_id: "job-1",
    tenant_id: "default",
    validation_scope: "zero_items",
    status: "completed",
    total_rows: 1,
    source_total_rows: 1,
    rows_with_issues: 0,
    total_issues: 0,
    processed_rows: 1,
    batch_size: 1,
    error_message: null,
    partial_summary: {},
    is_partial_result_available: false,
    partial_grouped_problems: {},
    partial_duplicates: [],
    row_results_preview: [],
    current_step: "report_ready",
    status_title: "Relatório pronto",
    status_detail: null,
    created_at: null,
    updated_at: null,
    file_name: "arquivo.csv",
    cancel_requested: false,
    parent_job_id: null,
    latest_retry_job_id: null,
    ...overrides,
  };
}

function buildReport(
  overrides: Partial<JobResultPayload> = {},
): JobResultPayload {
  const summary: SummaryPayload = {
    total_rows: 1,
    validated_rows: 1,
    source_total_rows: 1,
    rows_with_issues: 0,
    total_issues: 0,
    error_count: 0,
    warning_count: 0,
    processed_rows: 1,
  };
  return {
    summary,
    row_results: [],
    duplicates: [],
    grouped_problems: {},
    review_flags: [],
    correction_history: [],
    ...overrides,
  };
}

function renderWorkspace(
  job: JobStatusResponse | null,
  options: {
    onOpenRelatedJob?: (jobId: string) => void;
    reportData?: JobResultPayload;
    onRevertCorrection?: (eventId: string) => void;
  } = {},
) {
  return render(
    <ResultWorkspace
      job={job}
      currentJobId={job?.job_id ?? null}
      validationScope="zero_items"
      reportData={options.reportData ?? buildReport()}
      previewData={null}
      hasPendingCorrections={false}
      visibleProblemOccurrencesByCode={{}}
      isReprocessing={false}
      isResolvingBulkSameNameDuplicates={false}
      isSavingReviewFlag={false}
      revertingCorrectionEventId={null}
      onShowMore={vi.fn()}
      onEditOccurrence={vi.fn()}
      onToggleReviewFlag={vi.fn()}
      onRevertCorrection={options.onRevertCorrection ?? vi.fn()}
      onResolveDuplicate={vi.fn()}
      onResolveBulkSameNameDuplicates={vi.fn()}
      onReprocess={vi.fn()}
      onOpenRelatedJob={options.onOpenRelatedJob}
    />,
  );
}

describe("ResultWorkspace job lineage", () => {
  it("shows the simplified review guide before the summary cards", () => {
    renderWorkspace(buildJob());

    expect(screen.getByText("3. Revise o resultado")).toBeDefined();
    expect(screen.getByText("Nenhuma pendência aberta neste lote")).toBeDefined();
  });

  it("hides the lineage banner when the job has no reprocess relations", () => {
    renderWorkspace(buildJob());
    expect(screen.queryByLabelText("Histórico de reprocessamento")).toBeNull();
  });

  it("renders parent job lineage and opens the related job on click", () => {
    const onOpenRelatedJob = vi.fn();
    renderWorkspace(
      buildJob({
        job_id: "child-1",
        parent_job_id: "parent-0",
      }),
      { onOpenRelatedJob },
    );

    const link = screen.getByRole("button", { name: /Lote originado de parent-0/ });
    fireEvent.click(link);
    expect(onOpenRelatedJob).toHaveBeenCalledWith("parent-0");
  });

  it("renders latest retry link when the job was already reprocessed", () => {
    const onOpenRelatedJob = vi.fn();
    renderWorkspace(
      buildJob({
        job_id: "parent-0",
        latest_retry_job_id: "child-1",
      }),
      { onOpenRelatedJob },
    );

    const link = screen.getByRole("button", {
      name: /Reprocessamento mais recente: child-1/,
    });
    fireEvent.click(link);
    expect(onOpenRelatedJob).toHaveBeenCalledWith("child-1");
  });

  it("renders correction history with diff and revert action", () => {
    const onRevertCorrection = vi.fn();
    const correctionHistory: CorrectionHistoryEntryPayload[] = [
      {
        event_id: "corr-2",
        event_type: "job_review_flag_updated",
        action: "review_flag",
        tenant_id: "default",
        job_id: "job-1",
        api_key_id: "issued-1",
        created_at: "2026-04-22T13:00:00Z",
        actor_operator_id: "operator-1",
        actor_username: "operador.teste",
        actor_role: "operator",
        row_index: 1,
        row_indices: [],
        kept_row_index: null,
        current_kept_row_index: null,
        deleted_row_indices: [],
        merged_columns: [],
        field_diffs: [],
        before_status: "clear",
        after_status: "review",
        before_rows: [],
        after_rows: [],
        is_reverted: false,
        reverted_at: null,
        reverted_by_event_id: null,
        can_revert: true,
        revert_blocked_reason: null,
      },
      {
        event_id: "corr-1",
        event_type: "job_row_updated",
        action: "row_update",
        tenant_id: "default",
        job_id: "job-1",
        api_key_id: "issued-1",
        created_at: "2026-04-22T12:55:00Z",
        actor_operator_id: "operator-1",
        actor_username: "operador.teste",
        actor_role: "operator",
        row_index: 1,
        row_indices: [],
        kept_row_index: null,
        current_kept_row_index: null,
        deleted_row_indices: [],
        merged_columns: [],
        field_diffs: [
          {
            field: "complemento",
            source_column: "Complemento",
            before: "",
            after: "Detalhe revisado",
          },
        ],
        before_status: null,
        after_status: null,
        before_rows: [],
        after_rows: [],
        is_reverted: false,
        reverted_at: null,
        reverted_by_event_id: null,
        can_revert: false,
        revert_blocked_reason: "Desfaça primeiro a correção mais recente.",
      },
    ];

    renderWorkspace(buildJob(), {
      reportData: buildReport({ correction_history: correctionHistory }),
      onRevertCorrection,
    });

    expect(screen.getByLabelText("Histórico de correções")).toBeDefined();
    expect(screen.getByText("Histórico manual deste lote")).toBeDefined();
    expect(screen.getByText(/Complemento/)).toBeDefined();
    expect(screen.getByText("Desfaça primeiro a correção mais recente.")).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Desfazer correção" }));
    expect(onRevertCorrection).toHaveBeenCalledWith("corr-2");
  });
});
