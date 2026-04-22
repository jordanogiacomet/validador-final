"use client";

import React, { useEffect, useMemo, useRef, useState } from "react";
import type { FormEvent } from "react";

import { ActiveJobsPanel } from "@/components/active-jobs-panel";
import { AuditPanel } from "@/components/audit-panel";
import { DuplicateResolutionModal } from "@/components/duplicate-resolution-modal";
import { EditRowModal } from "@/components/edit-row-modal";
import { ProcessCard } from "@/components/process-card";
import { ResultWorkspace } from "@/components/result-workspace";
import { StateBanner } from "@/components/state-banner";
import { UploadPanel } from "@/components/upload-panel";
import {
  cancelJob,
  extractUploadPreflightPayload,
  getJob,
  getJobResult,
  getJobRow,
  listTenants,
  reprocessJob,
  resolveDuplicateRows,
  setJobRowReviewFlag,
  updateJobRow,
  validateFile,
} from "@/lib/api";
import {
  INITIAL_PROBLEM_OCCURRENCES,
  PROBLEM_OCCURRENCES_STEP,
  buildFinalScopeCopy,
  buildPreviewReportData,
  formatJobFailureMessage,
  formatFieldName,
  getBulkConsolidatableSameNameDuplicates,
  hasDuplicateDescriptionConflict,
  getDuplicateSuggestedKeepRow,
  getSourceTotalRows,
  getValidatedTotalRows,
  isJobTerminal,
  lineNumber,
  normalizeValidationScope,
  resolveEditableField,
} from "@/lib/presentation";
import type {
  BannerState,
  DuplicateGroup,
  DuplicateModalState,
  EditModalState,
  JobResultPayload,
  JobStatus,
  JobStatusResponse,
  ProblemOccurrence,
  ReviewFlagActionStatus,
  RowReadResponse,
  TenantListItem,
  UploadPreflightPayload,
  ValidationScope,
} from "@/lib/types";
import { useActiveJobs } from "@/hooks/use-active-jobs";
import { useJobPolling } from "@/hooks/use-job-polling";

const FALLBACK_TENANT: TenantListItem = {
  tenant_id: "default",
  display_name: "Empresa padrão",
  is_default: true,
};

function buildFallbackTenant(tenantId: string): TenantListItem {
  if (tenantId === FALLBACK_TENANT.tenant_id) {
    return FALLBACK_TENANT;
  }

  return {
    tenant_id: tenantId,
    display_name: tenantId,
    is_default: false,
  };
}

function createClientJobState(params: {
  jobId: string;
  tenantId: string;
  status: JobStatus;
  validationScope: ValidationScope;
  fileName?: string | null;
  currentStep?: string | null;
  statusTitle?: string | null;
  statusDetail?: string | null;
  errorMessage?: string | null;
  cancelRequested?: boolean;
}): JobStatusResponse {
  return {
    job_id: params.jobId,
    tenant_id: params.tenantId,
    validation_scope: params.validationScope,
    status: params.status,
    total_rows: 0,
    source_total_rows: 0,
    rows_with_issues: 0,
    total_issues: 0,
    processed_rows: 0,
    batch_size: 0,
    error_message: params.errorMessage || null,
    partial_summary: {},
    is_partial_result_available: false,
    partial_grouped_problems: {},
    partial_duplicates: [],
    row_results_preview: [],
    current_step: params.currentStep || "file_received",
    status_title: params.statusTitle || "Arquivo recebido",
    status_detail: params.statusDetail || "Aguardando processamento.",
    created_at: null,
    updated_at: new Date().toISOString(),
    file_name: params.fileName || null,
    cancel_requested: params.cancelRequested || false,
  };
}

function getTenantLabel(tenants: TenantListItem[], tenantId: string | null): string {
  if (!tenantId) {
    return "-";
  }

  const tenant = tenants.find((option) => option.tenant_id === tenantId);
  if (!tenant) {
    return tenantId;
  }

  return tenant.display_name;
}

function buildRowCacheKey(jobId: string, rowIndex: number): string {
  return `${jobId}:${rowIndex}`;
}

