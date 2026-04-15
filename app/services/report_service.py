import csv
from collections import defaultdict
from datetime import datetime
from html import escape
from io import StringIO
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    CondPageBreak,
    KeepTogether,
    LongTable,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from app.core.issue import ValidationIssue

RowType = dict[str, str | int | float | None]
ValidationResults = dict[int, list[ValidationIssue]]
ReportMetadata = dict[str, Any]

INK = colors.HexColor("#18212B")
MUTED = colors.HexColor("#5B6775")
ACCENT = colors.HexColor("#154E4A")
ACCENT_DARK = colors.HexColor("#113A37")
ACCENT_SOFT = colors.HexColor("#E8F1EF")
SURFACE = colors.HexColor("#FFFFFF")
SURFACE_ALT = colors.HexColor("#F5F7F5")
LINE = colors.HexColor("#D7DEDB")
ERROR = colors.HexColor("#B42318")
ERROR_SOFT = colors.HexColor("#FDE9E7")
WARNING = colors.HexColor("#9A5B00")
WARNING_SOFT = colors.HexColor("#FFF1D6")
SUCCESS = colors.HexColor("#1F7A4F")
SUCCESS_SOFT = colors.HexColor("#E6F6EE")
MAX_PROBLEM_ROWS_IN_PDF = 40

FIELD_LABELS: dict[str, str] = {
    "item": "Item",
    "placa_anterior": "Placa Anterior",
    "descricao": "Descrição",
    "marca": "Marca",
    "modelo": "Modelo",
    "ns": "NS",
    "local": "Local",
    "cc": "CC",
    "complemento": "Complemento",
    "observacao": "Observação",
}

CATEGORY_CRITICAL_CHECK_LABELS: dict[str, str] = {
    "btu_pattern": "capacidade em BTU",
    "inches_pattern": "polegadas",
    "ports_pattern": "quantidade de portas",
    "channels_pattern": "quantidade de canais",
    "liters_pattern": "capacidade em litros",
}


def _get_row_metadata(
    normalized_rows: list[RowType],
    row_index: int,
) -> tuple[str | int | float | None, str | int | float | None]:
    if row_index < 0 or row_index >= len(normalized_rows):
        return None, None

    row = normalized_rows[row_index]
    return row.get("item"), row.get("descricao")


def _get_duplicate_descricao(
    normalized_rows: list[RowType],
    row_indices: list[int],
) -> str | None:
    descriptions: list[str] = []
    seen: set[str] = set()

    for row_index in row_indices:
        _, descricao = _get_row_metadata(normalized_rows, row_index)
        if descricao is None:
            continue

        descricao_text = str(descricao).strip()
        if not descricao_text or descricao_text in seen:
            continue

        seen.add(descricao_text)
        descriptions.append(descricao_text)

    if not descriptions:
        return None

    return " / ".join(descriptions)


def _truncate_text(value: object, max_length: int) -> str:
    text = "" if value is None else str(value)
    if len(text) <= max_length:
        return text
    return f"{text[: max_length - 3]}..."


def _human_line_number(row_index: int | None) -> str:
    if row_index is None:
        return "-"
    return str(row_index + 2)


def _field_label(field_name: str | None) -> str:
    if field_name is None:
        return "Revisão geral"
    return FIELD_LABELS.get(field_name, field_name)


def _paragraph(text: object, style: ParagraphStyle) -> Paragraph:
    safe_text = escape("" if text is None else str(text))
    return Paragraph(safe_text.replace("\n", "<br/>"), style)


def _format_timestamp(value: object | None) -> str:
    if value is None:
        return "-"

    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M")

    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)

    return parsed.strftime("%d/%m/%Y %H:%M")


def _normalize_metadata(metadata: ReportMetadata | None) -> ReportMetadata:
    metadata = metadata or {}
    return {
        "organization_name": metadata.get("organization_name") or "Organização não informada",
        "file_name": metadata.get("file_name") or "Arquivo não informado",
        "job_id": metadata.get("job_id") or "-",
        "generated_at": _format_timestamp(metadata.get("generated_at")),
    }


def _build_scope_note(summary: dict[str, int]) -> str:
    source_total_rows = summary.get("source_total_rows", summary["total_rows"])
    if source_total_rows != summary["total_rows"]:
        return (
            "Somente itens cadastrados do zero entraram no resultado operacional. "
            f"Arquivo com {source_total_rows} linhas."
        )

    return "Todas as linhas lidas entraram no escopo validado deste lote."


def _humanize_category_name(category_token: str) -> str:
    return category_token.replace("_", " ").upper()


def _parse_category_required_issue(code: str) -> dict[str, str] | None:
    if not (code.startswith("CATEGORY_") and code.endswith("_REQUIRED")):
        return None

    for field_name, field_label in FIELD_LABELS.items():
        suffix = f"_{field_name.upper()}_REQUIRED"
        if not code.endswith(suffix):
            continue

        category_token = code[len("CATEGORY_") : -len(suffix)]
        if not category_token:
            return None

        return {
            "category_label": _humanize_category_name(category_token),
            "field_name": field_name,
            "field_label": field_label,
        }

    return None


