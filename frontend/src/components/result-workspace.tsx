import React, { useEffect, useState } from "react";

import {
  downloadApiFile,
  downloadGeneratedFile,
} from "@/lib/api";
import {
  buildFilteredOperationalExportCsv,
  buildResultWorkspaceGuide,
  buildResultFilterGroups,
  buildScopeSummaryCopy,
  describeIssue,
  filterDuplicatesForResultSearch,
  filterProblemGroupsForResultView,
  formatFieldName,
  getActiveResultFilterCount,
  getBulkConsolidatableSameNameDuplicates,
  getDuplicateFilterCounts,
  getReviewFlaggedRowCount,
  getSourceTotalRows,
  getValidatedTotalRows,
  hasActiveResultFilters,
  hasResultSearchQuery,
  hasDuplicateDescriptionConflict,
  isRowMarkedForReview,
  isDuplicateItemsScope,
  isZeroItemsScope,
  lineNumber,
  resetResultFilterState,
  resetResultSearchState,
  resolveEditableField,
  slugify,
  sortProblemGroups,
  toggleResultFilter,
} from "@/lib/presentation";
import type { DuplicateDisplayFilter, ResultFilterState } from "@/lib/presentation";
import type {
  DuplicateGroup,
  JobResultPayload,
  JobStatusResponse,
  PreviewReportPayload,
  ProblemOccurrence,
  ReviewFlagActionStatus,
  SummaryPayload,
  ValidationScope,
} from "@/lib/types";

interface ResultWorkspaceProps {
  job: JobStatusResponse | null;
  currentJobId: string | null;
  validationScope: ValidationScope;
  reportData: JobResultPayload | null;
  previewData: PreviewReportPayload | null;
  hasPendingCorrections: boolean;
  visibleProblemOccurrencesByCode: Record<string, number>;
  isReprocessing: boolean;
  isResolvingBulkSameNameDuplicates: boolean;
  isSavingReviewFlag: boolean;
  onShowMore: (code: string) => void;
  onEditOccurrence: (occurrence: ProblemOccurrence) => void;
  onToggleReviewFlag: (rowIndex: number, status: ReviewFlagActionStatus) => void;
  onResolveDuplicate: (duplicate: DuplicateGroup) => void;
  onResolveBulkSameNameDuplicates: () => void;
  onReprocess: () => void;
  onOpenRelatedJob?: (jobId: string) => void;
}

function JobLineageBanner({
  job,
  onOpenRelatedJob,
}: {
  job: JobStatusResponse | null;
  onOpenRelatedJob?: (jobId: string) => void;
}) {
  const parentJobId = job?.parent_job_id ?? null;
  const latestRetryJobId = job?.latest_retry_job_id ?? null;
  if (!parentJobId && !latestRetryJobId) {
    return null;
  }

  function renderRelatedJob(label: string, jobId: string) {
    if (onOpenRelatedJob) {
      return (
        <button
          type="button"
          className="job-lineage-link"
          onClick={() => onOpenRelatedJob(jobId)}
        >
          {label} {jobId}
        </button>
      );
    }
    return (
      <span className="job-lineage-text">
        {label} {jobId}
      </span>
    );
  }

  return (
    <section className="panel job-lineage-card" aria-label="Histórico de reprocessamento">
      <div className="panel-kicker">Reprocessamento</div>
      <div className="job-lineage-row">
        {parentJobId
          ? renderRelatedJob("Lote originado de", parentJobId)
          : null}
        {latestRetryJobId
          ? renderRelatedJob("Reprocessamento mais recente:", latestRetryJobId)
          : null}
      </div>
    </section>
  );
}

const DUPLICATE_FILTER_LABELS: Record<DuplicateDisplayFilter, string> = {
  all: "Todos",
  normal: "Mesmo nome",
  conflict: "Nome diferente",
};

function ResultGuideCard({
  job,
  summary,
  isPartial,
}: {
  job: JobStatusResponse | null;
  summary: Partial<SummaryPayload>;
  isPartial: boolean;
}) {
  const guide = buildResultWorkspaceGuide({ job, summary, isPartial });

  return (
    <section className="panel result-guide-card">
      <div className="panel-kicker">3. Revise o resultado</div>
      <h2 className="panel-title">{guide.title}</h2>
      <p className="panel-copy">{guide.detail}</p>
    </section>
  );
}

