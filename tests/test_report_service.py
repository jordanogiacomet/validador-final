from pathlib import Path

from app.core.issue import ValidationIssue
from app.core.validation_scope import ValidationScope
from app.services.report_service import (
    _build_scope_note,
    _describe_issue,
    _sorted_problem_groups,
    build_duplicate_section,
    build_duplicates_export_csv,
    build_full_report,
    build_grouped_problems,
    build_partial_report,
    build_problem_group_export_csv,
    build_row_results,
    generate_pdf_report,
)


def _make_issue(code="TEST", severity="error", message="test msg", field="item", meta=None):
    return ValidationIssue(
        code=code,
        severity=severity,
        message=message,
        field=field,
        meta=meta,
    )


def _sample_rows():
    return [
        {"item": "A001", "descricao": "Mesa", "placa_anterior": "P1",
         "flag_item_coletado": 1, "flag_item_cadastrado_do_zero": 0},
        {"item": "A002", "descricao": "Cadeira", "placa_anterior": None,
         "flag_item_coletado": 0, "flag_item_cadastrado_do_zero": 1},
        {"item": "A001", "descricao": "Mesa", "placa_anterior": "P3",
         "flag_item_coletado": 1, "flag_item_cadastrado_do_zero": 0},
    ]


# --- build_row_results ---

def test_build_row_results_basic():
    rows = _sample_rows()
    results = {0: [_make_issue()], 1: [], 2: [_make_issue(severity="warning")]}
    output = build_row_results(rows, results)
    assert len(output) == 3
    assert output[0]["row_index"] == 0
    assert output[0]["item"] == "A001"
    assert output[0]["has_errors"] is True
    assert output[0]["has_warnings"] is False
    assert output[1]["has_errors"] is False
    assert output[2]["has_warnings"] is True


def test_build_row_results_empty():
    output = build_row_results([], {})
    assert output == []


def test_build_row_results_no_issues():
    rows = _sample_rows()
    output = build_row_results(rows, {})
    assert all(r["has_errors"] is False for r in output)
    assert all(r["has_warnings"] is False for r in output)
    assert all(r["issues"] == [] for r in output)


def test_build_row_results_includes_descricao():
    rows = [{"item": "X", "descricao": "Impressora"}]
    output = build_row_results(rows, {})
    assert output[0]["descricao"] == "Impressora"


def test_build_row_results_can_limit_to_processed_indices():
    rows = _sample_rows()
    results = {0: [_make_issue()], 2: [_make_issue(code="OTHER")]}
    output = build_row_results(rows, results, row_indices=[0, 2])
    assert [entry["row_index"] for entry in output] == [0, 2]


# --- build_duplicate_section ---

def test_duplicate_section_finds_duplicates():
    rows = _sample_rows()
    dups = build_duplicate_section(rows, {})
    assert len(dups) == 1
    assert dups[0]["item"] == "A001"
    assert dups[0]["descricao"] == "Mesa"
    assert dups[0]["has_description_conflict"] is False
    assert dups[0]["count"] == 2
    assert set(dups[0]["row_indices"]) == {0, 2}


def test_duplicate_section_flags_different_descriptions():
    rows = [
        {"item": "A001", "descricao": "Mesa"},
        {"item": "A001", "descricao": "Cadeira"},
    ]
    dups = build_duplicate_section(rows, {})

    assert dups[0]["descricao"] == "Mesa / Cadeira"
    assert dups[0]["has_description_conflict"] is True


def test_duplicate_section_no_duplicates():
    rows = [{"item": "A"}, {"item": "B"}, {"item": "C"}]
    dups = build_duplicate_section(rows, {})
    assert dups == []


def test_duplicate_section_ignores_none_items():
    rows = [{"item": None}, {"item": None}, {"item": "A"}]
    dups = build_duplicate_section(rows, {})
    assert dups == []


def test_duplicate_section_multiple_groups():
    rows = [{"item": "A"}, {"item": "B"}, {"item": "A"}, {"item": "B"}]
    dups = build_duplicate_section(rows, {})
    assert len(dups) == 2


def test_duplicate_section_can_limit_to_validated_scope():
    rows = _sample_rows()
    dups = build_duplicate_section(rows, {}, row_indices=[1])
    assert dups == []