def _parse_category_critical_issue(code: str) -> dict[str, str] | None:
    if not (code.startswith("CATEGORY_") and code.endswith("_MISSING")):
        return None

    for check_name, requirement_label in CATEGORY_CRITICAL_CHECK_LABELS.items():
        suffix = f"_{check_name.upper()}_MISSING"
        if not code.endswith(suffix):
            continue

        category_token = code[len("CATEGORY_") : -len(suffix)]
        if not category_token:
            return None

        return {
            "category_label": _humanize_category_name(category_token),
            "check_name": check_name,
            "requirement_label": requirement_label,
        }

    return None


def _describe_issue(code: str) -> dict[str, str]:
    if code == "DUPLICATE_ITEM":
        return {
            "title": "Identificador patrimonial repetido",
            "context": "Mais de uma linha está usando o mesmo item patrimonial dentro do lote.",
            "impact": (
                "A conciliação patrimonial perde confiabilidade e o mesmo código "
                "pode ser atribuído a bens diferentes."
            ),
            "action": (
                "Defina qual linha deve manter o código atual e ajuste as demais "
                "para que cada bem tenha um item único."
            ),
        }

    if code.startswith("ZERO_ITEM_COMPLEMENTO_"):
        return {
            "title": "Detalhamento insuficiente para item novo",
            "context": (
                "O bem foi cadastrado do zero, mas ainda não traz informação "
                "suficiente para ser identificado sem ambiguidade."
            ),
            "impact": (
                "A equipe passa a depender de memória operacional ou verificação "
                "manual adicional para reconhecer o ativo."
            ),
            "action": (
                "Complete o complemento com características objetivas, como "
                "material, cor, capacidade, localização ou outro traço verificável."
            ),
        }

    if code == "ZERO_ITEM_MARCA_MISSING":
        return {
            "title": "Marca não informada",
            "context": "O item novo foi registrado sem a marca do fabricante.",
            "impact": (
                "O cadastro perde força probatória e fica mais difícil cruzar a "
                "planilha com o bem físico ou com documentos de origem."
            ),
            "action": (
                "Confirme a marca na etiqueta, no equipamento ou na documentação e "
                "preencha a coluna correspondente."
            ),
        }

    if code == "ZERO_ITEM_MODELO_MISSING":
        return {
            "title": "Modelo não informado",
            "context": "O item novo foi registrado sem o modelo do fabricante.",
            "impact": (
                "O registro perde precisão e aumenta o risco de confusão entre "
                "ativos semelhantes."
            ),
            "action": (
                "Informe o modelo exato disponível na etiqueta técnica, caixa ou "
                "nota do equipamento."
            ),
        }

    if code.startswith("FLAG_CONSISTENCY"):
        return {
            "title": "Identificação anterior inconsistente",
            "context": (
                "Os indicadores internos do cadastro não estão coerentes com a "
                "existência ou ausência de placa anterior."
            ),
            "impact": (
                "O histórico do bem fica ambíguo e compromete a leitura de origem, "
                "coleta anterior e tratamento do item."
            ),
            "action": (
                "Revise a identificação de origem do bem e ajuste a informação "
                "anterior antes do próximo envio."
            ),
        }

    category_required = _parse_category_required_issue(code)
    if category_required is not None:
        category_label = category_required["category_label"]
        field_label = category_required["field_label"]
        return {
            "title": f"{category_label}: preencher {field_label}",
            "context": (
                f"Itens classificados como {category_label} precisam preencher "
                f"{field_label} para identificação patrimonial adequada."
            ),
            "impact": (
                f"Sem {field_label}, o registro continua fraco para conferência "
                "operacional e exige interpretação manual adicional."
            ),
            "action": (
                f"Preencha {field_label} seguindo o padrão patrimonial adotado "
                f"para itens da espécie {category_label}."
            ),
        }

    category_critical = _parse_category_critical_issue(code)
    if category_critical is not None:
        category_label = category_critical["category_label"]
        requirement_label = category_critical["requirement_label"]
        return {
            "title": f"{category_label}: informar {requirement_label}",
            "context": (
                f"Itens da espécie {category_label} precisam trazer "
                f"{requirement_label} em Descrição, Complemento ou Modelo."
            ),
            "impact": (
                "Sem esse detalhe técnico, a identificação do bem fica incompleta "
                "e a conciliação patrimonial exige verificação manual adicional."
            ),
            "action": (
                f"Inclua {requirement_label} em Descrição, Complemento ou Modelo, "
                "conforme o padrão de cadastro usado para essa espécie."
            ),
        }

    if code.startswith("LLM_AUDIT_FINDING"):
        return {
            "title": "Revisão textual do cadastro",
            "context": (
                "A auditoria semântica encontrou um ponto de qualidade que pode "
                "enfraquecer a leitura operacional do registro."
            ),
            "impact": (
                "O item permanece compreensível, mas com menor confiança para uso "
                "institucional e rastreio posterior."
            ),
            "action": (
                "Ajuste descrição, marca, modelo, NS, complemento ou observação "
                "para deixar o item mais específico e verificável."
            ),
        }

    if code in {"LLM_AUDIT_FAILURE", "LLM_AUDIT_PROMPT_NOT_FOUND"}:
        return {
            "title": "Falha na auditoria automática",
            "context": "A etapa complementar de auditoria textual não concluiu a execução.",
            "impact": (
                "Não se trata de correção de planilha para a equipe operacional, "
                "mas de uma ocorrência do próprio sistema."
            ),
            "action": (
                "Encaminhe o caso ao suporte técnico. Os demais apontamentos do "
                "lote continuam válidos para tratamento."
            ),
        }

    return {
        "title": code.replace("_", " ").title(),
        "context": (
            "O validador agrupou linhas com o mesmo tipo de apontamento para "
            "facilitar o tratamento operacional."
        ),
        "impact": "Enquanto este grupo permanecer aberto, o lote continua com pendências ativas.",
        "action": (
            "Revise as linhas listadas e ajuste o campo destacado conforme a "
            "orientação do validador."
        ),
    }


