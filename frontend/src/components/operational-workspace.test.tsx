import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, listTenants, previewValidationScope, validateFile } from "@/lib/api";

import { OperationalWorkspace } from "./operational-workspace";

vi.mock("@/hooks/use-active-jobs", () => ({
  useActiveJobs: () => ({
    jobs: [],
    isLoading: false,
    error: null,
    refreshJobs: vi.fn().mockResolvedValue(undefined),
  }),
}));

vi.mock("@/hooks/use-job-polling", () => ({
  useJobPolling: () => undefined,
}));

vi.mock("@/components/active-jobs-panel", () => ({
  ActiveJobsPanel: () => <div data-testid="active-jobs-panel" />,
}));

vi.mock("@/components/process-card", () => ({
  ProcessCard: () => <div data-testid="process-card" />,
}));

vi.mock("@/components/result-workspace", () => ({
  ResultWorkspace: () => null,
}));

vi.mock("@/components/audit-panel", () => ({
  AuditPanel: () => null,
}));

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    ApiError: actual.ApiError,
    listTenants: vi.fn(),
    previewValidationScope: vi.fn(),
    validateFile: vi.fn(),
  };
});

const listTenantsMock = vi.mocked(listTenants);
const previewValidationScopeMock = vi.mocked(previewValidationScope);
const validateFileMock = vi.mocked(validateFile);

