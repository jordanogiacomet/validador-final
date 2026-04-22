import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { JobStatusResponse, ValidationScope } from "@/lib/types";

import { ProcessCard } from "./process-card";

function renderCard(job: JobStatusResponse | null, validationScope: ValidationScope = "zero_items") {
  return render(
    <ProcessCard
      job={job}
      organizationLabel="Empresa padrão"
      fallbackFileName={job?.file_name ?? null}
      validationScope={validationScope}
    />,
  );
}

function buildJob(overrides: Partial<JobStatusResponse> = {}): JobStatusResponse {
  return {
    job_id: "job-1",
    tenant_id: "default",
    validation_scope: "zero_items",
    status: "completed",
    total_rows: 2,
    source_total_rows: 2,
    rows_with_issues: 1,
    total_issues: 1,
    processed_rows: 2,
    batch_size: 2,
    error_message: null,
    partial_summary: {},
    is_partial_result_available: false,
    partial_grouped_problems: {},
    partial_duplicates: [],
    row_results_preview: [],
    current_step: "report_ready",
    status_title: "Relatório pronto",
    status_detail: "Tudo carregado.",
    created_at: null,
    updated_at: "2026-04-18T12:00:00Z",
    file_name: "inventario.csv",
    cancel_requested: false,
    parent_job_id: null,
    latest_retry_job_id: null,
    ...overrides,
  };
}

describe("ProcessCard", () => {
  it("shows a clear starting instruction before any upload", () => {
    renderCard(null);

    expect(screen.getByText("Envie uma planilha para começar")).toBeDefined();
    expect(
      screen.getByText("Escolha a empresa, selecione o CSV e clique em Iniciar conferência."),
    ).toBeDefined();
  });

  it("shows the next operator action after a completed lot with issues", () => {
    renderCard(buildJob());

    expect(screen.getByText("Revise as pendências encontradas")).toBeDefined();
    expect(
      screen.getByText(
        "Use a lista abaixo para corrigir o que for necessário e depois baixar os arquivos.",
      ),
    ).toBeDefined();
  });

  it("shows ETA copy for a running lot when progress is already measurable", () => {
    renderCard(
      buildJob({
        status: "running",
        current_step: "validating_batches",
        status_title: "Validação",
        status_detail: "Processando.",
        total_rows: 100,
        source_total_rows: 100,
        processed_rows: 40,
        created_at: "2026-04-18T12:00:00Z",
        updated_at: "2026-04-18T12:02:00Z",
      }),
    );

    expect(screen.getByText(/ETA aproximado: 3 min/)).toBeDefined();
  });
});
