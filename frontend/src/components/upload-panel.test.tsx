import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { UploadPanel } from "./upload-panel";

describe("UploadPanel", () => {
  it("communicates CSV/XLSX support and exposes the tenant template action", () => {
    const handleTemplateDownload = vi.fn();

    render(
      <UploadPanel
        tenants={[
          {
            tenant_id: "default",
            display_name: "Default Tenant",
            is_default: true,
          },
        ]}
        selectedTenantId="default"
        validationScope="zero_items"
        selectedFileName={null}
        isSubmitting={false}
        isTenantLoading={false}
        tenantError={null}
        uploadPreflight={null}
        onTenantChange={vi.fn()}
        onTemplateDownload={handleTemplateDownload}
        onValidationScopeChange={vi.fn()}
        onFileChange={vi.fn()}
        onSubmit={(event) => event.preventDefault()}
      />,
    );

    expect(screen.getByLabelText("Planilha CSV ou XLSX").getAttribute("accept")).toBe(
      ".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    );
    expect(
      screen.getByText(
        "XLSX pode ser enviado diretamente. CSV precisa manter o cabecalho na primeira linha.",
      ),
    ).toBeDefined();
    expect(
      screen.getByText(
        "Use o modelo de Default Tenant para manter as colunas esperadas e, se salvar em CSV, preservar o layout da empresa.",
      ),
    ).toBeDefined();

    fireEvent.click(screen.getByRole("button", { name: "Baixar modelo XLSX" }));

    expect(handleTemplateDownload).toHaveBeenCalledTimes(1);
  });
});
