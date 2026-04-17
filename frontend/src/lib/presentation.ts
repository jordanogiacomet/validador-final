import type {
  DuplicateGroup,
  JobListItemResponse,
  JobStatusResponse,
  PreviewReportPayload,
  ProblemOccurrence,
  StatusChip,
  SummaryPayload,
  ValidationScope,
} from "@/lib/types";

export const PROCESS_STEPS = [
  {
    id: "file_received",
    label: "Arquivo recebido",
    detail: "Lote na fila.",
  },
  {
    id: "reading_lot",
    label: "Leitura do lote",
    detail: "CSV em leitura.",
  },
  {
    id: "indexing_global",
    label: "Indexação global",
    detail: "Itens e duplicidades em mapeamento.",
  },
  {
    id: "validating_batches",
    label: "Validação",
    detail: "Prévia liberada por partes.",
  },
  {
    id: "building_artifacts",
    label: "Arquivos finais",
    detail: "Resumo, CSV e PDF em geração.",
  },
  {
    id: "report_ready",
    label: "Relatório pronto",
    detail: "Arquivos disponíveis.",
  },
] as const;

export const FIELD_LABELS: Record<string, string> = {
  item: "Item",
  descricao: "Descrição",
  marca: "Marca",
  modelo: "Modelo",
  complemento: "Complemento",
  observacao: "Observação",
  ns: "NS",
  placa_anterior: "Placa anterior",
  flag_item_coletado: "Indicador de coleta",
  flag_item_cadastrado_do_zero: "Indicador de cadastro novo",
  local: "Local",
  cc: "CC",
};

const CATEGORY_CHECK_LABELS: Record<string, string> = {
  btu_pattern: "capacidade em BTU",
  inches_pattern: "polegadas",
  ports_pattern: "quantidade de portas",
  channels_pattern: "quantidade de canais",
  liters_pattern: "capacidade em litros",
};

export const INITIAL_PROBLEM_OCCURRENCES = 20;
export const PROBLEM_OCCURRENCES_STEP = 20;

export function normalizeValidationScope(value: string | null | undefined): ValidationScope {
  if (value === "all_items" || value === "duplicate_items") {
    return value;
  }

  return "zero_items";
}

export function isAllItemsScope(scope: ValidationScope): boolean {
  return normalizeValidationScope(scope) === "all_items";
}

export function isDuplicateItemsScope(scope: ValidationScope): boolean {
  return normalizeValidationScope(scope) === "duplicate_items";
}

export function isZeroItemsScope(scope: ValidationScope): boolean {
  return normalizeValidationScope(scope) === "zero_items";
}

export function getValidationScopeLabel(scope: ValidationScope): string {
  if (isAllItemsScope(scope)) {
    return "Todos os itens";
  }

  if (isDuplicateItemsScope(scope)) {
    return "Somente duplicados";
  }

  return "Itens cadastrados do zero";
}

export function buildFinalScopeCopy(scope: ValidationScope): string {
  if (isAllItemsScope(scope)) {
    return "Todos os itens foram validados. PDF, JSON e CSV estão disponíveis.";
  }

  if (isDuplicateItemsScope(scope)) {
    return "Itens duplicados validados. PDF, JSON e CSV estão disponíveis.";
  }

  return "Itens cadastrados do zero validados. PDF, JSON e CSV estão disponíveis.";
}

export function formatFieldName(field: string | null | undefined): string {
  if (!field) {
    return "Revisão geral";
  }

  return FIELD_LABELS[field] || field;
}

export function resolveEditableField(occurrence: ProblemOccurrence): string | null {
  if (!occurrence.field) {
    return null;
  }

  if (
    occurrence.field === "flag_item_coletado" ||
    occurrence.field === "flag_item_cadastrado_do_zero"
  ) {
    return "placa_anterior";
  }

  return occurrence.field;
}