function SummarySection({
  summary,
  validationScope,
  isPartial,
  processedRows,
}: {
  summary: Partial<SummaryPayload>;
  validationScope: ValidationScope;
  isPartial: boolean;
  processedRows: number;
}) {
  const validatedRows = getValidatedTotalRows(summary);
  const cleanRows = Math.max(
    (isPartial ? processedRows : validatedRows) - Number(summary.rows_with_issues ?? 0),
    0,
  );

  const cards = isPartial
    ? [
        {
          label: "Itens em escopo",
          value: validatedRows,
          copy: buildScopeSummaryCopy(summary, validationScope),
          className: "",
        },
        {
          label: "Itens já validados",
          value: processedRows,
          copy: "Prévia atual.",
          className: "",
        },
        {
          label: "Linhas com revisão",
          value: summary.rows_with_issues ?? 0,
          copy: "Registros com ajuste.",
          className: "",
        },
        {
          label: "Total de problemas",
          value: summary.total_issues ?? 0,
          copy: "Apontamentos na prévia.",
          className: "",
        },
        {
          label: "Erros",
          value: summary.error_count ?? 0,
          copy: "Corrigir primeiro.",
          className: "error",
        },
        {
          label: "Avisos",
          value: summary.warning_count ?? 0,
          copy: "Completar depois.",
          className: "warning",
        },
      ]
    : [
        {
          label: "Itens em escopo",
          value: validatedRows,
          copy: buildScopeSummaryCopy(summary, validationScope),
          className: "",
        },
        {
          label: "Linhas com revisão",
          value: summary.rows_with_issues ?? 0,
          copy: "Registros com ajuste.",
          className: "",
        },
        {
          label: "Total de problemas",
          value: summary.total_issues ?? 0,
          copy: "Apontamentos do lote.",
          className: "",
        },
        {
          label: "Erros",
          value: summary.error_count ?? 0,
          copy: "Corrigir primeiro.",
          className: "error",
        },
        {
          label: "Avisos",
          value: summary.warning_count ?? 0,
          copy: "Completar depois.",
          className: "warning",
        },
        {
          label: "Linhas sem ação",
          value: cleanRows,
          copy: "Sem apontamentos.",
          className: "success",
        },
      ];

  return (
    <section className="summary-grid">
      {cards.map((card) => (
        <article className={`summary-card ${card.className}`.trim()} key={card.label}>
          <small>{card.label}</small>
          <strong>{card.value}</strong>
          <p>{card.copy}</p>
        </article>
      ))}
    </section>
  );
}

function EmptyState({ job }: { job: JobStatusResponse | null }) {
  let title = "O lote ainda não foi processado";
  let detail = "Envie um CSV para iniciar a validação.";

  if (job?.status === "canceled") {
    title = "O lote foi cancelado";
    detail = "Envie o arquivo novamente para iniciar outro lote.";
  } else if (job?.cancel_requested) {
    title = "Encerrando o lote atual";
    detail = "Cancelamento em andamento.";
  } else if (job?.status === "failed") {
    title = "O lote falhou";
    detail = "Revise a falha e envie o arquivo novamente.";
  } else if (job && (job.status === "queued" || job.status === "running")) {
    title = "Prévia ainda indisponível";
    detail = "Aguarde a primeira prévia do processamento.";
  }

  return (
    <section className="panel empty-card">
      <div className="panel-kicker">Resultado</div>
      <h2 className="panel-title">{title}</h2>
      <p>{detail}</p>
    </section>
  );
}