describe("OperationalWorkspace upload preflight", () => {
  beforeEach(() => {
    listTenantsMock.mockReset();
    previewValidationScopeMock.mockReset();
    validateFileMock.mockReset();

    listTenantsMock.mockResolvedValue([
      {
        tenant_id: "default",
        display_name: "Default Tenant",
        is_default: true,
      },
    ]);
    previewValidationScopeMock.mockResolvedValue({
      source_total_rows: 3,
      duplicate_group_count: 1,
      scopes: [
        {
          validation_scope: "zero_items",
          estimated_rows_in_scope: 1,
          estimated_rows_out_of_scope: 2,
          category_counts: [],
        },
        {
          validation_scope: "duplicate_items",
          estimated_rows_in_scope: 2,
          estimated_rows_out_of_scope: 1,
          category_counts: [],
        },
        {
          validation_scope: "all_items",
          estimated_rows_in_scope: 3,
          estimated_rows_out_of_scope: 0,
          category_counts: [],
        },
      ],
    });
  });

  it("renders inline preflight guidance when the upload is rejected before job creation", async () => {
    validateFileMock.mockRejectedValue(
      new ApiError(
        "Nao foi possivel ler o CSV. Revise o arquivo, delimitador, codificacao e cabecalho.",
        400,
        {
          detail: "O delimitador do CSV nao corresponde ao layout esperado para esta empresa.",
          payload: {
            detail: "O delimitador do CSV nao corresponde ao layout esperado para esta empresa.",
            preflight: {
              file_name: "lote.csv",
              file_size_bytes: 128,
              detected_columns: ["Item", "Descricao", "Marca"],
              missing_columns: [],
              guidance: [
                "Exporte o arquivo novamente usando o delimitador ','.",
                "O arquivo atual parece usar o delimitador ';'.",
              ],
              issues: [
                {
                  code: "delimiter_mismatch",
                  message:
                    "Cabecalho encontrado, mas com separador diferente do configurado.",
                },
              ],
            },
          },
        },
      ),
    );

    render(<OperationalWorkspace initialTenantId="default" />);

    const fileInput = await screen.findByLabelText("Planilha CSV ou XLSX");
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["Item;Descricao\n001;Mesa\n"], "lote.csv", { type: "text/csv" })],
      },
    });

    fireEvent.click(screen.getByRole("button", { name: "Iniciar conferência" }));

    await waitFor(() => {
      expect(previewValidationScopeMock).toHaveBeenCalledWith({
        file: expect.any(File),
        tenantId: "default",
      });
      expect(validateFileMock).toHaveBeenCalledWith({
        file: expect.any(File),
        tenantId: "default",
        validationScope: "zero_items",
      });
    });

    expect(
      await screen.findByText(
        "Cabecalho encontrado, mas com separador diferente do configurado.",
      ),
    ).toBeDefined();
    expect(screen.getByText("Colunas encontradas: Item, Descricao, Marca")).toBeDefined();
    expect(
      screen.getByText("Exporte o arquivo novamente usando o delimitador ','."),
    ).toBeDefined();
    expect(
      screen.getByText("O arquivo atual parece usar o delimitador ';'."),
    ).toBeDefined();
    expect(screen.getByRole("button", { name: "Iniciar conferência" })).toBeDefined();
  });

  it("updates the selected scope preview locally after the file preview is loaded", async () => {
    render(<OperationalWorkspace initialTenantId="default" />);

    const fileInput = await screen.findByLabelText("Planilha CSV ou XLSX");
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["Item,Descricao\n001,Mesa\n"], "lote.csv", { type: "text/csv" })],
      },
    });

    expect(
      await screen.findByText(
        "1 de 3 linha(s) entrarão porque estão cadastradas do zero.",
      ),
    ).toBeDefined();
    expect(previewValidationScopeMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByRole("radio", { name: /Somente duplicados/i }));

    expect(
      await screen.findByText(
        "2 de 3 linha(s) entrarão porque pertencem a 1 grupo(s) com Item repetido.",
      ),
    ).toBeDefined();
    expect(previewValidationScopeMock).toHaveBeenCalledTimes(1);
  });

  it("reloads the preview when the tenant changes", async () => {
    listTenantsMock.mockResolvedValue([
      {
        tenant_id: "default",
        display_name: "Default Tenant",
        is_default: true,
      },
      {
        tenant_id: "empresa_exemplo",
        display_name: "Empresa Exemplo",
        is_default: false,
      },
    ]);
    previewValidationScopeMock
      .mockResolvedValueOnce({
        source_total_rows: 3,
        duplicate_group_count: 1,
        scopes: [
          {
            validation_scope: "zero_items",
            estimated_rows_in_scope: 1,
            estimated_rows_out_of_scope: 2,
            category_counts: [],
          },
          {
            validation_scope: "duplicate_items",
            estimated_rows_in_scope: 2,
            estimated_rows_out_of_scope: 1,
            category_counts: [],
          },
          {
            validation_scope: "all_items",
            estimated_rows_in_scope: 3,
            estimated_rows_out_of_scope: 0,
            category_counts: [],
          },
        ],
      })
      .mockResolvedValueOnce({
        source_total_rows: 2,
        duplicate_group_count: 0,
        scopes: [
          {
            validation_scope: "zero_items",
            estimated_rows_in_scope: 2,
            estimated_rows_out_of_scope: 0,
            category_counts: [{ category: "tv", label: "TV", row_count: 2 }],
          },
          {
            validation_scope: "duplicate_items",
            estimated_rows_in_scope: 0,
            estimated_rows_out_of_scope: 2,
            category_counts: [],
          },
          {
            validation_scope: "all_items",
            estimated_rows_in_scope: 2,
            estimated_rows_out_of_scope: 0,
            category_counts: [{ category: "tv", label: "TV", row_count: 2 }],
          },
        ],
      });

    render(<OperationalWorkspace initialTenantId="default" />);

    const fileInput = await screen.findByLabelText("Planilha CSV ou XLSX");
    fireEvent.change(fileInput, {
      target: {
        files: [new File(["Item,Descricao\n001,Mesa\n"], "lote.csv", { type: "text/csv" })],
      },
    });

    await screen.findByText("1 de 3 linha(s) entrarão porque estão cadastradas do zero.");

    fireEvent.change(screen.getByLabelText("Empresa"), {
      target: { value: "empresa_exemplo" },
    });

    expect(
      await screen.findByText("2 de 2 linha(s) entrarão porque estão cadastradas do zero."),
    ).toBeDefined();
    expect(screen.getByText("TV: 2")).toBeDefined();
    expect(previewValidationScopeMock).toHaveBeenNthCalledWith(2, {
      file: expect.any(File),
      tenantId: "empresa_exemplo",
    });
  });
});
