import type { EditModalState } from "@/lib/types";

interface EditRowModalProps {
  state: EditModalState | null;
  newValue: string;
  isLoading: boolean;
  isSaving: boolean;
  onNewValueChange: (value: string) => void;
  onClose: () => void;
  onSave: () => void;
}

export function EditRowModal({
  state,
  newValue,
  isLoading,
  isSaving,
  onNewValueChange,
  onClose,
  onSave,
}: EditRowModalProps) {
  if (!state) {
    return null;
  }

  return (
    <div className="modal-shell" role="presentation" onClick={onClose}>
      <div
        className="modal-card"
        role="dialog"
        aria-modal="true"
        aria-labelledby="edit-modal-title"
        onClick={(event) => event.stopPropagation()}
      >
        <div className="panel-kicker">Correção direta no CSV</div>
        <h2 id="edit-modal-title" className="panel-title">
          Editar {state.itemLabel ? `o item ${state.itemLabel}` : "campo do lote"}
        </h2>
        <p className="panel-copy">
          {isLoading
            ? "Carregando linha do CSV."
            : "Altere o valor e salve no CSV corrigido."}
        </p>

        <div className="modal-grid">
          <div className="field">
            <label htmlFor="edit-field-display">Campo operacional</label>
            <input id="edit-field-display" type="text" readOnly value={state.field} />
          </div>
          <div className="field">
            <label htmlFor="edit-source-column-display">Coluna no CSV</label>
            <input
              id="edit-source-column-display"
              type="text"
              readOnly
              value={isLoading ? "Carregando..." : state.sourceColumn}
            />
          </div>
          <div className="field">
            <label htmlFor="edit-current-value">Valor atual no arquivo</label>
            <textarea
              id="edit-current-value"
              rows={3}
              readOnly
              value={isLoading ? "Carregando valor atual do CSV..." : state.currentValue}
            />
          </div>
          <div className="field">
            <label htmlFor="edit-new-value">Novo valor</label>
            <textarea
              id="edit-new-value"
              rows={4}
              disabled={isLoading || isSaving}
              value={newValue}
              onChange={(event) => onNewValueChange(event.target.value)}
            />
          </div>
        </div>

        <div className="modal-actions">
          <button className="action-button" type="button" onClick={onClose}>
            Cancelar
          </button>
          <button
            className="action-button primary"
            type="button"
            disabled={isLoading || isSaving}
            onClick={onSave}
          >
            {isLoading ? "Carregando..." : isSaving ? "Salvando..." : "Salvar no CSV"}
          </button>
        </div>
      </div>
    </div>
  );
}
