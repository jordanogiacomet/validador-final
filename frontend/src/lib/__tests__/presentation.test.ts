import { describe, expect, it } from "vitest";

import {
  buildScopeSummaryCopy,
  describeIssue,
  formatStatusChip,
  getValidationScopeLabel,
  normalizeValidationScope,
} from "@/lib/presentation";

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
