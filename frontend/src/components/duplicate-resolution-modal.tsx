"use client";

import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";

import {
  formatFieldName,
  hasDuplicateDescriptionConflict,
  lineNumber,
} from "@/lib/presentation";
import { resolveRowPhotoSources } from "@/lib/row-media";
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

function stopCardInteraction(event: {
  preventDefault: () => void;
  stopPropagation: () => void;
}) {
  event.preventDefault();
  event.stopPropagation();
}

function clampPhotoIndex(index: number, total: number): number {
  if (total <= 0) {
    return 0;
  }

  return Math.min(Math.max(index, 0), total - 1);
}

function buildPhotoAltText(rowLabel: string, photoIndex: number, totalPhotos: number): string {
  return totalPhotos > 1
    ? `${rowLabel} · foto ${photoIndex + 1} de ${totalPhotos}`
    : `${rowLabel} · foto`;
}

function DuplicatePhotoEmptyState() {
  return (
    <div className="duplicate-photo-frame duplicate-photo-empty">
      <span>Sem foto</span>
    </div>
  );
}

interface DuplicatePhotoLightboxProps {
  activeIndex: number;
  onClose: () => void;
  onNavigate: (nextIndex: number) => void;
  onPhotoError: (photoSource: string) => void;
  photoSources: string[];
  rowLabel: string;
}

function DuplicatePhotoLightbox({
  activeIndex,
  onClose,
  onNavigate,
  onPhotoError,
  photoSources,
  rowLabel,
}: DuplicatePhotoLightboxProps) {
  const activePhotoSource = photoSources[activeIndex];

  if (!activePhotoSource || typeof document === "undefined") {
    return null;
  }

  return createPortal(
    <div className="modal-shell photo-lightbox-shell" role="presentation" onClick={onClose}>
      <div
        className="photo-lightbox-card"
        role="dialog"
        aria-modal="true"
        aria-label={`Visualização ampliada de ${rowLabel}`}
        onClick={(event) => event.stopPropagation()}
      >
        <div className="photo-lightbox-head">
          <div>
            <strong>{rowLabel}</strong>
            <span>
              {photoSources.length > 1
                ? `Foto ${activeIndex + 1} de ${photoSources.length}`
                : "Foto ampliada"}
            </span>
          </div>

          <button className="photo-lightbox-close" type="button" onClick={onClose}>
            Fechar
          </button>
        </div>

        <div className="photo-lightbox-frame">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img
            alt={buildPhotoAltText(rowLabel, activeIndex, photoSources.length)}
            loading="eager"
            referrerPolicy="no-referrer"
            src={activePhotoSource}
            onError={() => onPhotoError(activePhotoSource)}
          />
        </div>

        {photoSources.length > 1 ? (
          <div className="photo-lightbox-actions">
            <button
              className="photo-lightbox-nav"
              type="button"
              disabled={activeIndex === 0}
              onClick={() => onNavigate(activeIndex - 1)}
            >
              Anterior
            </button>

            <span className="photo-lightbox-counter">
              {activeIndex + 1} / {photoSources.length}
            </span>

            <button
              className="photo-lightbox-nav"
              type="button"
              disabled={activeIndex === photoSources.length - 1}
              onClick={() => onNavigate(activeIndex + 1)}
            >
              Próxima
            </button>
          </div>
        ) : null}
      </div>
    </div>,
    document.body,
  );
}

