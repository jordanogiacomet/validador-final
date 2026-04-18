import { describe, expect, it } from "vitest";

import {
  buildResultFilterGroups,
  buildScopeSummaryCopy,
  describeIssue,
  filterDuplicates,
  filterDuplicatesForResultSearch,
  filterProblemGroupsForReviewFlags,
  filterProblemGroupsForResultView,
  filterProblemGroupsForResultSearch,
  formatStatusChip,
  getBulkConsolidatableSameNameDuplicates,
  getDuplicateFilterCounts,
  getReviewFlaggedRowCount,
  getValidationScopeLabel,
  hasActiveResultFilters,
  hasDuplicateDescriptionConflict,
  isRowMarkedForReview,
  normalizeValidationScope,
  normalizeSearchText,
  resetResultFilterState,
  resetResultSearchState,
  toggleResultFilter,
} from "@/lib/presentation";
import type { DuplicateGroup, ProblemOccurrence } from "@/lib/types";

describe("presentation helpers", () => {
  it("normalizes unknown validation scope to zero_items", () => {
    expect(normalizeValidationScope("unexpected")).toBe("zero_items");
  });

  it("builds zero-items summary copy when source rows exceed validated rows", () => {
    expect(
      buildScopeSummaryCopy({
        total_rows: 3,
        validated_rows: 3,
        source_total_rows: 9,
        rows_with_issues: 0,
        total_issues: 0,
        error_count: 0,
        warning_count: 0,
      }, "zero_items"),
    ).toContain("CSV original: 9 linhas");
  });

  it("keeps duplicate-items scope when normalizing", () => {
    expect(normalizeValidationScope("duplicate_items")).toBe("duplicate_items");
  });

  it("labels duplicate-items scope clearly", () => {
    expect(getValidationScopeLabel("duplicate_items")).toBe("Somente duplicados");
  });

  it("builds duplicate-items summary copy when source rows exceed validated rows", () => {
    expect(
      buildScopeSummaryCopy({
        total_rows: 2,
        validated_rows: 2,
        source_total_rows: 9,
        rows_with_issues: 0,
        total_issues: 0,
        error_count: 0,
        warning_count: 0,
      }, "duplicate_items"),
    ).toContain("Somente duplicados");
  });

  it("describes duplicate issues with operational copy", () => {
    expect(describeIssue("DUPLICATE_ITEM").title).toBe("Identificador patrimonial repetido");
  });

  it("treats explicit duplicate description conflicts as vermelho", () => {
    expect(
      hasDuplicateDescriptionConflict({
        item: "1100",
        descricao: "Mesa",
        has_description_conflict: true,
        row_indices: [0, 1],
        count: 2,
      }),
    ).toBe(true);
  });

  it("filters duplicate groups between normal and vermelho cards", () => {
    const duplicates: DuplicateGroup[] = [
      {
        item: "1100",
        descricao: "Mesa",
        row_indices: [0, 1],
        count: 2,
      },
      {
        item: "2200",
        descricao: "Mesa / Cadeira",
        row_indices: [4, 9],
        count: 2,
      },
    ];

    expect(filterDuplicates(duplicates, "all")).toHaveLength(2);
    expect(filterDuplicates(duplicates, "normal")).toEqual([duplicates[0]]);
    expect(filterDuplicates(duplicates, "conflict")).toEqual([duplicates[1]]);
  });

  it("matches result search without case or accent sensitivity", () => {
    const groupedProblems: Record<string, ProblemOccurrence[]> = {
      ZERO_ITEM_COMPLEMENTO_SHORT: [
        {
          row_index: 0,
          item: "1100",
          descricao: "Ar Condicionado",
          severity: "warning",
          message: "Complemento muito curto para ÁREA técnica",
          field: "complemento",
        },
        {
          row_index: 1,
          item: "2200",
          descricao: "Mesa administrativa",
          severity: "warning",
          message: "Marca ausente",
          field: "marca",
        },
      ],
    };

    expect(normalizeSearchText("  ÁREA   TÉCNICA ")).toBe("area tecnica");
    expect(filterProblemGroupsForResultSearch(groupedProblems, "area tecnica")).toEqual({
      ZERO_ITEM_COMPLEMENTO_SHORT: [groupedProblems.ZERO_ITEM_COMPLEMENTO_SHORT[0]],
    });
    expect(filterProblemGroupsForResultSearch(groupedProblems, "linha 3")).toEqual({
      ZERO_ITEM_COMPLEMENTO_SHORT: [groupedProblems.ZERO_ITEM_COMPLEMENTO_SHORT[1]],
    });
  });

  it("combines result search with duplicate display filters", () => {
    const duplicates: DuplicateGroup[] = [
      {
        item: "1100",
        descricao: "Mesa São Paulo",
        row_indices: [0, 1],
        count: 2,
      },
      {
        item: "2200",
        descricao: "Cadeira / Poltrona",
        has_description_conflict: true,
        row_indices: [4, 9],
        count: 2,
      },
    ];

    expect(filterDuplicatesForResultSearch(duplicates, "normal", "sao paulo")).toEqual([
      duplicates[0],
    ]);
    expect(filterDuplicatesForResultSearch(duplicates, "conflict", "cadeira")).toEqual([
      duplicates[1],
    ]);
    expect(filterDuplicatesForResultSearch(duplicates, "normal", "cadeira")).toEqual([]);
    expect(getDuplicateFilterCounts(duplicates, "cadeira")).toEqual({
      all: 1,
      normal: 0,
      conflict: 1,
    });
  });

  it("tracks rows marked for later review", () => {
    const reviewFlags = [
      { row_index: 1, status: "review" as const },
      { row_index: 4, status: "review" as const },
      { row_index: 1, status: "review" as const },
    ];

    expect(isRowMarkedForReview(reviewFlags, 1)).toBe(true);
    expect(isRowMarkedForReview(reviewFlags, 2)).toBe(false);
    expect(getReviewFlaggedRowCount(reviewFlags)).toBe(2);
  });

  it("filters problem occurrences to rows marked for later review", () => {
    const groupedProblems: Record<string, ProblemOccurrence[]> = {
      ZERO_ITEM_COMPLEMENTO_EMPTY: [
        {
          row_index: 0,
          item: "1100",
          descricao: "Mesa",
          severity: "warning",
          message: "Complemento vazio",
          field: "complemento",
        },
        {
          row_index: 2,
          item: "2200",
          descricao: "Cadeira",
          severity: "warning",
          message: "Complemento vazio",
          field: "complemento",
        },
      ],
    };

    expect(
      filterProblemGroupsForReviewFlags(
        groupedProblems,
        [{ row_index: 2, status: "review" }],
        true,
      ),
    ).toEqual({
      ZERO_ITEM_COMPLEMENTO_EMPTY: [groupedProblems.ZERO_ITEM_COMPLEMENTO_EMPTY[1]],
    });
  });

  it("combines search, duplicate filters, and review markers", () => {
    const duplicates: DuplicateGroup[] = [
      {
        item: "1100",
        descricao: "Mesa",
        row_indices: [0, 1],
        count: 2,
      },
      {
        item: "2200",
        descricao: "Cadeira / Poltrona",
        has_description_conflict: true,
        row_indices: [4, 9],
        count: 2,
      },
    ];
    const reviewFlags = [{ row_index: 9, status: "review" as const }];

    expect(
      filterDuplicatesForResultSearch(duplicates, "conflict", "poltrona", reviewFlags, true),
    ).toEqual([duplicates[1]]);
    expect(filterDuplicatesForResultSearch(duplicates, "normal", "", reviewFlags, true)).toEqual(
      [],
    );
    expect(getDuplicateFilterCounts(duplicates, "", reviewFlags, true)).toEqual({
      all: 1,
      normal: 0,
      conflict: 1,
    });
  });

  it("combines severity, rule, and category result filters with AND semantics", () => {
    const groupedProblems: Record<string, ProblemOccurrence[]> = {
      CATEGORY_MONITOR_COMPLEMENTO_REQUIRED: [
        {
          row_index: 0,
          item: "1100",
          descricao: "Monitor Dell",
          severity: "warning",
          message: "Espécie 'MONITOR': preencher Complemento",
          field: "complemento",
        },
      ],
      CATEGORY_MONITOR_INCHES_PATTERN_MISSING: [
        {
          row_index: 1,
          item: "2200",
          descricao: "Monitor LG",
          severity: "error",
          message: "Espécie 'MONITOR': informar polegadas em Complemento",
          field: "complemento",
        },
      ],
      ZERO_ITEM_MARCA_MISSING: [
        {
          row_index: 2,
          item: "3300",
          descricao: "Cadeira",
          severity: "warning",
          message: "Marca ausente",
          field: "marca",
        },
      ],
    };

    expect(
      filterProblemGroupsForResultView(groupedProblems, "", {
        severity: "warning",
        rule: "CATEGORY_MONITOR_COMPLEMENTO_REQUIRED",
        category: "monitor",
      }),
    ).toEqual({
      CATEGORY_MONITOR_COMPLEMENTO_REQUIRED: [
        groupedProblems.CATEGORY_MONITOR_COMPLEMENTO_REQUIRED[0],
      ],
    });

    expect(
      filterProblemGroupsForResultView(groupedProblems, "", {
        severity: "error",
        rule: "CATEGORY_MONITOR_COMPLEMENTO_REQUIRED",
        category: "monitor",
      }),
    ).toEqual({});
  });

  it("builds coherent result filter chip counts from the other active filters", () => {
    const groupedProblems: Record<string, ProblemOccurrence[]> = {
      CATEGORY_MONITOR_COMPLEMENTO_REQUIRED: [
        {
          row_index: 0,
          item: "1100",
          descricao: "Monitor Dell",
          severity: "warning",
          message: "Espécie 'MONITOR': preencher Complemento",
          field: "complemento",
        },
      ],
      CATEGORY_MONITOR_INCHES_PATTERN_MISSING: [
        {
          row_index: 1,
          item: "2200",
          descricao: "Monitor LG",
          severity: "error",
          message: "Espécie 'MONITOR': informar polegadas em Complemento",
          field: "complemento",
        },
      ],
      CATEGORY_TV_INCHES_PATTERN_MISSING: [
        {
          row_index: 2,
          item: "3300",
          descricao: "TV Samsung",
          severity: "warning",
          message: "Espécie 'TV': informar polegadas em Complemento",
          field: "complemento",
        },
      ],
    };

    const filterGroups = buildResultFilterGroups(groupedProblems, "", {
      severity: "warning",
      rule: null,
      category: "monitor",
    });

    expect(filterGroups.find((group) => group.dimension === "severity")?.options).toEqual([
      { value: "error", label: "Erros", count: 1, active: false, kind: "error" },
      { value: "warning", label: "Avisos", count: 1, active: true, kind: "warning" },
    ]);
    expect(filterGroups.find((group) => group.dimension === "rule")?.options).toEqual([
      {
        value: "CATEGORY_MONITOR_COMPLEMENTO_REQUIRED",
        label: "MONITOR: preencher Complemento",
        count: 1,
        active: false,
      },
    ]);
    expect(filterGroups.find((group) => group.dimension === "category")?.options).toEqual([
      { value: "monitor", label: "MONITOR", count: 1, active: true },
      { value: "tv", label: "TV", count: 1, active: false },
    ]);
  });

  it("omits category filters when the result has no category-backed issues", () => {
    const groupedProblems: Record<string, ProblemOccurrence[]> = {
      ZERO_ITEM_MARCA_MISSING: [
        {
          row_index: 0,
          item: "1100",
          descricao: "Mesa",
          severity: "warning",
          message: "Marca ausente",
          field: "marca",
        },
      ],
    };

    expect(
      buildResultFilterGroups(groupedProblems, "", resetResultFilterState()).some(
        (group) => group.dimension === "category",
      ),
    ).toBe(false);
  });

  it("resets and toggles result filter state", () => {
    const blankFilters = resetResultFilterState();

    expect(hasActiveResultFilters(blankFilters)).toBe(false);
    expect(toggleResultFilter(blankFilters, "severity", "warning")).toEqual({
      severity: "warning",
      rule: null,
      category: null,
    });
    expect(
      toggleResultFilter(
        { severity: "warning", rule: "ZERO_ITEM_MARCA_MISSING", category: "monitor" },
        "severity",
        "warning",
      ),
    ).toEqual({
      severity: null,
      rule: "ZERO_ITEM_MARCA_MISSING",
      category: "monitor",
    });
    expect(resetResultFilterState()).toEqual({
      severity: null,
      rule: null,
      category: null,
    });
  });

  it("builds a blank result search state when the active job changes", () => {
    expect(resetResultSearchState("job-2")).toEqual({
      jobId: "job-2",
      input: "",
      debouncedQuery: "",
    });
  });

  it("returns only same-name duplicate groups with exactly two occurrences for bulk consolidation", () => {
    const duplicates: DuplicateGroup[] = [
      {
        item: "3300",
        descricao: "Mesa",
        row_indices: [2, 4],
        count: 2,
      },
      {
        item: "1100",
        descricao: "Mesa",
        row_indices: [0, 1, 3],
        count: 3,
      },
      {
        item: "2200",
        descricao: "Mesa / Cadeira",
        row_indices: [10, 12],
        count: 2,
      },
      {
        item: "4400",
        descricao: "Armário",
        row_indices: [8, 9],
        count: 2,
      },
    ];

    expect(getBulkConsolidatableSameNameDuplicates(duplicates)).toEqual([
      duplicates[3],
      duplicates[0],
    ]);
  });

  it("uses the backend target field for category critical operational copy", () => {
    const guide = describeIssue(
      "CATEGORY_TANQUE_METALICO_LITERS_PATTERN_MISSING",
      "Espécie 'TANQUE METALICO': informar capacidade em litros em Complemento",
    );

    expect(guide.context).toContain("em Complemento");
    expect(guide.action).toContain("em Complemento");
  });

  it("formats cancel requested state as cancelando", () => {
    expect(
      formatStatusChip({
        status: "running",
        cancel_requested: true,
        is_partial_result_available: false,
      }),
    ).toEqual({ label: "Cancelando", kind: "warning" });
  });

  it("formats partial result state with concise copy", () => {
    expect(
      formatStatusChip({
        status: "running",
        cancel_requested: false,
        is_partial_result_available: true,
      }),
    ).toEqual({ label: "Prévia disponível", kind: "warning" });
  });
});