export function lineNumber(rowIndex: number): number {
  return rowIndex + 2;
}

export function slugify(value: string): string {
  return value
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

export function getValidatedTotalRows(summary: Partial<SummaryPayload>): number {
  return Number(summary.validated_rows ?? summary.total_rows ?? 0);
}

export function getSourceTotalRows(summary: Partial<SummaryPayload>): number {
  return Number(summary.source_total_rows ?? getValidatedTotalRows(summary));
}

export function buildScopeSummaryCopy(
  summary: Partial<SummaryPayload>,
  validationScope: ValidationScope,
): string {
  const validatedRows = getValidatedTotalRows(summary);
  const sourceTotalRows = getSourceTotalRows(summary);

  if (isDuplicateItemsScope(validationScope)) {
    if (sourceTotalRows !== validatedRows) {
      return `Somente duplicados. CSV original: ${sourceTotalRows} linhas.`;
    }

    return "Todas as linhas são de itens duplicados.";
  }

  if (sourceTotalRows !== validatedRows) {
    return `Somente itens novos. CSV original: ${sourceTotalRows} linhas.`;
  }

  return "Todas as linhas entraram no escopo.";
}

function humanizeCategoryToken(categoryToken: string): string {
  return categoryToken.replaceAll("_", " ").trim().toUpperCase();
}

function parseCategoryRequiredCode(code: string): {
  categoryLabel: string;
  fieldName: string;
  fieldLabel: string;
} | null {
  if (!code.startsWith("CATEGORY_") || !code.endsWith("_REQUIRED")) {
    return null;
  }

  for (const [fieldName, fieldLabel] of Object.entries(FIELD_LABELS)) {
    const suffix = `_${fieldName.toUpperCase()}_REQUIRED`;
    if (!code.endsWith(suffix)) {
      continue;
    }

    const categoryToken = code.slice("CATEGORY_".length, -suffix.length);
    if (!categoryToken) {
      return null;
    }

    return {
      categoryLabel: humanizeCategoryToken(categoryToken),
      fieldName,
      fieldLabel,
    };
  }

  return null;
}

function parseCategoryCriticalCode(code: string): {
  categoryLabel: string;
  checkName: string;
  requirementLabel: string;
} | null {
  if (!code.startsWith("CATEGORY_") || !code.endsWith("_MISSING")) {
    return null;
  }

  for (const [checkName, requirementLabel] of Object.entries(CATEGORY_CHECK_LABELS)) {
    const suffix = `_${checkName.toUpperCase()}_MISSING`;
    if (!code.endsWith(suffix)) {
      continue;
    }

    const categoryToken = code.slice("CATEGORY_".length, -suffix.length);
    if (!categoryToken) {
      return null;
    }

    return {
      categoryLabel: humanizeCategoryToken(categoryToken),
      checkName,
      requirementLabel,
    };
  }

  return null;
}

function parseCategoryCriticalPlacement(message: string | null | undefined): string | null {
  if (!message) {
    return null;
  }

  const match = message.match(/^Espécie '.*': informar .* em (.+)$/);
  return match?.[1] || null;
}

export function describeIssue(
  code: string,
  message?: string | null,
): {
  title: string;
  context: string;
  impact: string;
  action: string;
} {
  if (code === "DUPLICATE_ITEM") {
    return {
      title: "Identificador patrimonial repetido",
      context: "Mais de uma linha está usando o mesmo item patrimonial dentro do mesmo lote.",
      impact: "A equipe pode tratar bens distintos como se fossem o mesmo registro, gerando retrabalho e conciliação incorreta.",
      action: "Defina qual linha deve manter o código atual e ajuste as demais para que cada bem tenha um item único.",
    };
  }

  if (code.startsWith("ZERO_ITEM_COMPLEMENTO_")) {
    return {
      title: "Detalhamento insuficiente para item novo",
      context: "O bem foi cadastrado do zero, mas ainda não traz informação suficiente para ser identificado sem ambiguidade.",
      impact: "O ativo perde rastreabilidade e a equipe passa a depender de contexto informal para reconhecer o registro.",
      action: "Complete o complemento com características objetivas, como material, cor, capacidade, localização ou outra referência verificável.",
    };
  }

  if (code === "ZERO_ITEM_MARCA_MISSING") {
    return {
      title: "Marca não informada",
      context: "O item novo foi registrado sem a marca do fabricante.",
      impact: "Fica mais difícil comprovar a identidade do bem e comparar a planilha com a etiqueta física ou documentos de origem.",
      action: "Confirme a marca no equipamento, etiqueta ou documento do bem e preencha a coluna correspondente.",
    };
  }

  if (code === "ZERO_ITEM_MODELO_MISSING") {
    return {
      title: "Modelo não informado",
      context: "O item novo foi registrado sem o modelo do fabricante.",
      impact: "A ausência do modelo reduz a precisão do cadastro e dificulta a revisão patrimonial posterior.",
      action: "Preencha o modelo exato informado na etiqueta técnica, caixa ou nota do equipamento.",
    };
  }

  if (code.startsWith("FLAG_CONSISTENCY")) {
    return {
      title: "Identificação anterior inconsistente",
      context: "Os indicadores internos do cadastro não estão coerentes com a existência ou ausência de placa anterior.",
      impact: "O histórico do bem fica incoerente e compromete a leitura sobre origem, coleta anterior e tratamento do item.",
      action: "Revise a identificação de origem do bem e ajuste a informação anterior antes de reenviar o lote.",
    };
  }

  const categoryRequired = parseCategoryRequiredCode(code);
  if (categoryRequired) {
    return {
      title: `${categoryRequired.categoryLabel}: preencher ${categoryRequired.fieldLabel}`,
      context: `Itens classificados como ${categoryRequired.categoryLabel} precisam preencher ${categoryRequired.fieldLabel} para identificação patrimonial adequada.`,
      impact: `Sem ${categoryRequired.fieldLabel}, o registro continua fraco para conferência operacional e exige interpretação manual adicional.`,
      action: `Preencha ${categoryRequired.fieldLabel} seguindo o padrão patrimonial adotado para itens da espécie ${categoryRequired.categoryLabel}.`,
    };
  }

  const categoryCritical = parseCategoryCriticalCode(code);
  if (categoryCritical) {
    const targetPlacement = parseCategoryCriticalPlacement(message) || "Complemento";
    return {
      title: `${categoryCritical.categoryLabel}: informar ${categoryCritical.requirementLabel}`,
      context: `Itens da espécie ${categoryCritical.categoryLabel} precisam trazer ${categoryCritical.requirementLabel} em ${targetPlacement}.`,
      impact: "Sem esse detalhe técnico, a identificação do bem fica incompleta e a conciliação patrimonial exige verificação manual adicional.",
      action: `Inclua ${categoryCritical.requirementLabel} em ${targetPlacement}, conforme o padrão de cadastro usado para essa espécie.`,
    };
  }

  if (code.startsWith("LLM_AUDIT_FINDING")) {
    return {
      title: "Revisão textual do cadastro",
      context: "A análise semântica encontrou um ponto de qualidade que pode enfraquecer a leitura operacional do registro.",
      impact: "O texto do cadastro fica menos preciso e reduz a confiança sobre o reconhecimento do bem.",
      action: "Ajuste descrição, marca, modelo, NS, complemento ou observação para deixar o item mais específico e verificável.",
    };
  }

  if (code === "LLM_AUDIT_FAILURE" || code === "LLM_AUDIT_PROMPT_NOT_FOUND") {
    return {
      title: "Falha na auditoria automática",
      context: "A etapa complementar de auditoria textual não conseguiu concluir a execução.",
      impact: "Não se trata de uma correção de planilha para a equipe patrimonial, mas de uma ocorrência de suporte do sistema.",
      action: "Encaminhe o caso para suporte técnico. O lote pode seguir sendo corrigido pelos demais apontamentos disponíveis.",
    };
  }

  return {
    title: code.replaceAll("_", " "),
    context: "O validador agrupou linhas com o mesmo tipo de apontamento para facilitar o tratamento operacional.",
    impact: "Enquanto esse grupo permanecer aberto, o lote continua com pendências de correção ou consistência.",
    action: "Revise as linhas listadas, confira o campo destacado e aplique o ajuste indicado na mensagem do validador.",
  };
}

export function formatDateTime(value: string | null | undefined): string {
  if (!value) {
    return "-";
  }

  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) {
    return value;
  }

  return new Intl.DateTimeFormat("pt-BR", {
    dateStyle: "short",
    timeStyle: "short",
  }).format(parsed);
}