def _build_pdf_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "hero_label": ParagraphStyle(
            "HeroLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.HexColor("#CBE2DE"),
            spaceAfter=2,
        ),
        "hero_title": ParagraphStyle(
            "HeroTitle",
            parent=base["Title"],
            fontName="Helvetica-Bold",
            fontSize=22,
            leading=26,
            textColor=colors.white,
            spaceAfter=4,
        ),
        "hero_subtitle": ParagraphStyle(
            "HeroSubtitle",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=10,
            leading=14,
            textColor=colors.HexColor("#E6F1EF"),
            spaceAfter=0,
        ),
        "hero_metric_label": ParagraphStyle(
            "HeroMetricLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=10,
            textColor=ACCENT_DARK,
            spaceAfter=2,
        ),
        "hero_metric_value": ParagraphStyle(
            "HeroMetricValue",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=22,
            textColor=ACCENT_DARK,
            spaceAfter=2,
        ),
        "hero_metric_copy": ParagraphStyle(
            "HeroMetricCopy",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9,
            leading=12,
            textColor=MUTED,
            spaceAfter=0,
        ),
        "section_kicker": ParagraphStyle(
            "SectionKicker",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=ACCENT,
            spaceAfter=3,
        ),
        "section_title": ParagraphStyle(
            "SectionTitle",
            parent=base["Heading2"],
            fontName="Helvetica-Bold",
            fontSize=16,
            leading=19,
            textColor=INK,
            spaceAfter=4,
        ),
        "section_body": ParagraphStyle(
            "SectionBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.5,
            leading=14,
            textColor=MUTED,
            spaceAfter=0,
        ),
        "meta_label": ParagraphStyle(
            "MetaLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.5,
            leading=10,
            textColor=MUTED,
            spaceAfter=2,
        ),
        "meta_value": ParagraphStyle(
            "MetaValue",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=10.5,
            leading=13,
            textColor=INK,
            spaceAfter=0,
        ),
        "metric_label": ParagraphStyle(
            "MetricLabel",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.4,
            leading=9.5,
            textColor=MUTED,
            spaceAfter=2,
        ),
        "metric_value": ParagraphStyle(
            "MetricValue",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=19,
            leading=22,
            textColor=INK,
            spaceAfter=4,
        ),
        "metric_note": ParagraphStyle(
            "MetricNote",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=11.5,
            textColor=MUTED,
            spaceAfter=0,
        ),
        "verdict_title": ParagraphStyle(
            "VerdictTitle",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=12.5,
            leading=15,
            textColor=INK,
            spaceAfter=4,
        ),
        "verdict_body": ParagraphStyle(
            "VerdictBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=9.2,
            leading=13.2,
            textColor=MUTED,
            spaceAfter=0,
        ),
        "table_head": ParagraphStyle(
            "TableHead",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8,
            leading=10,
            textColor=colors.white,
            alignment=TA_CENTER,
        ),
        "table_cell": ParagraphStyle(
            "TableCell",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.8,
            textColor=INK,
        ),
        "table_cell_center": ParagraphStyle(
            "TableCellCenter",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.5,
            leading=10.8,
            textColor=INK,
            alignment=TA_CENTER,
        ),
        "problem_title": ParagraphStyle(
            "ProblemTitle",
            parent=base["Heading3"],
            fontName="Helvetica-Bold",
            fontSize=13,
            leading=16,
            textColor=INK,
            spaceAfter=2,
        ),
        "problem_meta": ParagraphStyle(
            "ProblemMeta",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.6,
            leading=11.2,
            textColor=MUTED,
            spaceAfter=0,
        ),
        "badge": ParagraphStyle(
            "Badge",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=8.5,
            leading=10,
            alignment=TA_CENTER,
        ),
        "detail_title": ParagraphStyle(
            "DetailTitle",
            parent=base["BodyText"],
            fontName="Helvetica-Bold",
            fontSize=7.8,
            leading=10,
            textColor=ACCENT,
            spaceAfter=4,
        ),
        "detail_body": ParagraphStyle(
            "DetailBody",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8.8,
            leading=12.4,
            textColor=INK,
            spaceAfter=0,
        ),
        "footnote": ParagraphStyle(
            "Footnote",
            parent=base["BodyText"],
            fontName="Helvetica",
            fontSize=8,
            leading=10,
            textColor=MUTED,
            alignment=TA_RIGHT,
        ),
    }


def _metric_card(
    label: str,
    value: int,
    note: str,
    styles: dict[str, ParagraphStyle],
    accent_color: colors.Color,
) -> Table:
    value_style = ParagraphStyle(
        f"MetricValue{label}",
        parent=styles["metric_value"],
        textColor=accent_color,
    )
    card = Table(
        [[[
            _paragraph(label.upper(), styles["metric_label"]),
            Spacer(1, 2),
            _paragraph(value, value_style),
            _paragraph(note, styles["metric_note"]),
        ]]],
        colWidths=[160],
    )
    card.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 10),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return card