export function ResultWorkspace({
  job,
  currentJobId,
  validationScope,
  reportData,
  previewData,
  hasPendingCorrections,
  visibleProblemOccurrencesByCode,
  isReprocessing,
  isResolvingBulkSameNameDuplicates,
  isSavingReviewFlag,
  onShowMore,
  onEditOccurrence,
  onToggleReviewFlag,
  onResolveDuplicate,
  onResolveBulkSameNameDuplicates,
  onReprocess,
  onOpenRelatedJob,
}: ResultWorkspaceProps) {
  const [duplicateFilter, setDuplicateFilter] = useState<DuplicateDisplayFilter>("all");
  const [showReviewOnly, setShowReviewOnly] = useState(false);
  const [resultFilters, setResultFilters] = useState<ResultFilterState>(() =>
    resetResultFilterState(),
  );
  const [searchInput, setSearchInput] = useState("");
  const [debouncedSearchQuery, setDebouncedSearchQuery] = useState("");
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const activeData = previewData || reportData;
  const isPartial = Boolean(previewData);

  useEffect(() => {
    const resetSearch = resetResultSearchState(currentJobId);
    setDuplicateFilter("all");
    setShowReviewOnly(false);
    setResultFilters(resetResultFilterState());
    setSearchInput(resetSearch.input);
    setDebouncedSearchQuery(resetSearch.debouncedQuery);
    setDownloadError(null);
  }, [currentJobId]);

  useEffect(() => {
    const timer = setTimeout(() => {
      setDebouncedSearchQuery(searchInput);
    }, 250);

    return () => clearTimeout(timer);
  }, [searchInput]);

  if (!activeData) {
    return <EmptyState job={job} />;
  }

  const summary = activeData.summary;
  const duplicates = activeData.duplicates ?? [];
  const groupedProblems = activeData.grouped_problems ?? {};
  const reviewFlags = activeData.review_flags ?? [];
  const allGroups = sortProblemGroups(groupedProblems);
  const filteredGroupedProblems = filterProblemGroupsForResultView(
    groupedProblems,
    debouncedSearchQuery,
    resultFilters,
    reviewFlags,
    showReviewOnly,
  );
  const groups = sortProblemGroups(filteredGroupedProblems);
  const processedRows = Number(summary.processed_rows ?? job?.processed_rows ?? getValidatedTotalRows(summary));
  const showCleanState = Number(summary.rows_with_issues ?? 0) === 0;
  const hasSearch = hasResultSearchQuery(debouncedSearchQuery);
  const hasActiveFilters = hasActiveResultFilters(resultFilters) || showReviewOnly;
  const activeFilterCount = getActiveResultFilterCount(resultFilters) + (showReviewOnly ? 1 : 0);
  const reviewFlagCount = getReviewFlaggedRowCount(reviewFlags);
  const resultFilterGroups = buildResultFilterGroups(
    groupedProblems,
    debouncedSearchQuery,
    resultFilters,
  );
  const duplicateFilterCounts = getDuplicateFilterCounts(
    duplicates,
    debouncedSearchQuery,
    reviewFlags,
    showReviewOnly,
  );
  const bulkConsolidatableSameNameDuplicates = getBulkConsolidatableSameNameDuplicates(duplicates);
  const filteredDuplicates = filterDuplicatesForResultSearch(
    duplicates,
    duplicateFilter,
    debouncedSearchQuery,
    reviewFlags,
    showReviewOnly,
  );
  const searchProblemOccurrenceCount = groups.reduce(
    (total, group) => total + group.occurrences.length,
    0,
  );
  const totalProblemOccurrenceCount = allGroups.reduce(
    (total, group) => total + group.occurrences.length,
    0,
  );
  const canReviewRows = !isPartial && Boolean(currentJobId);
  const showResultFilterEmptyState =
    (hasSearch || hasActiveFilters) && filteredDuplicates.length === 0 && groups.length === 0;
  const hasActiveOperationalExportFilters =
    hasSearch || hasActiveFilters || duplicateFilter !== "all";
  const filteredOperationalExportCount = filteredDuplicates.length + searchProblemOccurrenceCount;

  async function handleDownload(path: string, fallbackFileName: string) {
    try {
      setDownloadError(null);
      await downloadApiFile(path, fallbackFileName);
    } catch (caughtError) {
      const message =
        caughtError instanceof Error
          ? caughtError.message
          : "Não foi possível baixar o arquivo solicitado.";
      setDownloadError(message);
    }
  }

  function handleDownloadFilteredOperationalExport() {
    if (!currentJobId) {
      return;
    }

    try {
      setDownloadError(null);
      downloadGeneratedFile(
        buildFilteredOperationalExportCsv({
          duplicates,
          groupedProblems,
          query: debouncedSearchQuery,
          duplicateFilter,
          filters: resultFilters,
          reviewFlags,
          reviewOnly: showReviewOnly,
        }),
        `operacional-${hasActiveOperationalExportFilters ? "filtrado-" : ""}${currentJobId}.csv`,
        { type: "text/csv;charset=utf-8" },
      );
    } catch (caughtError) {
      const message =
        caughtError instanceof Error
          ? caughtError.message
          : "Não foi possível gerar o CSV filtrado.";
      setDownloadError(message);
    }
  }

  return (
    <>
      <JobLineageBanner job={job} onOpenRelatedJob={onOpenRelatedJob} />

      <ResultGuideCard job={job} summary={summary} isPartial={isPartial} />

      <SummarySection
        summary={summary}
        validationScope={validationScope}
        isPartial={isPartial}
        processedRows={processedRows}
      />

      <section className="panel result-search-card">
        <div className="result-search-row">
          <div className="field result-search-field">
            <label htmlFor="result-search-input">Procurar linha ou problema</label>
            <input
              id="result-search-input"
              type="search"
              value={searchInput}
              placeholder="Item, linha, campo ou orientação"
              onChange={(event) => setSearchInput(event.target.value)}
            />
          </div>

          {searchInput ? (
            <button
              className="action-button"
              type="button"
              onClick={() => {
                setSearchInput("");
                setDebouncedSearchQuery("");
              }}
            >
              Limpar
            </button>
          ) : null}
        </div>

        <p className="result-search-meta">
          {hasSearch || hasActiveFilters
            ? `${filteredDuplicates.length} duplicidade(s) e ${searchProblemOccurrenceCount} ocorrência(s) exibidas.`
            : `${duplicates.length} grupo(s) de duplicidade e ${totalProblemOccurrenceCount} ocorrência(s) encontrados neste lote.`}
        </p>

        {resultFilterGroups.length || reviewFlagCount || showReviewOnly ? (
          <div className="result-filter-panel" aria-label="Filtros do resultado">
            <div className="result-filter-head">
              <div className="panel-kicker panel-kicker-inline">Filtros</div>
              {hasActiveFilters ? (
                <button
                  className="action-button"
                  type="button"
                  onClick={() => {
                    setResultFilters(resetResultFilterState());
                    setShowReviewOnly(false);
                  }}
                >
                  Limpar filtros ({activeFilterCount})
                </button>
              ) : null}
            </div>

            <div className="result-filter-groups">
              {reviewFlagCount || showReviewOnly ? (
                <div className="result-filter-group">
                  <small>Marcação</small>
                  <div className="result-filter-chips">
                    <button
                      className={`result-filter-chip review ${showReviewOnly ? "active" : ""}`.trim()}
                      type="button"
                      aria-pressed={showReviewOnly}
                      onClick={() => setShowReviewOnly((currentValue) => !currentValue)}
                    >
                      <span>Para revisão</span>
                      <strong>{reviewFlagCount}</strong>
                    </button>
                  </div>
                </div>
              ) : null}
              {resultFilterGroups.map((group) => (
                <div className="result-filter-group" key={group.dimension}>
                  <small>{group.label}</small>
                  <div className="result-filter-chips">
                    {group.options.map((option) => (
                      <button
                        className={`result-filter-chip ${option.active ? "active" : ""} ${
                          option.kind || ""
                        }`.trim()}
                        type="button"
                        aria-pressed={option.active}
                        key={option.value}
                        onClick={() =>
                          setResultFilters((currentFilters) =>
                            toggleResultFilter(currentFilters, group.dimension, option.value),
                          )
                        }
                      >
                        <span>{option.label}</span>
                        <strong>{option.count}</strong>
                      </button>
                    ))}
                  </div>
                </div>
              ))}
            </div>
          </div>
        ) : null}
      </section>

      {!isPartial && currentJobId ? (
        <section className="panel actions-card">
          <div className="panel-kicker">Baixar arquivos</div>
          <h2 className="panel-title">Arquivos prontos deste lote</h2>
          <div className="actions">
            <button
              className="action-link"
              type="button"
              onClick={() => void handleDownload(`/jobs/${currentJobId}/report`, `relatorio-${currentJobId}.pdf`)}
            >
              Baixar relatório PDF
            </button>
            <button
              className="action-link"
              type="button"
              onClick={() =>
                void handleDownload(`/jobs/${currentJobId}/result`, `resultado-${currentJobId}.json`)
              }
            >
              Baixar dados estruturados
            </button>
            <button
              className="action-link"
              type="button"
              onClick={() => void handleDownload(`/jobs/${currentJobId}/csv`, `corrigido-${currentJobId}.csv`)}
            >
              Baixar CSV corrigido
            </button>
            <button
              className="action-link"
              type="button"
              onClick={() =>
                void handleDownload(
                  `/jobs/${currentJobId}/export?format=xlsx`,
                  `corrigido-${currentJobId}.xlsx`,
                )
              }
            >
              Exportar Excel
            </button>
          </div>
          {downloadError ? <p className="inline-error">{downloadError}</p> : null}

          {duplicates.length || allGroups.length ? (
            <div className="export-actions">
              <div>
                <div className="panel-kicker">Separar por assunto</div>
              </div>

              <div className="export-actions-grid">
                <article className="export-card">
                  <small>{hasActiveOperationalExportFilters ? "Recorte atual" : "Tela completa"}</small>
                  <strong>CSV do que você está vendo agora</strong>
                  <p>{filteredOperationalExportCount} registro(s) visíveis.</p>
                  <button
                    className="action-link"
                    type="button"
                    disabled={filteredOperationalExportCount === 0}
                    onClick={() => handleDownloadFilteredOperationalExport()}
                  >
                    {hasActiveOperationalExportFilters
                      ? "Baixar este recorte"
                      : "Baixar este resumo"}
                  </button>
                </article>

                {duplicates.length ? (
                  <article className="export-card">
                    <small>Duplicidades</small>
                    <strong>CSV só com os itens repetidos</strong>
                    <p>{duplicates.length} grupo(s).</p>
                    <button
                      className="action-link"
                      type="button"
                      onClick={() =>
                        void handleDownload(
                          `/jobs/${currentJobId}/exports/csv?kind=duplicates`,
                          `duplicidades-${currentJobId}.csv`,
                        )
                      }
                    >
                      Baixar somente duplicados
                    </button>
                  </article>
                ) : null}

                {allGroups.map(({ code, occurrences }) => {
                  const guide = describeIssue(code, occurrences[0]?.message);
                  return (
                    <article className="export-card" key={code}>
                      <small>{code}</small>
                      <strong>{guide.title}</strong>
                      <p>{occurrences.length} ocorrência(s).</p>
                      <button
                        className="action-link"
                        type="button"
                        onClick={() =>
                          void handleDownload(
                            `/jobs/${currentJobId}/exports/csv?kind=problem_group&problem_code=${encodeURIComponent(code)}`,
                            `${slugify(code)}-${currentJobId}.csv`,
                          )
                        }
                      >
                        Baixar somente este grupo
                      </button>
                    </article>
                  );
                })}
              </div>
            </div>
          ) : null}
        </section>
      ) : null}

      {!isPartial && hasPendingCorrections && currentJobId ? (
        <section className="panel correction-card">
          <div className="panel-kicker">Depois de corrigir</div>
          <h2 className="panel-title">Planilha ajustada nesta sessão</h2>
          <div className="correction-actions">
            <button
              className="action-link"
              type="button"
              onClick={() => void handleDownload(`/jobs/${currentJobId}/csv`, `corrigido-${currentJobId}.csv`)}
            >
              Baixar CSV corrigido
            </button>
            <button
              className="action-link"
              type="button"
              onClick={() =>
                void handleDownload(
                  `/jobs/${currentJobId}/export?format=xlsx`,
                  `corrigido-${currentJobId}.xlsx`,
                )
              }
            >
              Exportar Excel
            </button>
            <button className="action-button primary" type="button" disabled={isReprocessing} onClick={onReprocess}>
              {isReprocessing ? "Rodando nova conferência..." : "Rodar nova conferência"}
            </button>
          </div>
          {downloadError ? <p className="inline-error">{downloadError}</p> : null}
        </section>
      ) : null}

      {duplicates.length ? (
        <section className="panel duplicates-card">
          <div className="panel-kicker">Duplicidades</div>
          <h2 className="panel-title">Compare itens repetidos</h2>
          {bulkConsolidatableSameNameDuplicates.length ? (
            <div className="duplicate-bulk-actions">
              <p>
                Este atalho resolve automaticamente grupos de <b>mesmo nome</b> com <b>2 ocorrências</b>.
              </p>
              <button
                className="action-button primary"
                type="button"
                disabled={isPartial || isResolvingBulkSameNameDuplicates}
                onClick={onResolveBulkSameNameDuplicates}
              >
                {isResolvingBulkSameNameDuplicates
                  ? "Resolvendo..."
                  : `Resolver casos simples (${bulkConsolidatableSameNameDuplicates.length})`}
              </button>
            </div>
          ) : null}
          <div className="duplicate-filter-list" role="tablist" aria-label="Filtrar duplicidades">
            {(["all", "normal", "conflict"] as DuplicateDisplayFilter[]).map((filterKey) => (
              <button
                key={filterKey}
                className={`duplicate-filter-chip ${duplicateFilter === filterKey ? "active" : ""}`.trim()}
                type="button"
                role="tab"
                aria-selected={duplicateFilter === filterKey}
                onClick={() => setDuplicateFilter(filterKey)}
              >
                <span>{DUPLICATE_FILTER_LABELS[filterKey]}</span>
                <strong>{duplicateFilterCounts[filterKey]}</strong>
              </button>
            ))}
          </div>

          <div className="duplicates-grid">
            {filteredDuplicates.length ? filteredDuplicates.map((duplicate, index) => {
              const hasDescriptionConflict = hasDuplicateDescriptionConflict(duplicate);
              return (
                <article
                  className={`duplicate-card ${hasDescriptionConflict ? "description-conflict" : ""}`.trim()}
                  key={`${duplicate.item || "sem-item"}-${index}`}
                >
                  <strong>{duplicate.item || "Sem item"}</strong>
                  {hasDescriptionConflict ? (
                    <span className="duplicate-alert">Nomes do bem diferentes</span>
                  ) : null}
                  <p>
                    <b>Nome do bem:</b> {duplicate.descricao || "Não informado"}
                  </p>
                  <p>
                    <b>Ocorrências:</b> {duplicate.count}
                  </p>
                  <p>
                    <b>Linhas envolvidas:</b>{" "}
                    {duplicate.row_indices.map((rowIndex) => lineNumber(rowIndex)).join(", ")}
                  </p>
                  <div className="duplicate-card-actions">
                    <button
                      className="action-button"
                      type="button"
                      disabled={isPartial || isResolvingBulkSameNameDuplicates}
                      onClick={() => onResolveDuplicate(duplicate)}
                    >
                      {isPartial ? "Aguarde a conclusão" : "Abrir comparação"}
                    </button>
                  </div>
                </article>
              );
            }) : (
              <article className="duplicate-card duplicate-card-empty">
                <strong>Nenhum item neste filtro</strong>
                <p>
                  {hasSearch
                    ? "Nenhuma duplicidade corresponde à busca atual."
                    : duplicateFilter === "normal"
                    ? "Não há duplicados com nomes iguais para revisar neste lote."
                    : "Não há duplicados com nomes diferentes para revisar neste lote."}
                </p>
              </article>
            )}
          </div>
        </section>
      ) : null}

      {showResultFilterEmptyState ? (
        <section className="panel empty-card">
          <div className="panel-kicker">Resultado</div>
          <h2 className="panel-title">Nenhuma linha corresponde aos filtros atuais</h2>
          <p>Revise a busca ou limpe os filtros para voltar ao resultado completo.</p>
        </section>
      ) : null}

      {groups.length ? (
        <section className="panel nav-card">
          <div className="panel-kicker">Ir direto</div>
          <h2 className="panel-title">Problemas por assunto</h2>
          <div className="nav-chips">
            {groups.map(({ code, occurrences }) => {
              const severity = occurrences.some((occurrence) => occurrence.severity === "error")
                ? "error"
                : "warning";
              const guide = describeIssue(code, occurrences[0]?.message);
              return (
                <a className={`nav-chip ${severity}`} href={`#problem-${slugify(code)}`} key={code}>
                  <span>{guide.title}</span>
                  <strong>{occurrences.length}</strong>
                </a>
              );
            })}
          </div>
        </section>
      ) : null}

      {showCleanState ? (
        <section className="panel clean-card">
          <div className="panel-kicker">Resultado do lote</div>
          <h2 className="panel-title">
            {!isPartial &&
            isZeroItemsScope(validationScope) &&
            getValidatedTotalRows(summary) === 0 &&
            getSourceTotalRows(summary) > 0
              ? "Nenhum item cadastrado do zero entrou no escopo deste processamento"
              : !isPartial &&
                  isDuplicateItemsScope(validationScope) &&
                  getValidatedTotalRows(summary) === 0 &&
                  getSourceTotalRows(summary) > 0
                ? "Nenhum item duplicado entrou no escopo deste processamento"
              : isPartial
                ? "Nenhuma pendência foi confirmada na prévia atual"
                : "Nenhuma correção foi exigida neste processamento"}
          </h2>
          <p>
            {!isPartial &&
            isZeroItemsScope(validationScope) &&
            getValidatedTotalRows(summary) === 0 &&
            getSourceTotalRows(summary) > 0
              ? `CSV original: ${getSourceTotalRows(summary)} linhas. Nenhuma entrou no escopo de itens novos.`
              : !isPartial &&
                  isDuplicateItemsScope(validationScope) &&
                  getValidatedTotalRows(summary) === 0 &&
                  getSourceTotalRows(summary) > 0
                ? `CSV original: ${getSourceTotalRows(summary)} linhas. Nenhuma entrou no escopo de duplicidades.`
              : isPartial
                ? `${processedRows} itens validados sem apontamentos até agora.`
                : "Arquivo sem pendências abertas."}
          </p>
        </section>
      ) : null}

      {groups.length ? (
        <section className="problems" id="problems-section">
          {groups.map(({ code, occurrences }) => {
            const guide = describeIssue(code, occurrences[0]?.message);
            const severity = occurrences.some((occurrence) => occurrence.severity === "error")
              ? "error"
              : "warning";
            const visibleCount = Math.min(
              occurrences.length,
              visibleProblemOccurrencesByCode[code] || 20,
            );
            const visibleOccurrences = [...occurrences]
              .sort((left, right) => left.row_index - right.row_index)
              .slice(0, visibleCount);

            return (
              <article className="panel problem-card" id={`problem-${slugify(code)}`} key={code}>
                <div className="problem-header">
                  <div>
                    <span className="problem-kicker">
                      {severity === "error" ? "Erro" : "Aviso"}
                    </span>
                    <h3 className="problem-title">{guide.title}</h3>
                    <p className="problem-meta">
                      {occurrences.length} ocorrência(s)
                    </p>
                  </div>
                  <span className={`status-chip ${severity}`}>
                    {severity === "error" ? "Erro" : "Aviso"}
                  </span>
                </div>

                <div className="problem-layout">
                  <section className="detail-box">
                    <small>Ação</small>
                    <p>{guide.action}</p>
                  </section>
                </div>

                <div className="table-wrap">
                  <table>
                    <thead>
                      <tr>
                        <th>Linha</th>
                        <th>Item</th>
                        <th>Nome do bem</th>
                        <th>Campo</th>
                        <th>Orientação</th>
                        {canReviewRows ? <th>Revisão</th> : null}
                        <th>Ação</th>
                      </tr>
                    </thead>
                    <tbody>
                      {visibleOccurrences.map((occurrence) => {
                        const editableField = resolveEditableField(occurrence);
                        const isMarkedForReview = isRowMarkedForReview(
                          reviewFlags,
                          occurrence.row_index,
                        );
                        return (
                          <tr key={`${code}-${occurrence.row_index}-${occurrence.message}`}>
                            <td>{lineNumber(occurrence.row_index)}</td>
                            <td>{occurrence.item || "Não informado"}</td>
                            <td>{occurrence.descricao || "Não informado"}</td>
                            <td>
                              <span className="field-pill">
                                {formatFieldName(editableField || occurrence.field)}
                              </span>
                            </td>
                            <td>{occurrence.message}</td>
                            {canReviewRows ? (
                              <td>
                                <button
                                  className={`review-marker ${isMarkedForReview ? "active" : ""}`.trim()}
                                  type="button"
                                  aria-pressed={isMarkedForReview}
                                  disabled={isSavingReviewFlag}
                                  onClick={() =>
                                    onToggleReviewFlag(
                                      occurrence.row_index,
                                      isMarkedForReview ? "clear" : "review",
                                    )
                                  }
                                >
                                  {isMarkedForReview ? "Para revisão" : "Marcar"}
                                </button>
                              </td>
                            ) : null}
                            <td>
                              <button
                                className="edit-action"
                                type="button"
                                disabled={!editableField}
                                onClick={() => onEditOccurrence(occurrence)}
                              >
                                Corrigir
                              </button>
                            </td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>

                {visibleCount < occurrences.length ? (
                  <div className="problem-pagination">
                    <p>
                      Mostrando {visibleCount} de {occurrences.length}.
                    </p>
                    <button className="action-button" type="button" onClick={() => onShowMore(code)}>
                      Carregar mais
                    </button>
                  </div>
                ) : null}
              </article>
            );
          })}
        </section>
      ) : null}
    </>
  );
}
