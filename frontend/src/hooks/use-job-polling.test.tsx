import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getJob } from "@/lib/api";
import type { JobStatusResponse } from "@/lib/types";

import { useJobPolling } from "./use-job-polling";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    getJob: vi.fn(),
  };
});

const getJobMock = vi.mocked(getJob);

function buildJob(overrides: Partial<JobStatusResponse> = {}): JobStatusResponse {
  return {
    job_id: "job-1",
    tenant_id: "default",
    validation_scope: "zero_items",
    status: "running",
    total_rows: 10,
    source_total_rows: 10,
    rows_with_issues: 0,
    total_issues: 0,
    processed_rows: 4,
    batch_size: 5,
    error_message: null,
    partial_summary: {},
    is_partial_result_available: false,
    partial_grouped_problems: {},
    partial_duplicates: [],
    row_results_preview: [],
    current_step: "validating_batches",
    status_title: "Validação",
    status_detail: "Processando.",
    created_at: null,
    updated_at: "2026-04-18T12:00:00Z",
    file_name: "inventario.csv",
    cancel_requested: false,
    parent_job_id: null,
    latest_retry_job_id: null,
    ...overrides,
  };
}

describe("useJobPolling", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    getJobMock.mockReset();
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("polls with timeout scheduling and stops after a terminal status", async () => {
    const onJobUpdate = vi.fn();
    getJobMock
      .mockResolvedValueOnce(buildJob())
      .mockResolvedValueOnce(buildJob({ status: "completed", processed_rows: 10 }));

    renderHook(() =>
      useJobPolling({
        jobId: "job-1",
        intervalMs: 1000,
        onJobUpdate,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });
    expect(getJobMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1000);
    });

    expect(getJobMock).toHaveBeenCalledTimes(2);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(getJobMock).toHaveBeenCalledTimes(2);
    expect(onJobUpdate).toHaveBeenLastCalledWith(
      expect.objectContaining({ status: "completed" }),
    );
  });

  it("keeps polling at the hidden cadence and refreshes immediately when visible again", async () => {
    const onJobUpdate = vi.fn();
    getJobMock.mockResolvedValue(buildJob());
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });

    renderHook(() =>
      useJobPolling({
        jobId: "job-1",
        intervalMs: 1000,
        hiddenIntervalMs: 5000,
        onJobUpdate,
      }),
    );

    await act(async () => {
      await Promise.resolve();
    });

    expect(getJobMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(4999);
    });

    expect(getJobMock).toHaveBeenCalledTimes(1);

    await act(async () => {
      await vi.advanceTimersByTimeAsync(5000);
    });

    expect(getJobMock).toHaveBeenCalledTimes(2);

    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "visible",
    });
    document.dispatchEvent(new Event("visibilitychange"));

    await act(async () => {
      await Promise.resolve();
    });
    expect(getJobMock).toHaveBeenCalledTimes(3);
  });
});