def _build_report_banner(
    summary: dict[str, int],
    metadata: ReportMetadata,
    styles: dict[str, ParagraphStyle],
) -> Table:
    clean_rows = max(summary["total_rows"] - summary["rows_with_issues"], 0)
    banner_copy = (
        f"{summary['error_count']} erros  •  {summary['warning_count']} avisos"
        f"  •  {clean_rows} linhas em escopo sem ação"
    )
    source_total_rows = summary.get("source_total_rows", summary["total_rows"])
    if source_total_rows != summary["total_rows"]:
        banner_copy = (
            f"{banner_copy}  •  escopo operacional: {summary['total_rows']} de "
            f"{source_total_rows} linhas do arquivo"
        )

    left_content = [
        _paragraph("RELATÓRIO OPERACIONAL", styles["hero_label"]),
        _paragraph("Validação patrimonial do lote", styles["hero_title"]),
        Spacer(1, 4),
        _paragraph(
            (
                f"Organização: {metadata['organization_name']}\n"
                f"Arquivo: {metadata['file_name']}"
            ),
            styles["hero_subtitle"],
        ),
    ]
    right_content = [
        _paragraph("VEREDITO DO LOTE", styles["hero_metric_label"]),
        _paragraph(
            f"{summary['rows_with_issues']} linhas em escopo com revisão",
            styles["hero_metric_value"],
        ),
        _paragraph(banner_copy, styles["hero_metric_copy"]),
    ]

    banner = Table([[left_content, right_content]], colWidths=[334, 164])
    banner.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), ACCENT_DARK),
        ("BACKGROUND", (1, 0), (1, 0), ACCENT_SOFT),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 18),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 18),
        ("LEFTPADDING", (0, 0), (-1, -1), 18),
        ("RIGHTPADDING", (0, 0), (-1, -1), 18),
    ]))
    return banner


def _build_identity_panel(
    metadata: ReportMetadata,
    styles: dict[str, ParagraphStyle],
) -> Table:
    cells = []
    for label, value in (
        ("Organização", metadata["organization_name"]),
        ("Arquivo de origem", metadata["file_name"]),
        ("Job", metadata["job_id"]),
        ("Gerado em", metadata["generated_at"]),
    ):
        card = Table(
            [[[
                _paragraph(label.upper(), styles["meta_label"]),
                _paragraph(value, styles["meta_value"]),
            ]]],
            colWidths=[246],
        )
        card.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ("BOX", (0, 0), (-1, -1), 0.7, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        cells.append(card)

    panel = Table([cells[:2], cells[2:]], colWidths=[249, 249], hAlign="LEFT")
    panel.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return panel


def _build_summary_grid(
    summary: dict[str, int],
    styles: dict[str, ParagraphStyle],
) -> Table:
    clean_rows = max(summary["total_rows"] - summary["rows_with_issues"], 0)
    cards = [
        _metric_card(
            "Linhas validadas",
            summary["total_rows"],
            _build_scope_note(summary),
            styles,
            ACCENT,
        ),
        _metric_card(
            "Linhas com revisão",
            summary["rows_with_issues"],
            "Registros que exigem ajuste antes do próximo envio.",
            styles,
            ACCENT_DARK,
        ),
        _metric_card(
            "Total de problemas",
            summary["total_issues"],
            "Soma dos apontamentos consolidados neste processamento.",
            styles,
            ACCENT,
        ),
        _metric_card(
            "Erros",
            summary["error_count"],
            "Pendências críticas. Devem liderar a ordem de tratamento.",
            styles,
            ERROR,
        ),
        _metric_card(
            "Avisos",
            summary["warning_count"],
            "Pontos de qualidade e detalhamento ainda abertos.",
            styles,
            WARNING,
        ),
        _metric_card(
            "Linhas sem ação",
            clean_rows,
            "Registros que passaram sem apontamentos ativos.",
            styles,
            SUCCESS,
        ),
    ]
    summary_table = Table(
        [cards[:3], cards[3:]],
        colWidths=[166, 166, 166],
        hAlign="LEFT",
    )
    summary_table.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return summary_table


def _build_verdict_panel(
    summary: dict[str, int],
    duplicates: list[dict],
    styles: dict[str, ParagraphStyle],
) -> Table:
    duplicate_count = len(duplicates)
    source_total_rows = summary.get("source_total_rows", summary["total_rows"])

    if summary["total_rows"] == 0:
        title = "Nenhum item cadastrado do zero entrou no escopo operacional."
        body = (
            "O arquivo foi lido normalmente, mas nenhuma linha tinha "
            "flag_item_cadastrado_do_zero = 1. Por isso, o resultado validado "
            "não traz pendências operacionais."
        )
        highlight_label = "Itens em escopo"
        highlight_value = 0
        highlight_copy = f"Arquivo com {source_total_rows} linhas."
        highlight_color = SUCCESS
        highlight_bg = SUCCESS_SOFT
    elif summary["error_count"] > 0:
        title = "Prioridade imediata: tratar erros antes do próximo reenvio."
        body = (
            "Os erros afetam consistência, identificação ou regras críticas do lote. "
            "Resolva esse grupo antes de revisar avisos de qualidade."
        )
        highlight_label = "Risco crítico"
        highlight_value = summary["error_count"]
        highlight_copy = "Erros ativos no lote."
        highlight_color = ERROR
        highlight_bg = ERROR_SOFT
    elif summary["warning_count"] > 0:
        title = "Lote sem erros críticos, com pontos de qualidade ainda abertos."
        body = (
            "Os avisos não bloqueiam a leitura estrutural, mas indicam cadastros "
            "incompletos ou abaixo do padrão de detalhamento esperado."
        )
        highlight_label = "Pontos de qualidade"
        highlight_value = summary["warning_count"]
        highlight_copy = "Avisos ativos no lote."
        highlight_color = WARNING
        highlight_bg = WARNING_SOFT
    else:
        title = "Nenhuma correção foi exigida neste processamento."
        body = (
            "O lote passou pela validação sem pendências abertas. Use este relatório "
            "como artefato institucional de conferências e registro."
        )
        highlight_label = "Lote liberado"
        highlight_value = summary["total_rows"]
        highlight_copy = "Registros em escopo processados sem pendências."
        highlight_color = SUCCESS
        highlight_bg = SUCCESS_SOFT

    checklist = Table(
        [[[
            _paragraph("DIREÇÃO DE TRATAMENTO", styles["detail_title"]),
            _paragraph(title, styles["verdict_title"]),
            _paragraph(body, styles["verdict_body"]),
            Spacer(1, 5),
            _paragraph(
                (
                    f"Duplicidades no lote: {duplicate_count}. "
                    "Use a ordem erro -> aviso -> conferência final para reduzir retrabalho."
                ),
                styles["verdict_body"],
            ),
        ]]],
        colWidths=[344],
    )
    checklist.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))

    highlight_style = ParagraphStyle(
        "VerdictHighlight",
        parent=styles["metric_value"],
        textColor=highlight_color,
        alignment=TA_CENTER,
    )
    highlight = Table(
        [[[
            _paragraph(highlight_label.upper(), styles["metric_label"]),
            Spacer(1, 4),
            _paragraph(highlight_value, highlight_style),
            _paragraph(highlight_copy, styles["metric_note"]),
        ]]],
        colWidths=[154],
    )
    highlight.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), highlight_bg),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 16),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 16),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    verdict = Table([[checklist, highlight]], colWidths=[348, 150], hAlign="LEFT")
    verdict.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "STRETCH"),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
    ]))
    return verdict


