import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuditPanel } from "./audit-panel";

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listAuditEvents: vi.fn(),
  };
});

import { listAuditEvents } from "@/lib/api";
import type { AuditEventResponse } from "@/lib/types";

const listAuditEventsMock = vi.mocked(listAuditEvents);

function buildEvent(overrides: Partial<AuditEventResponse> = {}): AuditEventResponse {
  return {
    event_id: "event-1",
    event_type: "api_key_issued",
    tenant_id: "default",
    job_id: null,
    api_key_id: "issued-1",
    created_at: "2026-04-18T12:00:00Z",
    details: {
      operator_id: "default-local-operator",
      expires_at: "2026-04-18T20:00:00Z",
    },
    ...overrides,
  };
}

function createDeferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, resolve, reject };
}

describe("AuditPanel", () => {
  beforeEach(() => {
    listAuditEventsMock.mockReset();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("shows the loading state and then renders the fetched audit events", async () => {
    const deferred = createDeferred<AuditEventResponse[]>();
    listAuditEventsMock.mockReturnValueOnce(deferred.promise);

    render(<AuditPanel tenantId="default" currentJobId={null} />);

    expect(screen.queryByLabelText("Tipo de evento")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Abrir histórico" }));
    expect(screen.getByText("Carregando trilha de auditoria...")).toBeDefined();

    deferred.resolve([
      buildEvent({
        event_id: "event-1",
        details: {
          operator_id: "default-local-operator",
          expires_at: "2026-04-18T20:00:00Z",
        },
      }),
    ]);

    await screen.findByText(/Operador default-local-operator\./);

    expect(listAuditEventsMock).toHaveBeenCalledWith({
      tenantId: "default",
      limit: 200,
    });
    expect(screen.getByText("issued-1")).toBeDefined();
    expect(document.querySelector('time[datetime="2026-04-18T12:00:00Z"]')).not.toBeNull();
  });

  it("filters audit events by type, recent window, and job reference", async () => {
    vi.spyOn(Date, "now").mockReturnValue(new Date("2026-04-18T12:00:00Z").getTime());
    listAuditEventsMock.mockResolvedValue([
      buildEvent({
        event_id: "event-issued",
        event_type: "api_key_issued",
        details: {
          operator_id: "default-local-operator",
        },
      }),
      buildEvent({
        event_id: "event-reprocess",
        event_type: "job_reprocessed",
        job_id: "job-200",
        api_key_id: "issued-2",
        details: {
          parent_job_id: "job-200",
          new_job_id: "job-201",
        },
      }),
      buildEvent({
        event_id: "event-completed",
        event_type: "job_completed",
        job_id: "job-300",
        created_at: "2026-04-01T12:00:00Z",
        api_key_id: "issued-3",
        details: {
          total_rows: 12,
          rows_with_issues: 3,
          total_issues: 5,
          validation_scope: "zero_items",
        },
      }),
    ]);

    render(<AuditPanel tenantId="default" currentJobId={null} />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir histórico" }));

    await screen.findByText("Novo lote job-201 gerado. Origem job-200.");

    fireEvent.change(screen.getByLabelText("Tipo de evento"), {
      target: { value: "job_reprocessed" },
    });

    expect(screen.getByText("Novo lote job-201 gerado. Origem job-200.")).toBeDefined();
    expect(screen.queryByText(/3 de 12 linha\(s\) em escopo/)).toBeNull();

    fireEvent.change(screen.getByLabelText("Lote"), {
      target: { value: "job-201" },
    });

    expect(screen.getByText("1 evento(s) exibido(s) de 3. Empresa em foco: default.")).toBeDefined();

    fireEvent.change(screen.getByLabelText("Tipo de evento"), {
      target: { value: "all" },
    });
    fireEvent.change(screen.getByLabelText("Período"), {
      target: { value: "24h" },
    });

    expect(screen.queryByText(/3 de 12 linha\(s\) em escopo/)).toBeNull();

    fireEvent.change(screen.getByLabelText("Lote"), {
      target: { value: "job-inexistente" },
    });

    expect(await screen.findByText("Nenhum evento corresponde aos filtros")).toBeDefined();
  });

  it("resets local filters when the active job context changes", async () => {
    listAuditEventsMock.mockResolvedValue([
      buildEvent({
        event_id: "event-completed",
        event_type: "job_completed",
        job_id: "job-1",
        details: {
          total_rows: 12,
          rows_with_issues: 3,
          total_issues: 5,
        },
      }),
    ]);

    const { rerender } = render(<AuditPanel tenantId="default" currentJobId="job-1" />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir histórico" }));

    await screen.findByText(/3 de 12 linha\(s\) em escopo/);

    fireEvent.change(screen.getByLabelText("Tipo de evento"), {
      target: { value: "job_completed" },
    });
    fireEvent.change(screen.getByLabelText("Lote"), {
      target: { value: "job-1" },
    });

    rerender(<AuditPanel tenantId="default" currentJobId="job-2" />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir histórico" }));

    await waitFor(() => {
      expect((screen.getByLabelText("Tipo de evento") as HTMLSelectElement).value).toBe("all");
    });
    expect((screen.getByLabelText("Lote") as HTMLInputElement).value).toBe("");
  });

  it("shows a clear empty state when the tenant has no audit events yet", async () => {
    listAuditEventsMock.mockResolvedValue([]);

    render(<AuditPanel tenantId="default" currentJobId="job-55" />);
    fireEvent.click(screen.getByRole("button", { name: "Abrir histórico" }));

    expect(await screen.findByText("Ainda não há eventos registrados")).toBeDefined();
    expect(
      screen.getByText("A empresa default ainda não registrou eventos para o lote aberto."),
    ).toBeDefined();
  });
});
