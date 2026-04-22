import React from "react";
import type { FormEvent } from "react";

import { getValidationScopeLabel } from "@/lib/presentation";
import type {
  TenantListItem,
  UploadPreflightPayload,
  ValidationScope,
} from "@/lib/types";

interface UploadPanelProps {
  tenants: TenantListItem[];
  selectedTenantId: string;
  validationScope: ValidationScope;
  selectedFileName: string | null;
  isSubmitting: boolean;
  isTenantLoading: boolean;
  tenantError: string | null;
  uploadPreflight: UploadPreflightPayload | null;
  onTenantChange: (tenantId: string) => void;
  onTemplateDownload: () => void;
  onValidationScopeChange: (scope: ValidationScope) => void;
  onFileChange: (file: File | null) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

export function UploadPanel({
  tenants,
  selectedTenantId,
  validationScope,
  selectedFileName,
  isSubmitting,
  isTenantLoading,
  tenantError,
  uploadPreflight,
  onTenantChange,
  onTemplateDownload,
  onValidationScopeChange,
  onFileChange,
  onSubmit,
}: UploadPanelProps) {
  const hasMultipleTenants = tenants.length > 1;
  const selectedTenant = tenants.find((tenant) => tenant.tenant_id === selectedTenantId);

  return (
    <section className="panel control-card">
      <div className="panel-kicker">1. Enviar planilha</div>
      <h2 className="panel-title">Começar nova conferência</h2>
      <p className="panel-copy">
        Confirme a empresa da sessão, selecione um CSV ou XLSX e diga o que deseja conferir. O restante acontece automaticamente.
      </p>

      <form className="form-grid" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="tenant">Empresa</label>
          {hasMultipleTenants ? (
            <select
              id="tenant"
              name="tenant_id"
              value={selectedTenantId}
              disabled={isTenantLoading}
              onChange={(event) => onTenantChange(event.target.value)}
            >
              {tenants.map((tenant) => (
                <option key={tenant.tenant_id} value={tenant.tenant_id}>
                  {tenant.display_name} ({tenant.tenant_id})
                </option>
              ))}
            </select>
          ) : (
            <div className="tenant-context" id="tenant">
              <strong>{selectedTenant?.display_name || selectedTenantId}</strong>
              <span>{selectedTenantId}</span>
            </div>
          )}
          {tenantError ? <p className="inline-error">{tenantError}</p> : null}
        </div>

        <div className="field">
          <label htmlFor="file">Planilha CSV ou XLSX</label>
          <div className="file-picker">
            <div className="file-picker-top">
              <label className="file-trigger" htmlFor="file">
                Selecionar arquivo
              </label>
              <button
                className="file-trigger"
                type="button"
                disabled={isSubmitting || isTenantLoading}
                onClick={onTemplateDownload}
              >
                Baixar modelo XLSX
              </button>
              <span className="panel-kicker panel-kicker-inline">CSV ou XLSX</span>
            </div>
            <input
              id="file"
              className="file-input"
              name="file"
              type="file"
              accept=".csv,.xlsx,text/csv,application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
              onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
            />
            <span className="file-name">{selectedFileName || "Nenhum arquivo selecionado."}</span>
            <div className="file-help">
              XLSX pode ser enviado diretamente. CSV precisa manter o cabecalho na primeira
              linha.
            </div>
            <div className="file-help">
              Use o modelo de {selectedTenant?.display_name || selectedTenantId} para manter as
              colunas esperadas e, se salvar em CSV, preservar o layout da empresa.
            </div>
            {uploadPreflight ? (
              <div aria-live="polite" role="alert">
                {uploadPreflight.issues.map((issue) => (
                  <p className="inline-error" key={issue.code}>
                    {issue.message}
                  </p>
                ))}
                <div className="file-help">
                  Colunas encontradas:{" "}
                  {uploadPreflight.detected_columns.length
                    ? uploadPreflight.detected_columns.join(", ")
                    : "nenhuma compativel."}
                </div>
                {uploadPreflight.missing_columns.length ? (
                  <div className="file-help">
                    Colunas faltantes: {uploadPreflight.missing_columns.join(", ")}
                  </div>
                ) : null}
                {uploadPreflight.guidance.map((item, index) => (
                  <div className="file-help" key={`${index}-${item}`}>
                    {item}
                  </div>
                ))}
              </div>
            ) : null}
          </div>
        </div>

        <div className="field">
          <label>O que deseja conferir?</label>
          <div className="scope-options">
            {(["zero_items", "duplicate_items", "all_items"] as ValidationScope[]).map((scope) => (
              <label className="scope-option" key={scope}>
                <div className="scope-option-head">
                  <input
                    checked={validationScope === scope}
                    name="validation_scope"
                    type="radio"
                    value={scope}
                    onChange={() => onValidationScopeChange(scope)}
                  />
                  <strong>{getValidationScopeLabel(scope)}</strong>
                </div>
                <span>
                  {scope === "zero_items"
                    ? "Conferir somente bens cadastrados do zero."
                    : scope === "duplicate_items"
                      ? "Conferir somente itens repetidos."
                      : "Conferir todas as linhas da planilha."}
                </span>
              </label>
            ))}
          </div>
        </div>

        <button className="cta" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Iniciando conferência..." : "Iniciar conferência"}
        </button>
      </form>
    </section>
  );
}