# --- build_grouped_problems ---

def test_grouped_problems_groups_by_code():
    rows = _sample_rows()
    results = {
        0: [_make_issue(code="DUP"), _make_issue(code="FLAG")],
        1: [_make_issue(code="DUP")],
    }
    grouped = build_grouped_problems(rows, results)
    assert len(grouped["DUP"]) == 2
    assert len(grouped["FLAG"]) == 1


def test_grouped_problems_empty():
    grouped = build_grouped_problems([], {})
    assert grouped == {}


def test_grouped_problems_preserves_details():
    rows = [{"item": "A001", "descricao": "Mesa"}]
    results = {5: [_make_issue(code="X", severity="warning", message="msg", field="f")]}
    grouped = build_grouped_problems(rows, results)
    entry = grouped["X"][0]
    assert entry["row_index"] == 5
    assert entry["item"] is None
    assert entry["descricao"] is None
    assert entry["severity"] == "warning"
    assert entry["message"] == "msg"
    assert entry["field"] == "f"


def test_grouped_problems_include_item_and_descricao():
    rows = _sample_rows()
    results = {1: [_make_issue(code="ZERO", severity="warning", message="Marca vazia")]}
    grouped = build_grouped_problems(rows, results)

    entry = grouped["ZERO"][0]
    assert entry["item"] == "A002"
    assert entry["descricao"] == "Cadeira"


def test_build_duplicates_export_csv_formats_operational_columns():
    csv_output = build_duplicates_export_csv(
        [
            {
                "item": "A001",
                "descricao": "Mesa",
                "row_indices": [0, 2],
                "count": 2,
            }
        ]
    )

    assert "Item,Descrição,Quantidade de Ocorrências,Linhas Envolvidas" in csv_output
    assert "A001,Mesa,2,\"2, 4\"" in csv_output


def test_build_problem_group_export_csv_formats_operational_rows():
    csv_output = build_problem_group_export_csv(
        "ZERO_ITEM_COMPLEMENTO_EMPTY",
        [
            {
                "row_index": 1,
                "item": "A002",
                "descricao": "Cadeira",
                "severity": "warning",
                "field": "complemento",
                "message": "Complemento vazio",
            }
        ],
    )

    assert "Código,Linha,Item,Descrição,Severidade,Campo,Mensagem" in csv_output
    assert (
        "ZERO_ITEM_COMPLEMENTO_EMPTY,3,A002,Cadeira,warning,Complemento,"
        "Complemento vazio" in csv_output
    )


def test_describe_issue_for_category_required_is_specific():
    guide = _describe_issue("CATEGORY_MONITOR_COMPLEMENTO_REQUIRED")

    assert guide["title"] == "MONITOR: preencher Complemento"
    assert "MONITOR" in guide["context"]
    assert "Complemento" in guide["action"]


def test_describe_issue_for_category_critical_uses_portuguese_requirement():
    guide = _describe_issue("CATEGORY_TANQUE_METALICO_LITERS_PATTERN_MISSING")

    assert guide["title"] == "TANQUE METALICO: informar capacidade em litros"
    assert "capacidade em litros" in guide["context"]
    assert "em Complemento" in guide["context"]
    assert "liters_pattern" not in guide["context"]
    assert "capacidade em litros" in guide["action"]


def test_describe_issue_for_category_critical_can_use_message_target_field():
    guide = _describe_issue(
        "CATEGORY_TANQUE_METALICO_LITERS_PATTERN_MISSING",
        "Espécie 'TANQUE METALICO': informar capacidade em litros em Complemento",
    )

    assert "em Complemento" in guide["context"]
    assert "em Complemento" in guide["action"]


def test_build_scope_note_can_describe_duplicate_scope():
    note = _build_scope_note(
        {
            "total_rows": 2,
            "source_total_rows": 5,
            "rows_with_issues": 0,
            "total_issues": 0,
            "error_count": 0,
            "warning_count": 0,
        },
        ValidationScope.DUPLICATE_ITEMS,
    )

    assert "Item duplicado" in note
    assert "5 linhas" in note


# --- build_full_report ---