function deriveDefaultBanner(
  job: JobStatusResponse | null,
  reportData: JobResultPayload | null,
  validationScope: ValidationScope,
): BannerState | null {
  const previewData = buildPreviewReportData(job);

  if (job?.status === "completed" && reportData) {
    return {
      kind: "success",
      label: "Resultado consolidado",
      detail: buildFinalScopeCopy(validationScope),
    };
  }

  if (job?.status === "canceled") {
    return {
      kind: "warning",
      label: "Processamento cancelado",
      detail: job.status_detail || "O lote foi interrompido.",
    };
  }

  if (job?.cancel_requested) {
    return {
      kind: "warning",
      label: "Cancelamento solicitado",
      detail: job.status_detail || "O lote será interrompido em uma etapa segura.",
    };
  }

  if (job?.status === "failed") {
    return {
      kind: "error",
      label: "Falha no processamento",
      detail: formatJobFailureMessage(job),
    };
  }

  if (previewData && job) {
    const previewSummary = previewData.summary || {};
    const previewValidatedRows = getValidatedTotalRows(previewSummary);
    const previewSourceRows = getSourceTotalRows(previewSummary);
    return {
      kind: "warning",
      label: "Prévia disponível",
      detail: `${job.processed_rows || 0} de ${previewValidatedRows} itens validados.${previewSourceRows !== previewValidatedRows ? ` CSV original: ${previewSourceRows} linhas.` : ""} Revise os registros liberados enquanto o lote termina.`,
    };
  }

  if (job && (job.status === "queued" || job.status === "running")) {
    return {
      kind: "info",
      label: "Processamento em andamento",
      detail: "A prévia será exibida assim que houver registros confiáveis para revisar.",
    };
  }

  return null;
}

interface OperationalWorkspaceProps {
  initialTenantId: string;
}