export function formatStatusChip(
  job:
    | {
        status: JobStatusResponse["status"] | JobListItemResponse["status"];
        cancel_requested: boolean;
        is_partial_result_available?: boolean;
      }
    | null,
): StatusChip {
  if (job?.cancel_requested) {
    return { label: "Cancelando", kind: "warning" };
  }

  if (job?.status === "queued") {
    return { label: "Recebido", kind: "info" };
  }

  if (job?.status === "canceled") {
    return { label: "Cancelado", kind: "warning" };
  }

  if (job?.status === "completed") {
    return { label: "Consolidado", kind: "success" };
  }

  if (job?.status === "failed") {
    return { label: "Falha", kind: "error" };
  }

  if (job?.is_partial_result_available) {
    return { label: "Prévia disponível", kind: "warning" };
  }

  return { label: "Em processamento", kind: "info" };
}

export function describeJobProgress(
  job: Pick<
    JobStatusResponse | JobListItemResponse,
    "status" | "cancel_requested" | "status_detail" | "processed_rows" | "total_rows"
  >,
): string {
  if (job.cancel_requested) {
    return job.status_detail || "Interrompendo processamento.";
  }

  if (job.status === "queued") {
    return "Aguardando processamento.";
  }

  if (job.status === "running") {
    if (job.total_rows > 0) {
      return `${job.processed_rows} de ${job.total_rows} itens processados.`;
    }

    return job.status_detail || "Processando lote.";
  }

  if (job.status === "canceled") {
    return job.status_detail || "Lote interrompido.";
  }

  return job.status_detail || "Sem detalhes adicionais.";
}

