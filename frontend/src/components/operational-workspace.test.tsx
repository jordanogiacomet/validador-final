import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, listTenants, validateFile } from "@/lib/api";

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

vi.mock("@/lib/api", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api")>("@/lib/api");
  return {
    ...actual,
    listTenants: vi.fn(),
    validateFile: vi.fn(),
  };
});

const listTenantsMock = vi.mocked(listTenants);
const validateFileMock = vi.mocked(validateFile);

describe("OperationalWorkspace upload preflight", () => {
  beforeEach(() => {
    listTenantsMock.mockReset();
    validateFileMock.mockReset();

    listTenantsMock.mockResolvedValue([
      {
        tenant_id: "default",
        display_name: "Default Tenant",
        is_default: true,
      },
    ]);
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
});