def test_full_report_summary():
    rows = _sample_rows()
    results = {
        0: [_make_issue(severity="error")],
        1: [_make_issue(severity="warning")],
        2: [],
    }
    report = build_full_report(rows, results)
    s = report["summary"]
    assert s["total_rows"] == 3
    assert s["rows_with_issues"] == 2
    assert s["total_issues"] == 2
    assert s["error_count"] == 1
    assert s["warning_count"] == 1


def test_full_report_contains_all_sections():
    rows = _sample_rows()
    results = {0: [_make_issue()]}
    report = build_full_report(rows, results)
    assert "summary" in report
    assert "row_results" in report
    assert "duplicates" in report
    assert "grouped_problems" in report


def test_full_report_empty_input():
    report = build_full_report([], {})
    assert report["summary"]["total_rows"] == 0
    assert report["row_results"] == []
    assert report["duplicates"] == []
    assert report["grouped_problems"] == {}


def test_full_report_all_clean():
    rows = [{"item": "A"}, {"item": "B"}]
    results = {0: [], 1: []}
    report = build_full_report(rows, results)
    assert report["summary"]["rows_with_issues"] == 0
    assert report["summary"]["total_issues"] == 0


def test_full_report_can_limit_to_scope_and_keep_source_total_rows():
    rows = _sample_rows()
    results = {
        0: [_make_issue(code="OUT_OF_SCOPE")],
        1: [_make_issue(code="ZERO_SCOPE")],
        2: [_make_issue(code="OUT_OF_SCOPE_2")],
    }

    report = build_full_report(
        rows,
        results,
        validated_row_indices=[1],
        source_total_rows=3,
    )

    assert report["summary"]["total_rows"] == 1
    assert report["summary"]["validated_rows"] == 1
    assert report["summary"]["source_total_rows"] == 3
    assert [row["row_index"] for row in report["row_results"]] == [1]
    assert list(report["grouped_problems"]) == ["ZERO_SCOPE"]
    assert report["duplicates"] == []


def test_full_report_includes_llm_audit_metadata():
    rows = [{"item": "A001", "descricao": "Mesa"}]
    results = {
        0: [
            _make_issue(
                code="LLM_AUDIT_FINDING_1",
                severity="warning",
                message="Auditoria LLM: revisar descricao",
                field="descricao",
                meta={
                    "prompt_version": "v2",
                    "model": "claude-sonnet-4-20250514",
                },
            )
        ]
    }

    report = build_full_report(rows, results)

    assert report["llm_audit"] == {
        "prompt_versions": ["v2"],
        "models": ["claude-sonnet-4-20250514"],
    }


def test_partial_report_limits_summary_and_rows_to_processed_slice():
    rows = _sample_rows()
    results = {
        0: [_make_issue(code="DUPLICATE_ITEM", severity="error")],
        1: [_make_issue(code="ZERO", severity="warning")],
        2: [_make_issue(code="LATE", severity="warning")],
    }

    preview = build_partial_report(
        rows,
        results,
        processed_row_indices=[0, 1],
        partial_duplicates=[{"item": "A001", "row_indices": [0, 2], "count": 2}],
    )

    assert preview["partial_summary"]["total_rows"] == 3
    assert preview["partial_summary"]["processed_rows"] == 2
    assert preview["partial_summary"]["rows_with_issues"] == 2
    assert preview["partial_summary"]["total_issues"] == 2
    assert preview["partial_summary"]["error_count"] == 1
    assert preview["partial_summary"]["warning_count"] == 1
    assert [row["row_index"] for row in preview["row_results_preview"]] == [0, 1]
    assert "LATE" not in preview["partial_grouped_problems"]
    assert preview["partial_duplicates"][0]["item"] == "A001"


def test_partial_report_can_limit_to_scope_and_keep_source_total_rows():
    rows = _sample_rows()
    results = {
        0: [_make_issue(code="OUT_OF_SCOPE")],
        1: [_make_issue(code="ZERO_SCOPE", severity="warning")],
    }

    preview = build_partial_report(
        rows,
        results,
        processed_row_indices=[1],
        validated_row_indices=[1],
        source_total_rows=3,
    )

    assert preview["partial_summary"]["total_rows"] == 1
    assert preview["partial_summary"]["validated_rows"] == 1
    assert preview["partial_summary"]["source_total_rows"] == 3
    assert preview["partial_summary"]["processed_rows"] == 1
    assert [row["row_index"] for row in preview["row_results_preview"]] == [1]
    assert list(preview["partial_grouped_problems"]) == ["ZERO_SCOPE"]
    assert preview["partial_duplicates"] == []


