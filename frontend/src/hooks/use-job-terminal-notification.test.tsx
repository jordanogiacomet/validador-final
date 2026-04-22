import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { JobStatusResponse } from "@/lib/types";

import { useJobTerminalNotification } from "./use-job-terminal-notification";

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
    created_at: "2026-04-18T12:00:00Z",
    updated_at: "2026-04-18T12:02:00Z",
    file_name: "inventario.csv",
    cancel_requested: false,
    parent_job_id: null,
    latest_retry_job_id: null,
    ...overrides,
  };
}

describe("useJobTerminalNotification", () => {
  const notificationSpy = vi.fn();

  beforeEach(() => {
    notificationSpy.mockReset();
    Object.defineProperty(document, "visibilityState", {
      configurable: true,
      value: "hidden",
    });

    class MockNotification {
      static permission: NotificationPermission = "granted";
      static requestPermission = vi
        .fn<() => Promise<NotificationPermission>>()
        .mockResolvedValue("granted");

      constructor(title: string, options?: NotificationOptions) {
        notificationSpy(title, options);
      }
    }

    vi.stubGlobal("Notification", MockNotification as unknown as typeof Notification);
    Object.defineProperty(window, "Notification", {
      configurable: true,
      value: MockNotification,
    });
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("notifies only once when the tracked lot reaches a terminal state", () => {
    const { rerender } = renderHook(
      ({ job }: { job: JobStatusResponse | null }) => useJobTerminalNotification(job),
      {
        initialProps: {
          job: buildJob({ status: "queued", processed_rows: 0 }),
        },
      },
    );

    rerender({ job: buildJob({ status: "running", processed_rows: 4 }) });
    expect(notificationSpy).not.toHaveBeenCalled();

    rerender({
      job: buildJob({
        status: "completed",
        processed_rows: 10,
        current_step: "report_ready",
        status_title: "Relatório pronto",
      }),
    });
    expect(notificationSpy).toHaveBeenCalledTimes(1);
    expect(notificationSpy).toHaveBeenCalledWith(
      "Lote concluido",
      expect.objectContaining({
        body: "inventario.csv terminou o processamento e ja pode ser revisado.",
        tag: "job-1:completed",
      }),
    );

    rerender({
      job: buildJob({
        status: "completed",
        processed_rows: 10,
        current_step: "report_ready",
        status_title: "Relatório pronto",
      }),
    });
    expect(notificationSpy).toHaveBeenCalledTimes(1);
  });

  it("skips browser notifications when permission is not granted", () => {
    class MockNotification {
      static permission: NotificationPermission = "denied";
      static requestPermission = vi
        .fn<() => Promise<NotificationPermission>>()
        .mockResolvedValue("denied");

      constructor(_title: string, _options?: NotificationOptions) {
        notificationSpy(_title, _options);
      }
    }

    vi.stubGlobal("Notification", MockNotification as unknown as typeof Notification);
    Object.defineProperty(window, "Notification", {
      configurable: true,
      value: MockNotification,
    });

    const { rerender } = renderHook(
      ({ job }: { job: JobStatusResponse | null }) => useJobTerminalNotification(job),
      {
        initialProps: {
          job: buildJob({ status: "running" }),
        },
      },
    );

    rerender({
      job: buildJob({
        status: "failed",
        error_message: "Falha inesperada",
        current_step: "failed",
      }),
    });

    expect(notificationSpy).not.toHaveBeenCalled();
  });
});
