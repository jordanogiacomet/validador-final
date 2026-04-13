from collections import defaultdict
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.core.issue import ValidationIssue

RowType = dict[str, str | int | float | None]
ValidationResults = dict[int, list[ValidationIssue]]


def build_row_results(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
) -> list[dict]:
    """Build structured validation result per row."""
    output = []
    for idx, row in enumerate(normalized_rows):
        issues = validation_results.get(idx, [])
        output.append({
            "row_index": idx,
            "item": row.get("item"),
            "descricao": row.get("descricao"),
            "issues": [issue.model_dump() for issue in issues],
            "has_errors": any(i.severity == "error" for i in issues),
            "has_warnings": any(i.severity == "warning" for i in issues),
        })
    return output


def build_duplicate_section(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
) -> list[dict]:
    """Build section listing duplicate items and their row indices."""
    item_rows: dict[object, list[int]] = defaultdict(list)
    for idx, row in enumerate(normalized_rows):
        item_val = row.get("item")
        if item_val is not None:
            item_rows[item_val].append(idx)

    duplicates = []
    for item_val, indices in item_rows.items():
        if len(indices) > 1:
            duplicates.append({
                "item": item_val,
                "row_indices": indices,
                "count": len(indices),
            })
    return duplicates


def build_grouped_problems(
    validation_results: ValidationResults,
) -> dict[str, list[dict]]:
    """Group issues by issue code for operational review."""
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row_idx, issues in validation_results.items():
        for issue in issues:
            grouped[issue.code].append({
                "row_index": row_idx,
                "severity": issue.severity,
                "message": issue.message,
                "field": issue.field,
            })
    return dict(grouped)


def build_full_report(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
) -> dict:
    """Build the complete structured report."""
    total_rows = len(normalized_rows)
    rows_with_issues = sum(1 for idx in range(total_rows) if validation_results.get(idx))
    total_issues = sum(len(issues) for issues in validation_results.values())
    error_count = sum(
        1 for issues in validation_results.values()
        for i in issues if i.severity == "error"
    )
    warning_count = total_issues - error_count

    return {
        "summary": {
            "total_rows": total_rows,
            "rows_with_issues": rows_with_issues,
            "total_issues": total_issues,
            "error_count": error_count,
            "warning_count": warning_count,
        },
        "row_results": build_row_results(normalized_rows, validation_results),
        "duplicates": build_duplicate_section(normalized_rows, validation_results),
        "grouped_problems": build_grouped_problems(validation_results),
    }


def generate_pdf_report(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
    output_path: str | Path,
) -> Path:
    """Generate a PDF report for operational review."""
    output_path = Path(output_path)
    report_data = build_full_report(normalized_rows, validation_results)
    summary = report_data["summary"]

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=15 * mm,
        rightMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "ReportTitle", parent=styles["Title"], fontSize=16, spaceAfter=12
    )
    heading_style = ParagraphStyle(
        "SectionHeading", parent=styles["Heading2"], fontSize=13, spaceAfter=8
    )
    body_style = styles["BodyText"]

    elements: list = []

    elements.append(Paragraph("Relatório de Validação de Inventário", title_style))
    elements.append(Spacer(1, 6 * mm))

    summary_data = [
        ["Total de linhas", str(summary["total_rows"])],
        ["Linhas com problemas", str(summary["rows_with_issues"])],
        ["Total de problemas", str(summary["total_issues"])],
        ["Erros", str(summary["error_count"])],
        ["Avisos", str(summary["warning_count"])],
    ]
    summary_table = Table(summary_data, colWidths=[140, 80])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("FONTSIZE", (0, 0), (-1, -1), 10),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    elements.append(Paragraph("Resumo", heading_style))
    elements.append(summary_table)
    elements.append(Spacer(1, 8 * mm))

    duplicates = report_data["duplicates"]
    if duplicates:
        elements.append(Paragraph("Itens Duplicados", heading_style))
        dup_data = [["Item", "Ocorrências", "Linhas"]]
        for dup in duplicates:
            row_indices_str = ", ".join(str(r) for r in dup["row_indices"])
            dup_data.append([str(dup["item"]), str(dup["count"]), row_indices_str])
        dup_table = Table(dup_data, colWidths=[120, 80, 200])
        dup_table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("PADDING", (0, 0), (-1, -1), 5),
        ]))
        elements.append(dup_table)
        elements.append(Spacer(1, 8 * mm))

    grouped = report_data["grouped_problems"]
    if grouped:
        elements.append(Paragraph("Problemas Agrupados por Tipo", heading_style))
        for code, occurrences in grouped.items():
            elements.append(Paragraph(
                f"<b>{code}</b> ({len(occurrences)} ocorrências)", body_style
            ))
            prob_data = [["Linha", "Severidade", "Mensagem"]]
            for occ in occurrences[:50]:
                prob_data.append([
                    str(occ["row_index"]),
                    occ["severity"],
                    occ["message"][:80],
                ])
            prob_table = Table(prob_data, colWidths=[50, 70, 300])
            prob_table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("PADDING", (0, 0), (-1, -1), 4),
            ]))
            elements.append(prob_table)
            elements.append(Spacer(1, 4 * mm))

    doc.build(elements)
    return output_path