export function OperationalWorkspace({ initialTenantId }: OperationalWorkspaceProps) {
  const { jobs, isLoading: jobsLoading, error: jobsError, refreshJobs } = useActiveJobs({
    activeOnly: false,
    limit: 8,
  });
  const fallbackTenant = useMemo(
    () => buildFallbackTenant(initialTenantId),
    [initialTenantId],
  );
  const [tenants, setTenants] = useState<TenantListItem[]>([fallbackTenant]);
  const [selectedTenantId, setSelectedTenantId] = useState(initialTenantId);
  const [tenantError, setTenantError] = useState<string | null>(null);
  const [isTenantLoading, setIsTenantLoading] = useState(true);
  const [validationScope, setValidationScope] = useState<ValidationScope>("zero_items");
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [selectedFileName, setSelectedFileName] = useState<string | null>(null);
  const [uploadPreflight, setUploadPreflight] = useState<UploadPreflightPayload | null>(
    null,
  );
  const [currentJobId, setCurrentJobId] = useState<string | null>(null);
  const [currentJob, setCurrentJob] = useState<JobStatusResponse | null>(null);
  const [reportData, setReportData] = useState<JobResultPayload | null>(null);
  const [manualBanner, setManualBanner] = useState<BannerState | null>(null);
  const [hasPendingCorrections, setHasPendingCorrections] = useState(false);
  const [visibleProblemOccurrencesByCode, setVisibleProblemOccurrencesByCode] = useState<
    Record<string, number>
  >({});
  const [editModalState, setEditModalState] = useState<EditModalState | null>(null);
  const [editValue, setEditValue] = useState("");
  const [isEditModalLoading, setIsEditModalLoading] = useState(false);
  const [rowCache, setRowCache] = useState<Record<string, RowReadResponse>>({});
  const [isSavingEdit, setIsSavingEdit] = useState(false);
  const [duplicateModalState, setDuplicateModalState] = useState<DuplicateModalState | null>(null);
  const [selectedKeepRowIndex, setSelectedKeepRowIndex] = useState<number | null>(null);
  const [isSavingDuplicateResolution, setIsSavingDuplicateResolution] = useState(false);
  const [isBulkResolvingSameNameDuplicates, setIsBulkResolvingSameNameDuplicates] = useState(false);
  const [isSavingReviewFlag, setIsSavingReviewFlag] = useState(false);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [isReprocessing, setIsReprocessing] = useState(false);
  const latestEditRequestRef = useRef(0);

  useEffect(() => {
    let isCancelled = false;

    async function loadTenantOptions() {
      try {
        const nextTenants = await listTenants();
        if (isCancelled || !nextTenants.length) {
          return;
        }

        setTenants(nextTenants);
        const preferredTenant =
          nextTenants.find((tenant) => tenant.tenant_id === selectedTenantId) ||
          nextTenants.find((tenant) => tenant.is_default) ||
          nextTenants[0];
        setSelectedTenantId(preferredTenant.tenant_id);
        setTenantError(null);
      } catch (caughtError) {
        if (isCancelled) {
          return;
        }

        const message =
          caughtError instanceof Error
            ? caughtError.message
            : "Falha ao carregar os tenants disponíveis.";
        setTenantError(message);
        setTenants([fallbackTenant]);
        setSelectedTenantId(initialTenantId);
      } finally {
        if (!isCancelled) {
          setIsTenantLoading(false);
        }
      }
    }

    void loadTenantOptions();
    return () => {
      isCancelled = true;
    };
  }, [fallbackTenant, initialTenantId, selectedTenantId]);

  useJobPolling({
    jobId: currentJobId,
    enabled: Boolean(currentJobId && (!currentJob || !isJobTerminal(currentJob))),
    onJobUpdate: (job) => {
      setCurrentJob(job);
      setValidationScope(normalizeValidationScope(job.validation_scope));
      if (job.status !== "completed") {
        setReportData(null);
      }
    },
    onError: (message) => {
      setManualBanner({
        kind: "error",
        label: "Falha ao consultar o lote",
        detail: message,
      });
    },
  });

  useEffect(() => {
    if (!currentJobId || currentJob?.status !== "completed" || reportData) {
      return;
    }

    const completedJobId = currentJobId;
    let isCancelled = false;

    async function loadCompletedResult() {
      try {
        const result = await getJobResult(completedJobId);
        if (!isCancelled) {
          setReportData(result);
        }
      } catch (caughtError) {
        if (isCancelled) {
          return;
        }

        const message =
          caughtError instanceof Error
            ? caughtError.message
            : "Falha ao carregar o resultado estruturado do lote.";
        setManualBanner({
          kind: "error",
          label: "Falha ao carregar o resultado",
          detail: message,
        });
      }
    }

    void loadCompletedResult();
    return () => {
      isCancelled = true;
    };
  }, [currentJob, currentJobId, reportData]);

  function closeEditModal() {
    latestEditRequestRef.current += 1;
    setEditModalState(null);
    setEditValue("");
    setIsEditModalLoading(false);
  }

  function applyRowPayloadToEditModal(
    occurrence: ProblemOccurrence,
    editableField: string,
    rowPayload: RowReadResponse,
  ) {
    const sourceColumn = rowPayload.resolved_columns[editableField] || editableField;
    const currentValue = rowPayload.row[sourceColumn] || "";

    setEditModalState({
      rowIndex: occurrence.row_index,
      field: formatFieldName(editableField),
      fieldKey: editableField,
      itemLabel: occurrence.item || "",
      sourceColumn,
      currentValue,
    });
    setEditValue(currentValue);
    setIsEditModalLoading(false);
  }

  function resetWorkspaceState() {
    setVisibleProblemOccurrencesByCode({});
    closeEditModal();
    setRowCache({});
    setDuplicateModalState(null);
    setSelectedKeepRowIndex(null);
  }

  async function loadCompletedJob(jobId: string) {
    const [job, result] = await Promise.all([getJob(jobId), getJobResult(jobId)]);
    setCurrentJobId(jobId);
    setCurrentJob(job);
    setReportData(result);
    setValidationScope(normalizeValidationScope(job.validation_scope));
  }

  async function openJob(jobId: string) {
    resetWorkspaceState();
    setManualBanner(null);
    setUploadPreflight(null);
    setHasPendingCorrections(false);

    try {
      const job = await getJob(jobId);
      if (job.status === "completed") {
        await loadCompletedJob(jobId);
        return;
      }

      setCurrentJobId(jobId);
      setCurrentJob(job);
      setReportData(null);
      setValidationScope(normalizeValidationScope(job.validation_scope));
    } catch (caughtError) {
      const message =
        caughtError instanceof Error ? caughtError.message : "Falha ao carregar o lote selecionado.";
      setManualBanner({
        kind: "error",
        label: "Falha ao abrir o lote",
        detail: message,
      });
    }
  }

  async function handleCancelJob(jobId: string) {
    try {
      const payload = await cancelJob(jobId);
      if (jobId === currentJobId) {
        setCurrentJob(payload);
        if (payload.status !== "completed") {
          setReportData(null);
        }
      }

      setManualBanner({
        kind: "warning",
        label: payload.status === "canceled" ? "Processamento cancelado" : "Cancelamento solicitado",
        detail: payload.status_detail || "O lote será interrompido em uma etapa segura.",
      });
      await refreshJobs();
    } catch (caughtError) {
      const message =
        caughtError instanceof Error
          ? caughtError.message
          : "Não foi possível interromper o lote selecionado.";
      setManualBanner({
        kind: "error",
        label: "Falha ao cancelar o job",
        detail: message,
      });
    }
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!selectedFile) {
      setUploadPreflight(null);
      setManualBanner({
        kind: "error",
        label: "Arquivo não informado",
        detail: "Selecione um CSV antes de iniciar o processamento do lote.",
      });
      return;
    }

    setManualBanner(null);
    setUploadPreflight(null);
    setIsSubmitting(true);

    try {
      const uploadPayload = await validateFile({
        file: selectedFile,
        tenantId: selectedTenantId,
        validationScope,
      });

      resetWorkspaceState();
      setReportData(null);
      setHasPendingCorrections(false);
      setCurrentJobId(uploadPayload.job_id);
      setCurrentJob(
        createClientJobState({
          jobId: uploadPayload.job_id,
          tenantId: uploadPayload.tenant_id,
          status: uploadPayload.status,
          validationScope: uploadPayload.validation_scope,
          fileName: selectedFile.name,
          currentStep: "file_received",
          statusTitle: "Arquivo recebido",
          statusDetail: "Aguardando processamento.",
        }),
      );
      setValidationScope(uploadPayload.validation_scope);
      await refreshJobs();
    } catch (caughtError) {
      const preflightPayload = extractUploadPreflightPayload(caughtError);
      if (preflightPayload) {
        setUploadPreflight(preflightPayload);
        return;
      }

      const message =
        caughtError instanceof Error ? caughtError.message : "Não foi possível concluir o lote.";
      setManualBanner({
        kind: "error",
        label: "Falha no processamento",
        detail: message,
      });
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleEditOccurrence(occurrence: ProblemOccurrence) {
    if (!currentJobId) {
      setManualBanner({
        kind: "error",
        label: "Edição indisponível",
        detail: "Nenhum job ativo foi identificado para registrar a correção.",
      });
      return;
    }

    const editableField = resolveEditableField(occurrence);
    if (!editableField) {
      setManualBanner({
        kind: "warning",
        label: "Edição não permitida",
        detail: "Este apontamento não possui um campo editável associado no CSV.",
      });
      return;
    }

    const requestId = latestEditRequestRef.current + 1;
    latestEditRequestRef.current = requestId;
    setEditModalState({
      rowIndex: occurrence.row_index,
      field: formatFieldName(editableField),
      fieldKey: editableField,
      itemLabel: occurrence.item || "",
      sourceColumn: "",
      currentValue: "",
    });
    setEditValue("");
    setIsEditModalLoading(true);

    const cacheKey = buildRowCacheKey(currentJobId, occurrence.row_index);
    const cachedRowPayload = rowCache[cacheKey];
    if (cachedRowPayload) {
      applyRowPayloadToEditModal(occurrence, editableField, cachedRowPayload);
      return;
    }

    try {
      const rowPayload = await getJobRow(currentJobId, occurrence.row_index);
      setRowCache((currentValue) => ({
        ...currentValue,
        [cacheKey]: rowPayload,
      }));

      if (latestEditRequestRef.current !== requestId) {
        return;
      }

      applyRowPayloadToEditModal(occurrence, editableField, rowPayload);
    } catch (caughtError) {
      if (latestEditRequestRef.current !== requestId) {
        return;
      }

      closeEditModal();
      const message =
        caughtError instanceof Error ? caughtError.message : "Não foi possível carregar o valor atual no CSV.";
      setManualBanner({
        kind: "error",
        label: "Falha ao corrigir",
        detail: message,
      });
    }
  }

  async function saveEditModal() {
    if (!editModalState || !currentJobId || isEditModalLoading) {
      return;
    }

    setIsSavingEdit(true);
    try {
      const payload = await updateJobRow(currentJobId, editModalState.rowIndex, {
        [editModalState.fieldKey]: editValue,
      });
      const cacheKey = buildRowCacheKey(currentJobId, editModalState.rowIndex);
      setRowCache((currentValue) => {
        const cachedRowPayload = currentValue[cacheKey];
        if (!cachedRowPayload) {
          return currentValue;
        }

        return {
          ...currentValue,
          [cacheKey]: {
            ...cachedRowPayload,
            row: payload.updated_row,
          },
        };
      });
      setHasPendingCorrections(true);
      closeEditModal();
      setManualBanner({
        kind: "success",
        label: "Correção registrada",
        detail: "CSV atualizado. Reprocesse o lote ao terminar as edições.",
      });
    } catch (caughtError) {
      const message =
        caughtError instanceof Error ? caughtError.message : "Não foi possível atualizar o CSV.";
      setManualBanner({
        kind: "error",
        label: "Falha ao corrigir",
        detail: message,
      });
    } finally {
      setIsSavingEdit(false);
    }
  }

  async function handleToggleReviewFlag(rowIndex: number, status: ReviewFlagActionStatus) {
    if (!currentJobId) {
      setManualBanner({
        kind: "error",
        label: "Marcação indisponível",
        detail: "Nenhum job ativo foi identificado para salvar a marcação.",
      });
      return;
    }

    setIsSavingReviewFlag(true);
    try {
      const payload = await setJobRowReviewFlag(currentJobId, rowIndex, status);
      setReportData((currentValue) =>
        currentValue
          ? {
              ...currentValue,
              review_flags: payload.review_flags,
            }
          : currentValue,
      );
      setManualBanner({
        kind: status === "review" ? "warning" : "success",
        label: status === "review" ? "Linha marcada" : "Marcação removida",
        detail:
          status === "review"
            ? `Linha ${lineNumber(rowIndex)} marcada para revisão posterior.`
            : `Linha ${lineNumber(rowIndex)} removida da revisão posterior.`,
      });
    } catch (caughtError) {
      const message =
        caughtError instanceof Error ? caughtError.message : "Não foi possível salvar a marcação.";
      setManualBanner({
        kind: "error",
        label: "Falha ao marcar linha",
        detail: message,
      });
    } finally {
      setIsSavingReviewFlag(false);
    }
  }

  async function handleResolveDuplicate(duplicate: DuplicateGroup) {
    if (!currentJobId) {
      setManualBanner({
        kind: "error",
        label: "Resolução indisponível",
        detail: "Nenhum job ativo foi identificado para resolver a duplicidade.",
      });
      return;
    }

    try {
      const rows = await Promise.all(
        duplicate.row_indices
          .slice()
          .sort((left, right) => left - right)
          .map(async (rowIndex) => ({
            rowIndex,
            rowPayload: await getJobRow(currentJobId, rowIndex),
          })),
      );
      const suggestedKeepRowIndex = getDuplicateSuggestedKeepRow(duplicate);
      setDuplicateModalState({
        duplicate,
        rows,
        suggestedKeepRowIndex: suggestedKeepRowIndex ?? rows[rows.length - 1]?.rowIndex ?? 0,
      });
      setSelectedKeepRowIndex(suggestedKeepRowIndex ?? rows[rows.length - 1]?.rowIndex ?? null);
    } catch (caughtError) {
      const message =
        caughtError instanceof Error ? caughtError.message : "Não foi possível carregar as linhas duplicadas no CSV.";
      setManualBanner({
        kind: "error",
        label: "Falha ao abrir a resolução",
        detail: message,
      });
    }
  }

  async function saveDuplicateResolution() {
    if (!duplicateModalState || !currentJobId || selectedKeepRowIndex === null) {
      setManualBanner({
        kind: "warning",
        label: "Linha pendente",
        detail:
          "A linha-base técnica do grupo precisa estar carregada antes de consolidar a duplicidade.",
      });
      return;
    }

    setIsSavingDuplicateResolution(true);
    try {
      const hasDescriptionConflict = hasDuplicateDescriptionConflict(duplicateModalState.duplicate);
      const payload = await resolveDuplicateRows({
        jobId: currentJobId,
        rowIndices: duplicateModalState.rows.map((entry) => entry.rowIndex),
        keepRowIndex: selectedKeepRowIndex,
      });
      setDuplicateModalState(null);
      setSelectedKeepRowIndex(null);
      setHasPendingCorrections(false);
      await loadCompletedJob(currentJobId);
      const mergedDetail = payload.merged_columns.length
        ? ` Campos preenchidos: ${payload.merged_columns.join(", ")}.`
        : "";
      setManualBanner({
        kind: "success",
        label: "Duplicidade resolvida",
        detail: hasDescriptionConflict
          ? `A ocorrência-base foi atualizada e as demais ocorrências foram removidas do CSV corrigido.${mergedDetail}`
          : `Os dados das ocorrências foram consolidados. Foto, mídia e colunas de data/hora ficaram fora da mescla.${mergedDetail}`,
      });
    } catch (caughtError) {
      const message =
        caughtError instanceof Error ? caughtError.message : "Não foi possível atualizar o CSV.";
      setManualBanner({
        kind: "error",
        label: "Falha ao excluir duplicados",
        detail: message,
      });
    } finally {
      setIsSavingDuplicateResolution(false);
    }
  }

  async function handleResolveBulkSameNameDuplicates() {
    if (!currentJobId || !reportData) {
      setManualBanner({
        kind: "error",
        label: "Consolidação indisponível",
        detail: "Nenhum resultado concluído foi encontrado para consolidar em massa.",
      });
      return;
    }

    const eligibleDuplicates = getBulkConsolidatableSameNameDuplicates(reportData.duplicates ?? []);
    if (!eligibleDuplicates.length) {
      setManualBanner({
        kind: "warning",
        label: "Nada para consolidar",
        detail: "Por enquanto, o atalho em massa consolida apenas grupos de nomes iguais com exatamente 2 ocorrências.",
      });
      return;
    }

    const activeJobId = currentJobId;
    let processedGroups = 0;
    setIsBulkResolvingSameNameDuplicates(true);
    try {
      for (const duplicate of eligibleDuplicates) {
        const keepRowIndex = getDuplicateSuggestedKeepRow(duplicate);
        if (keepRowIndex === null) {
          continue;
        }

        await resolveDuplicateRows({
          jobId: activeJobId,
          rowIndices: duplicate.row_indices,
          keepRowIndex,
        });
        processedGroups += 1;
      }

      setDuplicateModalState(null);
      setSelectedKeepRowIndex(null);
      setHasPendingCorrections(false);
      await loadCompletedJob(activeJobId);
      setManualBanner({
        kind: "success",
        label: "Consolidação em massa concluída",
        detail:
          `${processedGroups} grupo(s) de nomes iguais com 2 ocorrências foram consolidados. ` +
          "Os grupos foram processados em lote do fim para o início do CSV.",
      });
    } catch (caughtError) {
      try {
        await loadCompletedJob(activeJobId);
      } catch {
        // Best-effort refresh after partial bulk updates.
      }

      const message =
        caughtError instanceof Error ? caughtError.message : "Não foi possível consolidar em massa.";
      const detail = processedGroups
        ? `${processedGroups} grupo(s) já tinham sido consolidados antes da falha. ${message}`
        : message;
      setManualBanner({
        kind: "error",
        label: "Falha na consolidação em massa",
        detail,
      });
    } finally {
      setIsBulkResolvingSameNameDuplicates(false);
    }
  }

  async function handleReprocess() {
    if (!currentJobId) {
      return;
    }

    setIsReprocessing(true);
    resetWorkspaceState();
    setManualBanner(null);
    setUploadPreflight(null);

    try {
      const payload = await reprocessJob(currentJobId);
      setHasPendingCorrections(false);
      setReportData(null);
      setCurrentJobId(payload.job_id);
      setCurrentJob(
        createClientJobState({
          jobId: payload.job_id,
          tenantId: payload.tenant_id,
          status: payload.status,
          validationScope: payload.validation_scope,
          fileName: currentJob?.file_name || selectedFileName,
          currentStep: "file_received",
          statusTitle: "Arquivo recebido",
          statusDetail: "Aguardando processamento.",
        }),
      );
      setValidationScope(payload.validation_scope);
      await refreshJobs();
    } catch (caughtError) {
      const message =
        caughtError instanceof Error
          ? caughtError.message
          : "Não foi possível iniciar um novo processamento para o lote corrigido.";
      setManualBanner({
        kind: "error",
        label: "Falha ao reprocessar",
        detail: message,
      });
    } finally {
      setIsReprocessing(false);
    }
  }

  function showMoreProblemOccurrences(code: string) {
    setVisibleProblemOccurrencesByCode((currentValue) => ({
      ...currentValue,
      [code]: (currentValue[code] || INITIAL_PROBLEM_OCCURRENCES) + PROBLEM_OCCURRENCES_STEP,
    }));
  }

  const effectiveValidationScope = currentJob?.validation_scope || validationScope;
  const organizationLabel = getTenantLabel(tenants, currentJob?.tenant_id || selectedTenantId);
  const banner = manualBanner || deriveDefaultBanner(currentJob, reportData, effectiveValidationScope);
  const previewData = buildPreviewReportData(currentJob);

  return (
    <>
      <div className="workspace">
        <aside className="sidebar">
          <UploadPanel
            tenants={tenants}
            selectedTenantId={selectedTenantId}
            validationScope={validationScope}
            selectedFileName={selectedFileName}
            isSubmitting={isSubmitting}
            isTenantLoading={isTenantLoading}
            tenantError={tenantError}
            uploadPreflight={uploadPreflight}
            onTenantChange={(tenantId) => {
              setSelectedTenantId(tenantId);
              setManualBanner(null);
              setUploadPreflight(null);
            }}
            onValidationScopeChange={(scope) => {
              setValidationScope(scope);
              setUploadPreflight(null);
            }}
            onFileChange={(file) => {
              setSelectedFile(file);
              setSelectedFileName(file?.name || null);
              setUploadPreflight(null);
            }}
            onSubmit={handleSubmit}
          />

          <ActiveJobsPanel
            jobs={jobs}
            isLoading={jobsLoading}
            error={jobsError}
            onOpenJob={openJob}
            onCancelJob={handleCancelJob}
          />
        </aside>

        <main className="main">
          <ProcessCard
            job={currentJob}
            organizationLabel={organizationLabel}
            fallbackFileName={selectedFileName}
            validationScope={effectiveValidationScope}
          />

          <StateBanner banner={banner} />

          <ResultWorkspace
            job={currentJob}
            currentJobId={currentJobId}
            validationScope={effectiveValidationScope}
            reportData={reportData}
            previewData={previewData}
            hasPendingCorrections={hasPendingCorrections}
            visibleProblemOccurrencesByCode={visibleProblemOccurrencesByCode}
            isReprocessing={isReprocessing}
            isResolvingBulkSameNameDuplicates={isBulkResolvingSameNameDuplicates}
            isSavingReviewFlag={isSavingReviewFlag}
            onShowMore={showMoreProblemOccurrences}
            onEditOccurrence={handleEditOccurrence}
            onToggleReviewFlag={handleToggleReviewFlag}
            onResolveDuplicate={handleResolveDuplicate}
            onResolveBulkSameNameDuplicates={handleResolveBulkSameNameDuplicates}
            onReprocess={handleReprocess}
            onOpenRelatedJob={openJob}
          />

          <AuditPanel
            tenantId={currentJob?.tenant_id || selectedTenantId}
            currentJobId={currentJobId}
          />
        </main>
      </div>

      <EditRowModal
        state={editModalState}
        newValue={editValue}
        isLoading={isEditModalLoading}
        isSaving={isSavingEdit}
        onNewValueChange={setEditValue}
        onClose={closeEditModal}
        onSave={saveEditModal}
      />

      <DuplicateResolutionModal
        state={duplicateModalState}
        selectedKeepRowIndex={selectedKeepRowIndex}
        isSaving={isSavingDuplicateResolution}
        onClose={() => {
          setDuplicateModalState(null);
          setSelectedKeepRowIndex(null);
        }}
        onSelectKeepRow={setSelectedKeepRowIndex}
        onSave={saveDuplicateResolution}
      />
    </>
  );
}