export function buildPreviewReportData(job: JobStatusResponse | null): PreviewReportPayload | null {
  if (!job?.is_partial_result_available) {
    return null;
  }

  return {
    summary: job.partial_summary,
    duplicates: job.partial_duplicates,
    grouped_problems: job.partial_grouped_problems,
    row_results: job.row_results_preview,
  };
}

export function buildScopeSummary(occurrences: ProblemOccurrence[]): string {
  const lines = occurrences
    .map((occurrence) => lineNumber(occurrence.row_index))
    .sort((left, right) => left - right);
  const uniqueFields = [...new Set(occurrences.map((occurrence) => formatFieldName(occurrence.field)))];
  const preview = lines.slice(0, 5).join(", ");
  const suffix = lines.length > 5 ? ", ..." : "";

  return `${occurrences.length} linha(s). Campos: ${uniqueFields.join(", ")}. Linhas: ${preview}${suffix}.`;
}

export function isJobTerminal(job: JobStatusResponse | null): boolean {
  return Boolean(job && (job.status === "completed" || job.status === "failed" || job.status === "canceled"));
}

export function getDuplicateSuggestedKeepRow(duplicate: DuplicateGroup): number | null {
  if (!duplicate.row_indices.length) {
    return null;
  }

  return [...duplicate.row_indices].sort((left, right) => left - right).at(-1) ?? null;
}