def _build_table_header(labels: list[str], style: ParagraphStyle) -> list[Paragraph]:
    return [_paragraph(label, style) for label in labels]


def _build_duplicates_table(
    duplicates: list[dict],
    styles: dict[str, ParagraphStyle],
) -> LongTable:
    data: list[list[Paragraph]] = [
        _build_table_header(
            ["Item", "Nome do bem", "Ocorrências", "Linhas envolvidas"],
            styles["table_head"],
        )
    ]
    for duplicate in duplicates:
        human_lines = ", ".join(_human_line_number(idx) for idx in duplicate["row_indices"])
        data.append([
            _paragraph(duplicate["item"], styles["table_cell_center"]),
            _paragraph(duplicate.get("descricao") or "Não informado", styles["table_cell"]),
            _paragraph(duplicate["count"], styles["table_cell_center"]),
            _paragraph(human_lines, styles["table_cell"]),
        ])

    table = LongTable(data, colWidths=[72, 180, 78, 168], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [SURFACE, SURFACE_ALT]),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
    ]))
    return table


def _sorted_problem_groups(grouped_problems: dict[str, list[dict]]) -> list[tuple[str, list[dict]]]:
    return sorted(
        grouped_problems.items(),
        key=lambda item: (
            0 if any(occ["severity"] == "error" for occ in item[1]) else 1,
            -len(item[1]),
            item[0],
        ),
    )


def _build_problem_header(
    code: str,
    occurrences: list[dict],
    styles: dict[str, ParagraphStyle],
) -> Table:
    guide = _describe_issue(code)
    severity = "error" if any(occ["severity"] == "error" for occ in occurrences) else "warning"
    badge_color = ERROR if severity == "error" else WARNING
    badge_bg = ERROR_SOFT if severity == "error" else WARNING_SOFT
    badge_text = "ERRO" if severity == "error" else "AVISO"

    badge_style = ParagraphStyle(
        f"Badge{code}",
        parent=styles["badge"],
        textColor=badge_color,
    )

    header = Table(
        [[
            [
                _paragraph(guide["title"], styles["problem_title"]),
                _paragraph(
                    f"{len(occurrences)} ocorrência(s) no escopo validado",
                    styles["problem_meta"],
                ),
            ],
            _paragraph(badge_text, badge_style),
        ]],
        colWidths=[408, 90],
    )
    header.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, 0), SURFACE_ALT),
        ("BACKGROUND", (1, 0), (1, 0), badge_bg),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 12),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 12),
        ("LEFTPADDING", (0, 0), (-1, -1), 12),
        ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ]))
    return header


