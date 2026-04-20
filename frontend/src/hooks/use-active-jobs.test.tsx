import { renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { listJobs } from "@/lib/api";
import type { JobListItemResponse } from "@/lib/types";

import { useActiveJobs } from "./use-active-jobs";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listJobs: vi.fn(),
  };
});

const listJobsMock = vi.mocked(listJobs);

function buildJob(overrides: Partial<JobListItemResponse> = {}): JobListItemResponse {
  return {
    job_id: "job-1",
    tenant_id: "default",
    validation_scope: "zero_items",
    status: "completed",
    file_name: "inventario.csv",
    created_at: "2026-04-18T12:00:00Z",
    updated_at: "2026-04-18T12:02:00Z",
    current_step: "report_ready",
    status_title: "Relatório pronto",
    status_detail: "Arquivos disponíveis.",
    processed_rows: 10,
    total_rows: 10,
    source_total_rows: 10,
    cancel_requested: false,
    parent_job_id: null,
    latest_retry_job_id: null,
    ...overrides,
  };
}

describe("useActiveJobs", () => {
  beforeEach(() => {
    listJobsMock.mockReset();
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
  });

  it("loads recent jobs by default instead of active-only jobs", async () => {
    listJobsMock.mockResolvedValue([buildJob()]);

    const { result } = renderHook(() => useActiveJobs({ intervalMs: 1000 }));

    await waitFor(() => expect(result.current.isLoading).toBe(false));

    expect(listJobsMock).toHaveBeenCalledWith({ activeOnly: false, limit: 8 });
    expect(result.current.jobs).toHaveLength(1);
    expect(result.current.jobs[0]?.status).toBe("completed");
  });

  it("can still request active-only jobs when configured", async () => {
    listJobsMock.mockResolvedValue([buildJob({ status: "running" })]);

    renderHook(() => useActiveJobs({ activeOnly: true, limit: 3, intervalMs: 1000 }));

    await waitFor(() => {
      expect(listJobsMock).toHaveBeenCalledWith({ activeOnly: true, limit: 3 });
    });
  });
});
