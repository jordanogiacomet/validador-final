import { formatFieldName, lineNumber } from "@/lib/presentation";
import type { DuplicateModalState } from "@/lib/types";

interface DuplicateResolutionModalProps {
  state: DuplicateModalState | null;
  selectedKeepRowIndex: number | null;
  isSaving: boolean;
  onClose: () => void;
  onSelectKeepRow: (rowIndex: number) => void;
  onSave: () => void;
}

function getCanonicalFieldValue(
  rowPayload: DuplicateModalState["rows"][number]["rowPayload"],
  field: string,
): string {
  const sourceColumn = rowPayload.resolved_columns[field] || field;
  return rowPayload.row[sourceColumn] || "";
}

export function DuplicateResolutionModal({
  state,
  selectedKeepRowIndex,
  isSaving,
  onClose,
  onSelectKeepRow,
  onSave,
}: DuplicateResolutionModalProps) {
  if (!state) {
    return null;
  }

  return (
    <div className="modal-shell" role="presentation" onClick={onClose}>
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="duplicate-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="panel-kicker">Resolução de duplicidade</div>
        <h2 id="duplicate-modal-title" className="panel-title">
          Manter maior linha do item {state.duplicate.item || "sem identificação"}
        </h2>
        <p className="panel-copy">
          A linha de maior numeração será mantida. Campos vazios recebem dados das linhas anteriores.
        </p>

        <div className="duplicate-resolution-list">
          {state.rows.map(({ rowIndex, rowPayload }) => {
            const descricao = getCanonicalFieldValue(rowPayload, "descricao") || "Não informado";
            const placa = getCanonicalFieldValue(rowPayload, "placa_anterior") || "Sem placa anterior";
            const marca = getCanonicalFieldValue(rowPayload, "marca") || "Não informado";
            const modelo = getCanonicalFieldValue(rowPayload, "modelo") || "Não informado";
            const ns = getCanonicalFieldValue(rowPayload, "ns") || "Não informado";
            const complemento =
              getCanonicalFieldValue(rowPayload, "complemento") || "Não informado";
            const isSuggested = state.suggestedKeepRowIndex === rowIndex;

            return (
              <label className="duplicate-resolution-option" htmlFor={`duplicate-keep-${rowIndex}`} key={rowIndex}>
                <div className="duplicate-resolution-option-head">
                  <input
                    checked={selectedKeepRowIndex === rowIndex}
                    id={`duplicate-keep-${rowIndex}`}
                    name="duplicate_keep_row"
                    type="radio"
                    value={rowIndex}
                    disabled={!isSuggested || isSaving}
                    onChange={() => onSelectKeepRow(rowIndex)}
                  />

                  <div>
                    <div className="duplicate-resolution-title">
                      <strong>Linha {lineNumber(rowIndex)}</strong>
                      {isSuggested ? (
                        <span className="duplicate-resolution-badge">Linha mantida</span>
                      ) : null}
                    </div>
                    <div className="duplicate-resolution-note">
                      Item {state.duplicate.item || "-"} | {descricao}
                    </div>
                  </div>
                </div>

                <div className="duplicate-resolution-meta">
                  {[
                    ["Placa Anterior", placa],
                    ["Marca", marca],
                    ["Modelo", modelo],
                    ["NS", ns],
                    [formatFieldName("complemento"), complemento],
                  ].map(([label, value]) => (
                    <div key={`${rowIndex}-${label}`} className={label === "Complemento" ? "duplicate-span-full" : undefined}>
                      <small>{label}</small>
                      <span>{value}</span>
                    </div>
                  ))}
                </div>
              </label>
            );
          })}
        </div>

        <div className="modal-actions">
          <button className="action-button" type="button" onClick={onClose}>
            Cancelar
          </button>
          <button className="action-button primary" type="button" disabled={isSaving} onClick={onSave}>
            {isSaving ? "Atualizando..." : "Manter maior linha"}
          </button>
        </div>
      </div>
    </div>
  );
}