def _build_problem_guidance(
    code: str,
    occurrences: list[dict],
    styles: dict[str, ParagraphStyle],
) -> Table:
    guide = _describe_issue(code)
    unique_fields = []
    for field in (_field_label(occ.get("field")) for occ in occurrences):
        if field not in unique_fields:
            unique_fields.append(field)
    scope = (
        f"Atinge {len(occurrences)} linha(s). Campos mais envolvidos: "
        f"{', '.join(unique_fields[:4]) or 'Revisão geral'}."
    )

    boxes = []
    for title, body in (
        ("Contexto operacional", guide["context"]),
        ("Impacto na correção", guide["impact"]),
        ("Ação exigida", guide["action"]),
        ("Escopo deste grupo", scope),
    ):
        box = Table(
            [[[
                _paragraph(title.upper(), styles["detail_title"]),
                _paragraph(body, styles["detail_body"]),
            ]]],
            colWidths=[244],
        )
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), SURFACE),
            ("BOX", (0, 0), (-1, -1), 0.7, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 10),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
            ("LEFTPADDING", (0, 0), (-1, -1), 12),
            ("RIGHTPADDING", (0, 0), (-1, -1), 12),
        ]))
        boxes.append(box)

    guidance = Table([boxes[:2], boxes[2:]], colWidths=[249, 249], hAlign="LEFT")
    guidance.setStyle(TableStyle([
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 0),
        ("TOPPADDING", (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 0),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return guidance


def _build_occurrences_table(
    occurrences: list[dict],
    styles: dict[str, ParagraphStyle],
) -> LongTable:
    data: list[list[Paragraph]] = [
        _build_table_header(
            ["Linha", "Item", "Nome do bem", "Campo a revisar", "Orientação do validador"],
            styles["table_head"],
        )
    ]
    for occurrence in occurrences[:MAX_PROBLEM_ROWS_IN_PDF]:
        data.append([
            _paragraph(_human_line_number(occurrence["row_index"]), styles["table_cell_center"]),
            _paragraph(occurrence.get("item") or "Não informado", styles["table_cell_center"]),
            _paragraph(
                _truncate_text(occurrence.get("descricao") or "Não informado", 70),
                styles["table_cell"],
            ),
            _paragraph(_field_label(occurrence.get("field")), styles["table_cell"]),
            _paragraph(occurrence["message"], styles["table_cell"]),
        ])

    table = LongTable(data, colWidths=[44, 56, 122, 92, 184], repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), ACCENT),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [SURFACE, SURFACE_ALT]),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 7),
        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
    ]))
    return table


def _build_clean_panel(summary: dict[str, int], styles: dict[str, ParagraphStyle]) -> Table:
    source_total_rows = summary.get("source_total_rows", summary["total_rows"])
    title = "Nenhuma correção foi exigida neste processamento."
    body = (
        "O arquivo passou pela validação sem apontamentos abertos. "
        "Use este PDF como artefato institucional de conferência e registro."
    )

    if summary["total_rows"] == 0 and source_total_rows > 0:
        title = "Nenhum item cadastrado do zero entrou no escopo operacional."
        body = (
            "O arquivo foi lido normalmente, mas nenhuma linha tinha "
            "flag_item_cadastrado_do_zero = 1. Este PDF registra que não houve "
            "itens em escopo para consolidar no resultado operacional."
        )

    panel = Table(
        [[[
            _paragraph("LOTE SEM PENDÊNCIAS", styles["detail_title"]),
            _paragraph(title, styles["verdict_title"]),
            _paragraph(body, styles["verdict_body"]),
        ]]],
        colWidths=[498],
    )
    panel.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), SUCCESS_SOFT),
        ("BOX", (0, 0), (-1, -1), 0.8, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
    ]))
    return panel


def build_row_results(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
    row_indices: list[int] | None = None,
) -> list[dict]:
    indices = row_indices if row_indices is not None else list(range(len(normalized_rows)))
    output = []
    for idx in indices:
        row = normalized_rows[idx]
        issues = validation_results.get(idx, [])
        output.append({
            "row_index": idx,
            "item": row.get("item"),
            "descricao": row.get("descricao"),
            "issues": [issue.model_dump() for issue in issues],
            "has_errors": any(issue.severity == "error" for issue in issues),
            "has_warnings": any(issue.severity == "warning" for issue in issues),
        })
    return output


def build_duplicate_section(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
    row_indices: list[int] | None = None,
) -> list[dict]:
    _ = validation_results
    item_rows: dict[object, list[int]] = defaultdict(list)
    indices = row_indices if row_indices is not None else list(range(len(normalized_rows)))
    for idx in indices:
        row = normalized_rows[idx]
        item_value = row.get("item")
        if item_value is not None:
            item_rows[item_value].append(idx)

    duplicates = []
    for item_value, indices in item_rows.items():
        if len(indices) > 1:
            duplicates.append({
                "item": item_value,
                "descricao": _get_duplicate_descricao(normalized_rows, indices),
                "row_indices": indices,
                "count": len(indices),
            })
    return duplicates


def build_grouped_problems(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
    row_indices: list[int] | None = None,
) -> dict[str, list[dict]]:
    allowed_indices = set(row_indices) if row_indices is not None else None
    grouped: dict[str, list[dict]] = defaultdict(list)
    for row_index, issues in validation_results.items():
        if allowed_indices is not None and row_index not in allowed_indices:
            continue
        item, descricao = _get_row_metadata(normalized_rows, row_index)
        for issue in issues:
            grouped[issue.code].append({
                "row_index": row_index,
                "item": item,
                "descricao": descricao,
                "severity": issue.severity,
                "message": issue.message,
                "field": issue.field,
            })
    return dict(grouped)


def _resolve_validated_row_indices(
    normalized_rows: list[RowType],
    validated_row_indices: list[int] | None,
) -> list[int]:
    if validated_row_indices is not None:
        return list(validated_row_indices)
    return list(range(len(normalized_rows)))


