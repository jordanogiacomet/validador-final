from pathlib import Path

from app.core.issue import ValidationIssue
from app.services.report_service import (
    build_duplicate_section,
    build_full_report,
    build_grouped_problems,
    build_row_results,
    generate_pdf_report,
)


def _make_issue(code="TEST", severity="error", message="test msg", field="item"):
    return ValidationIssue(code=code, severity=severity, message=message, field=field)


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


# --- build_duplicate_section ---

def test_duplicate_section_finds_duplicates():
    rows = _sample_rows()
    dups = build_duplicate_section(rows, {})
    assert len(dups) == 1
    assert dups[0]["item"] == "A001"
    assert dups[0]["descricao"] == "Mesa"
    assert dups[0]["count"] == 2
    assert set(dups[0]["row_indices"]) == {0, 2}


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


def test_pdf_report_many_issues(tmp_path):
    rows = [{"item": f"I{i}", "descricao": f"Desc{i}"} for i in range(100)]
    results = {i: [_make_issue(code="TEST", message=f"issue {i}")] for i in range(100)}
    pdf_path = tmp_path / "large.pdf"
    generate_pdf_report(rows, results, pdf_path)
    assert pdf_path.exists()
    assert pdf_path.stat().st_size > 0