function DuplicatePhotoGallery({
  photoSources,
  rowLabel,
}: {
  photoSources: string[];
  rowLabel: string;
}) {
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const slideRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [failedPhotoSources, setFailedPhotoSources] = useState<string[]>([]);
  const [currentPhotoIndex, setCurrentPhotoIndex] = useState(0);
  const [lightboxPhotoIndex, setLightboxPhotoIndex] = useState<number | null>(null);

  const renderablePhotoSources = photoSources.filter(
    (photoSource) => !failedPhotoSources.includes(photoSource),
  );

  useEffect(() => {
    if (renderablePhotoSources.length === 0) {
      setCurrentPhotoIndex(0);
      setLightboxPhotoIndex(null);
      return;
    }

    if (currentPhotoIndex >= renderablePhotoSources.length) {
      setCurrentPhotoIndex(renderablePhotoSources.length - 1);
    }

    if (lightboxPhotoIndex !== null && lightboxPhotoIndex >= renderablePhotoSources.length) {
      setLightboxPhotoIndex(renderablePhotoSources.length - 1);
    }
  }, [currentPhotoIndex, lightboxPhotoIndex, renderablePhotoSources.length]);

  useEffect(() => {
    if (lightboxPhotoIndex === null) {
      return;
    }

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setLightboxPhotoIndex(null);
        return;
      }

      if (event.key === "ArrowLeft") {
        event.preventDefault();
        setLightboxPhotoIndex((activeIndex) =>
          activeIndex === null ? null : clampPhotoIndex(activeIndex - 1, renderablePhotoSources.length),
        );
        return;
      }

      if (event.key === "ArrowRight") {
        event.preventDefault();
        setLightboxPhotoIndex((activeIndex) =>
          activeIndex === null ? null : clampPhotoIndex(activeIndex + 1, renderablePhotoSources.length),
        );
      }
    };

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    window.addEventListener("keydown", handleKeyDown);
    return () => {
      document.body.style.overflow = previousOverflow;
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [lightboxPhotoIndex, renderablePhotoSources.length]);

  function markPhotoAsFailed(photoSource: string) {
    setFailedPhotoSources((currentSources) =>
      currentSources.includes(photoSource) ? currentSources : [...currentSources, photoSource],
    );
  }

  function scrollToPhoto(nextIndex: number) {
    const clampedIndex = clampPhotoIndex(nextIndex, renderablePhotoSources.length);
    setCurrentPhotoIndex(clampedIndex);
    slideRefs.current[clampedIndex]?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
      inline: "nearest",
    });
  }

  function handleGalleryScroll() {
    const scroller = scrollerRef.current;
    if (!scroller || scroller.clientWidth === 0) {
      return;
    }

    const nextIndex = clampPhotoIndex(
      Math.round(scroller.scrollLeft / scroller.clientWidth),
      renderablePhotoSources.length,
    );
    if (nextIndex !== currentPhotoIndex) {
      setCurrentPhotoIndex(nextIndex);
    }
  }

  if (renderablePhotoSources.length === 0) {
    return (
      <div className="duplicate-photo-gallery-shell">
        <DuplicatePhotoEmptyState />
      </div>
    );
  }

  return (
    <>
      <div className="duplicate-photo-gallery-shell" onClick={stopCardInteraction}>
        <div className="duplicate-photo-frame">
          {renderablePhotoSources.length > 1 ? (
            <div
              ref={scrollerRef}
              className="duplicate-photo-scroller"
              role="group"
              aria-label={`Galeria de fotos de ${rowLabel}`}
              onScroll={handleGalleryScroll}
            >
              {renderablePhotoSources.map((photoSource, photoIndex) => (
                <button
                  key={photoSource}
                  ref={(element) => {
                    slideRefs.current[photoIndex] = element;
                  }}
                  className="duplicate-photo-slide"
                  type="button"
                  title="Abrir foto ampliada"
                  onClick={(event) => {
                    stopCardInteraction(event);
                    setLightboxPhotoIndex(photoIndex);
                  }}
                >
                  {/* eslint-disable-next-line @next/next/no-img-element */}
                  <img
                    alt={buildPhotoAltText(rowLabel, photoIndex, renderablePhotoSources.length)}
                    loading="lazy"
                    referrerPolicy="no-referrer"
                    src={photoSource}
                    onError={() => markPhotoAsFailed(photoSource)}
                  />
                </button>
              ))}
            </div>
          ) : (
            <button
              className="duplicate-photo-slide duplicate-photo-single"
              type="button"
              title="Abrir foto ampliada"
              onClick={(event) => {
                stopCardInteraction(event);
                setLightboxPhotoIndex(0);
              }}
            >
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img
                alt={buildPhotoAltText(rowLabel, 0, 1)}
                loading="lazy"
                referrerPolicy="no-referrer"
                src={renderablePhotoSources[0]}
                onError={() => markPhotoAsFailed(renderablePhotoSources[0])}
              />
            </button>
          )}
        </div>

        {renderablePhotoSources.length > 1 ? (
          <div className="duplicate-photo-controls">
            <span className="duplicate-photo-counter">
              {currentPhotoIndex + 1} / {renderablePhotoSources.length}
            </span>

            <div className="duplicate-photo-control-group">
              <button
                className="duplicate-photo-control-button"
                type="button"
                disabled={currentPhotoIndex === 0}
                onClick={(event) => {
                  stopCardInteraction(event);
                  scrollToPhoto(currentPhotoIndex - 1);
                }}
              >
                Anterior
              </button>

              <button
                className="duplicate-photo-control-button"
                type="button"
                disabled={currentPhotoIndex === renderablePhotoSources.length - 1}
                onClick={(event) => {
                  stopCardInteraction(event);
                  scrollToPhoto(currentPhotoIndex + 1);
                }}
              >
                Próxima
              </button>
            </div>
          </div>
        ) : null}
      </div>

      {lightboxPhotoIndex !== null ? (
        <DuplicatePhotoLightbox
          activeIndex={lightboxPhotoIndex}
          photoSources={renderablePhotoSources}
          rowLabel={rowLabel}
          onClose={() => setLightboxPhotoIndex(null)}
          onNavigate={(nextIndex) => setLightboxPhotoIndex(clampPhotoIndex(nextIndex, renderablePhotoSources.length))}
          onPhotoError={markPhotoAsFailed}
        />
      ) : null}
    </>
  );
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

  const hasDescriptionConflict = hasDuplicateDescriptionConflict(state.duplicate);
  const modalTitle = hasDescriptionConflict
    ? `Resolver duplicidade do item ${state.duplicate.item || "sem identificação"}`
    : `Consolidar ocorrências do item ${state.duplicate.item || "sem identificação"}`;
  const modalCopy = hasDescriptionConflict
    ? "A linha de maior numeração continua como base técnica do CSV corrigido. Campos vazios ainda podem receber dados das ocorrências anteriores."
    : "Os dados úteis das ocorrências serão consolidados. Foto, mídia e colunas de data/hora ficam fora da mescla. A linha física mantida no CSV é só um detalhe técnico.";

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
          {modalTitle}
        </h2>
        <p className="panel-copy">{modalCopy}</p>

        <div className="duplicate-resolution-list">
          {state.rows.map(({ rowIndex, rowPayload }) => {
            const descricao = getCanonicalFieldValue(rowPayload, "descricao") || "Não informado";
            const placa = getCanonicalFieldValue(rowPayload, "placa_anterior") || "Sem placa anterior";
            const marca = getCanonicalFieldValue(rowPayload, "marca") || "Não informado";
            const modelo = getCanonicalFieldValue(rowPayload, "modelo") || "Não informado";
            const ns = getCanonicalFieldValue(rowPayload, "ns") || "Não informado";
            const complemento =
              getCanonicalFieldValue(rowPayload, "complemento") || "Não informado";
            const photoSources = resolveRowPhotoSources(rowPayload);
            const isSuggested = state.suggestedKeepRowIndex === rowIndex;
            const rowLabel = `Linha ${lineNumber(rowIndex)}`;

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
                        <span className="duplicate-resolution-badge">Base técnica do CSV</span>
                      ) : null}
                    </div>
                    <div className="duplicate-resolution-note">
                      Item {state.duplicate.item || "-"} | {descricao}
                    </div>
                  </div>
                </div>

                <div className="duplicate-resolution-body">
                  <DuplicatePhotoGallery photoSources={photoSources} rowLabel={rowLabel} />

                  <div className="duplicate-resolution-meta">
                    {[
                      ["Placa Anterior", placa],
                      ["Marca", marca],
                      ["Modelo", modelo],
                      ["NS", ns],
                      [formatFieldName("complemento"), complemento],
                    ].map(([label, value]) => (
                      <div
                        key={`${rowIndex}-${label}`}
                        className={label === "Complemento" ? "duplicate-span-full" : undefined}
                      >
                        <small>{label}</small>
                        <span>{value}</span>
                      </div>
                    ))}
                  </div>
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
            {isSaving ? "Atualizando..." : "Aplicar consolidação"}
          </button>
        </div>
      </div>
    </div>
  );
}