def test_partial_report_can_skip_row_results_preview_for_live_polling():
    rows = _sample_rows()
    results = {
        0: [_make_issue(code="DUPLICATE_ITEM", severity="error")],
        1: [_make_issue(code="ZERO_SCOPE", severity="warning")],
    }

    preview = build_partial_report(
        rows,
        results,
        processed_row_indices=[0, 1],
        include_row_results_preview=False,
    )

    assert preview["partial_summary"]["processed_rows"] == 2
    assert preview["row_results_preview"] == []
    assert "DUPLICATE_ITEM" in preview["partial_grouped_problems"]


def test_sorted_problem_groups_prioritize_errors_then_volume():
    grouped = {
        "WARN_BIG": [
            {"severity": "warning"},
            {"severity": "warning"},
            {"severity": "warning"},
        ],
        "ERR_SMALL": [{"severity": "error"}],
        "ERR_BIG": [{"severity": "error"}, {"severity": "error"}],
    }
    ordered = _sorted_problem_groups(grouped)
    assert [code for code, _ in ordered] == ["ERR_BIG", "ERR_SMALL", "WARN_BIG"]


# --- generate_pdf_report ---

def test_pdf_report_creates_file(tmp_path):
    rows = _sample_rows()
    results = {
        0: [_make_issue(code="DUPLICATE_ITEM", severity="error", message="Dup A001")],
        1: [_make_issue(code="ZERO_MISSING_MARCA", severity="warning", message="Marca vazia")],
        2: [],
    }
    pdf_path = tmp_path / "report.pdf"
    result = generate_pdf_report(rows, results, pdf_path)
    assert result == pdf_path
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_pdf_report_empty_data(tmp_path):
    pdf_path = tmp_path / "empty.pdf"
    result = generate_pdf_report([], {}, pdf_path)
    assert result == pdf_path
    assert pdf_path.exists()


def test_pdf_report_with_duplicates(tmp_path):
    rows = [{"item": "X"}, {"item": "X"}]
    results = {
        0: [_make_issue(code="DUPLICATE_ITEM")],
        1: [_make_issue(code="DUPLICATE_ITEM")],
    }
    pdf_path = tmp_path / "dup_report.pdf"
    generate_pdf_report(rows, results, pdf_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_pdf_report_accepts_string_path(tmp_path):
    pdf_path = str(tmp_path / "str_path.pdf")
    generate_pdf_report([{"item": "A"}], {}, pdf_path)
    assert Path(pdf_path).exists()


def test_pdf_report_accepts_metadata(tmp_path):
    pdf_path = tmp_path / "metadata.pdf"
    generate_pdf_report(
        [{"item": "A001", "descricao": "Mesa"}],
        {0: [_make_issue(code="DUPLICATE_ITEM", message="Duplicado")]},
        pdf_path,
        metadata={
            "organization_name": "Empresa Exemplo",
            "file_name": "lote.csv",
            "job_id": "job-123",
            "generated_at": "2026-04-13T12:00:00",
        },
    )
    content = pdf_path.read_bytes()
    assert b"Empresa Exemplo" in content
    assert b"lote.csv" in content
    assert b"job-123" in content


def test_pdf_report_clean_lot_has_clean_copy(tmp_path):
    pdf_path = tmp_path / "clean.pdf"
    generate_pdf_report([{"item": "A001", "descricao": "Mesa"}], {0: []}, pdf_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0


def test_pdf_report_many_issues(tmp_path):
    rows = [{"item": f"I{i}", "descricao": f"Desc{i}"} for i in range(100)]
    results = {i: [_make_issue(code="TEST", message=f"issue {i}")] for i in range(100)}
    pdf_path = tmp_path / "large.pdf"
    generate_pdf_report(rows, results, pdf_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
