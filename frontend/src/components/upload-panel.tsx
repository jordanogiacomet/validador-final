import type { FormEvent } from "react";

import { getValidationScopeLabel } from "@/lib/presentation";
import type { TenantListItem, ValidationScope } from "@/lib/types";

interface UploadPanelProps {
  tenants: TenantListItem[];
  selectedTenantId: string;
  validationScope: ValidationScope;
  selectedFileName: string | null;
  isSubmitting: boolean;
  isTenantLoading: boolean;
  tenantError: string | null;
  onTenantChange: (tenantId: string) => void;
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
  onTenantChange,
  onValidationScopeChange,
  onFileChange,
  onSubmit,
}: UploadPanelProps) {
  return (
    <section className="panel control-card">
      <div className="panel-kicker">Entrada do lote</div>
      <h2 className="panel-title">Novo processamento</h2>

      <form className="form-grid" onSubmit={onSubmit}>
        <div className="field">
          <label htmlFor="tenant">Organização</label>
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
          {tenantError ? <p className="inline-error">{tenantError}</p> : null}
        </div>

        <div className="field">
          <label htmlFor="file">Planilha CSV</label>
          <div className="file-picker">
            <div className="file-picker-top">
              <label className="file-trigger" htmlFor="file">
                Selecionar arquivo
              </label>
              <span className="panel-kicker panel-kicker-inline">CSV</span>
            </div>
            <input
              id="file"
              className="file-input"
              name="file"
              type="file"
              accept=".csv,text/csv"
              onChange={(event) => onFileChange(event.target.files?.[0] ?? null)}
            />
            <span className="file-name">{selectedFileName || "Nenhum arquivo selecionado."}</span>
            <div className="file-help">CSV com cabeçalho na primeira linha.</div>
          </div>
        </div>

        <div className="field">
          <label>Escopo da análise</label>
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
                    ? "Valida apenas itens novos."
                    : scope === "duplicate_items"
                      ? "Valida apenas itens repetidos."
                      : "Valida todas as linhas do CSV."}
                </span>
              </label>
            ))}
          </div>
        </div>

        <button className="cta" type="submit" disabled={isSubmitting}>
          {isSubmitting ? "Processando lote..." : "Processar lote"}
        </button>
      </form>
    </section>
  );
}