def _build_summary_payload(
    validation_results: ValidationResults,
    row_indices: list[int],
    *,
    total_validated_rows: int,
    source_total_rows: int,
    processed_rows: int | None = None,
) -> dict[str, int]:
    rows_with_issues = sum(1 for idx in row_indices if validation_results.get(idx))
    total_issues = sum(len(validation_results.get(idx, [])) for idx in row_indices)
    error_count = sum(
        1
        for idx in row_indices
        for issue in validation_results.get(idx, [])
        if issue.severity == "error"
    )
    warning_count = total_issues - error_count

    summary = {
        "total_rows": total_validated_rows,
        "validated_rows": total_validated_rows,
        "source_total_rows": source_total_rows,
        "rows_with_issues": rows_with_issues,
        "total_issues": total_issues,
        "error_count": error_count,
        "warning_count": warning_count,
    }
    if processed_rows is not None:
        summary["processed_rows"] = processed_rows

    return summary


def build_partial_report(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
    processed_row_indices: list[int],
    partial_duplicates: list[dict] | None = None,
    validated_row_indices: list[int] | None = None,
    source_total_rows: int | None = None,
    include_row_results_preview: bool = True,
) -> dict:
    validated_indices = _resolve_validated_row_indices(
        normalized_rows, validated_row_indices
    )
    source_total_rows = (
        len(normalized_rows) if source_total_rows is None else source_total_rows
    )
    ordered_indices = sorted(processed_row_indices)
    return {
        "partial_summary": _build_summary_payload(
            validation_results,
            ordered_indices,
            total_validated_rows=len(validated_indices),
            source_total_rows=source_total_rows,
            processed_rows=len(ordered_indices),
        ),
        "row_results_preview": (
            build_row_results(
                normalized_rows,
                validation_results,
                row_indices=ordered_indices,
            )
            if include_row_results_preview
            else []
        ),
        "partial_grouped_problems": build_grouped_problems(
            normalized_rows,
            validation_results,
            row_indices=ordered_indices,
        ),
        "partial_duplicates": partial_duplicates
        or build_duplicate_section(
            normalized_rows,
            validation_results,
            row_indices=validated_indices,
        ),
    }


def build_full_report(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
    validated_row_indices: list[int] | None = None,
    source_total_rows: int | None = None,
) -> dict:
    validated_indices = _resolve_validated_row_indices(
        normalized_rows, validated_row_indices
    )
    source_total_rows = (
        len(normalized_rows) if source_total_rows is None else source_total_rows
    )

    return {
        "summary": _build_summary_payload(
            validation_results,
            validated_indices,
            total_validated_rows=len(validated_indices),
            source_total_rows=source_total_rows,
        ),
        "row_results": build_row_results(
            normalized_rows,
            validation_results,
            row_indices=validated_indices,
        ),
        "duplicates": build_duplicate_section(
            normalized_rows,
            validation_results,
            row_indices=validated_indices,
        ),
        "grouped_problems": build_grouped_problems(
            normalized_rows,
            validation_results,
            row_indices=validated_indices,
        ),
    }


def build_duplicates_export_csv(duplicates: list[dict]) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "Item",
            "Descrição",
            "Quantidade de Ocorrências",
            "Linhas Envolvidas",
        ],
    )
    writer.writeheader()
    for duplicate in duplicates:
        row_indices = duplicate.get("row_indices") or []
        writer.writerow(
            {
                "Item": "" if duplicate.get("item") is None else str(duplicate["item"]),
                "Descrição": ""
                if duplicate.get("descricao") is None
                else str(duplicate["descricao"]),
                "Quantidade de Ocorrências": duplicate.get("count", 0),
                "Linhas Envolvidas": ", ".join(
                    _human_line_number(
                        row_index if isinstance(row_index, int) else None
                    )
                    for row_index in row_indices
                ),
            }
        )

    return buffer.getvalue()


def build_problem_group_export_csv(
    code: str,
    occurrences: list[dict],
) -> str:
    buffer = StringIO()
    writer = csv.DictWriter(
        buffer,
        fieldnames=[
            "Código",
            "Linha",
            "Item",
            "Descrição",
            "Severidade",
            "Campo",
            "Mensagem",
        ],
    )
    writer.writeheader()
    for occurrence in sorted(
        occurrences,
        key=lambda item: (
            item.get("row_index")
            if isinstance(item.get("row_index"), int)
            else float("inf")
        ),
    ):
        row_index = occurrence.get("row_index")
        writer.writerow(
            {
                "Código": code,
                "Linha": _human_line_number(row_index if isinstance(row_index, int) else None),
                "Item": "" if occurrence.get("item") is None else str(occurrence["item"]),
                "Descrição": ""
                if occurrence.get("descricao") is None
                else str(occurrence["descricao"]),
                "Severidade": ""
                if occurrence.get("severity") is None
                else str(occurrence["severity"]),
                "Campo": _field_label(
                    occurrence.get("field")
                    if isinstance(occurrence.get("field"), str)
                    else None
                ),
                "Mensagem": ""
                if occurrence.get("message") is None
                else str(occurrence["message"]),
            }
        )

    return buffer.getvalue()


