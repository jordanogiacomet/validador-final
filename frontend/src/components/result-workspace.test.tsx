import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type {
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

function buildReport(): JobResultPayload {
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
  };
}

function renderWorkspace(job: JobStatusResponse | null, onOpenRelatedJob?: (jobId: string) => void) {
  return render(
    <ResultWorkspace
      job={job}
      currentJobId={job?.job_id ?? null}
      validationScope="zero_items"
      reportData={buildReport()}
      previewData={null}
      hasPendingCorrections={false}
      visibleProblemOccurrencesByCode={{}}
      isReprocessing={false}
      isResolvingBulkSameNameDuplicates={false}
      isSavingReviewFlag={false}
      onShowMore={vi.fn()}
      onEditOccurrence={vi.fn()}
      onToggleReviewFlag={vi.fn()}
      onResolveDuplicate={vi.fn()}
      onResolveBulkSameNameDuplicates={vi.fn()}
      onReprocess={vi.fn()}
      onOpenRelatedJob={onOpenRelatedJob}
    />,
  );
}

describe("ResultWorkspace job lineage", () => {
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
      onOpenRelatedJob,
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
      onOpenRelatedJob,
    );

    const link = screen.getByRole("button", {
      name: /Reprocessamento mais recente: child-1/,
    });
    fireEvent.click(link);
    expect(onOpenRelatedJob).toHaveBeenCalledWith("child-1");
  });
});