def generate_pdf_report(
    normalized_rows: list[RowType],
    validation_results: ValidationResults,
    output_path: str | Path,
    metadata: ReportMetadata | None = None,
    validated_row_indices: list[int] | None = None,
    source_total_rows: int | None = None,
) -> Path:
    output_path = Path(output_path)
    report_data = build_full_report(
        normalized_rows,
        validation_results,
        validated_row_indices=validated_row_indices,
        source_total_rows=source_total_rows,
    )
    summary = report_data["summary"]
    duplicates = report_data["duplicates"]
    grouped_problems = report_data["grouped_problems"]
    metadata = _normalize_metadata(metadata)

    doc = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        leftMargin=14 * mm,
        rightMargin=14 * mm,
        topMargin=16 * mm,
        bottomMargin=18 * mm,
        pageCompression=0,
    )
    styles = _build_pdf_styles()
    elements: list[object] = []

    elements.append(_build_report_banner(summary, metadata, styles))
    elements.append(Spacer(1, 6 * mm))

    elements.append(_paragraph("IDENTIFICAÇÃO DO LOTE", styles["section_kicker"]))
    elements.append(_paragraph("Dados de controle e rastreio", styles["section_title"]))
    elements.append(_paragraph(
        (
            "Este documento consolida o resultado operacional do lote processado, "
            "com identificação do arquivo, resumo executivo e orientação de correção."
        ),
        styles["section_body"],
    ))
    elements.append(Spacer(1, 4 * mm))
    elements.append(_build_identity_panel(metadata, styles))
    elements.append(Spacer(1, 7 * mm))

    elements.append(_paragraph("RESUMO EXECUTIVO", styles["section_kicker"]))
    elements.append(_paragraph("Panorama do processamento", styles["section_title"]))
    elements.append(_paragraph(
        (
            "Use este quadro para definir a ordem de tratamento do lote e avaliar "
            "o volume de correções abertas antes do próximo envio."
        ),
        styles["section_body"],
    ))
    elements.append(Spacer(1, 4 * mm))
    elements.append(_build_summary_grid(summary, styles))
    elements.append(Spacer(1, 7 * mm))

    elements.append(_paragraph("DIREÇÃO DE TRATAMENTO", styles["section_kicker"]))
    elements.append(_paragraph("Leitura operacional do lote", styles["section_title"]))
    elements.append(_paragraph(
        (
            "Abaixo está o veredito consolidado do lote, com foco no que a equipe "
            "deve tratar primeiro e no risco atual de consistência."
        ),
        styles["section_body"],
    ))
    elements.append(Spacer(1, 4 * mm))
    elements.append(_build_verdict_panel(summary, duplicates, styles))

    if duplicates:
        elements.append(Spacer(1, 7 * mm))
        elements.append(_paragraph("CONSISTÊNCIA CADASTRAL", styles["section_kicker"]))
        elements.append(_paragraph("Itens com identificador repetido", styles["section_title"]))
        elements.append(_paragraph(
            (
                "Cada item patrimonial deve aparecer uma única vez. Resolva "
                "duplicidades antes de aprofundar ajustes de qualidade textual."
            ),
            styles["section_body"],
        ))
        elements.append(Spacer(1, 4 * mm))
        elements.append(_build_duplicates_table(duplicates, styles))

    sorted_groups = _sorted_problem_groups(grouped_problems)
    if not sorted_groups:
        elements.append(Spacer(1, 7 * mm))
        elements.append(_build_clean_panel(summary, styles))
    else:
        elements.append(PageBreak())
        elements.append(_paragraph("MAPA DE CORREÇÕES", styles["section_kicker"]))
        elements.append(_paragraph("Problemas agrupados por tipo", styles["section_title"]))
        elements.append(_paragraph(
            (
                "Cada bloco abaixo descreve o contexto do problema, o impacto para "
                "a operação patrimonial, a ação esperada e as linhas envolvidas no "
                "escopo validado."
            ),
            styles["section_body"],
        ))
        elements.append(Spacer(1, 5 * mm))

        for code, occurrences in sorted_groups:
            elements.append(CondPageBreak(70 * mm))
            elements.append(KeepTogether([
                _build_problem_header(code, occurrences, styles),
                Spacer(1, 2.5 * mm),
                _build_problem_guidance(code, occurrences, styles),
                Spacer(1, 3 * mm),
            ]))
            elements.append(_build_occurrences_table(occurrences, styles))
            if len(occurrences) > MAX_PROBLEM_ROWS_IN_PDF:
                elements.append(Spacer(1, 1.5 * mm))
                elements.append(_paragraph(
                    (
                        f"Observação: este PDF mostra as primeiras "
                        f"{MAX_PROBLEM_ROWS_IN_PDF} ocorrências deste grupo. "
                        "Consulte os dados estruturados para a listagem completa."
                    ),
                    styles["footnote"],
                ))
            elements.append(Spacer(1, 6 * mm))

    footer_left = f"{metadata['organization_name']} • relatório operacional"

    def draw_page_chrome(canvas, doc) -> None:
        canvas.saveState()
        page_width, _ = A4
        canvas.setStrokeColor(LINE)
        canvas.setLineWidth(0.6)
        canvas.line(doc.leftMargin, 14 * mm, page_width - doc.rightMargin, 14 * mm)
        canvas.setFillColor(MUTED)
        canvas.setFont("Helvetica", 8)
        canvas.drawString(doc.leftMargin, 9.5 * mm, _truncate_text(footer_left, 68))
        canvas.drawRightString(
            page_width - doc.rightMargin,
            9.5 * mm,
            f"Página {canvas.getPageNumber()}",
        )
        canvas.restoreState()

    doc.build(elements, onFirstPage=draw_page_chrome, onLaterPages=draw_page_chrome)
    return output_path
