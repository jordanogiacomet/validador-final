from app.core.context import ValidationContext
from app.core.issue import ValidationIssue
from app.rules.base import BaseRule


class ZeroItemQualityRule(BaseRule):
    name: str = "zero_item_quality"

    def applies(self, context: ValidationContext) -> bool:
        return context.normalized_row.get("flag_item_cadastrado_do_zero") == 1

    def validate(self, context: ValidationContext) -> list[ValidationIssue]:
        row = context.normalized_row
        issues: list[ValidationIssue] = []

        complemento = row.get("complemento")
        complemento_str = str(complemento).strip() if complemento else ""

        if not complemento_str:
            issues.append(
                ValidationIssue(
                    code="ZERO_ITEM_COMPLEMENTO_EMPTY",
                    severity="warning",
                    message="Item cadastrado do zero sem Complemento",
                    field="complemento",
                )
            )
        else:
            threshold = context.tenant.thresholds.get(
                "short_complement_max_words", 3
            )
            word_count = len(complemento_str.split())
            if word_count <= int(threshold):
                issues.append(
                    ValidationIssue(
                        code="ZERO_ITEM_COMPLEMENTO_SHORT",
                        severity="warning",
                        message=(
                            f"Complemento muito curto ({word_count} palavras,"
                            f" mínimo recomendado: {int(threshold) + 1})"
                        ),
                        field="complemento",
                    )
                )

        marca = row.get("marca")
        if not marca or not str(marca).strip():
            issues.append(
                ValidationIssue(
                    code="ZERO_ITEM_MARCA_MISSING",
                    severity="warning",
                    message="Item cadastrado do zero sem Marca",
                    field="marca",
                )
            )

        modelo = row.get("modelo")
        if not modelo or not str(modelo).strip():
            issues.append(
                ValidationIssue(
                    code="ZERO_ITEM_MODELO_MISSING",
                    severity="warning",
                    message="Item cadastrado do zero sem Modelo",
                    field="modelo",
                )
            )

        self._check_relative_complement_quality(context, issues, complemento_str)

        return issues

    def _check_relative_complement_quality(
        self,
        context: ValidationContext,
        issues: list[ValidationIssue],
        complemento_str: str,
    ) -> None:
        if not complemento_str:
            return

        row = context.normalized_row
        descricao = row.get("descricao")
        if not descricao or not str(descricao).strip():
            return

        tipo_item = str(descricao).strip().lower()

        cache_key = "_zero_item_complement_stats"
        if cache_key not in context.shared_context:
            stats: dict[str, list[int]] = {}
            for r in context.all_rows:
                if r.get("flag_item_cadastrado_do_zero") != 1:
                    continue
                r_desc = r.get("descricao")
                r_comp = r.get("complemento")
                if not r_desc or not str(r_desc).strip():
                    continue
                if not r_comp or not str(r_comp).strip():
                    continue
                r_tipo = str(r_desc).strip().lower()
                word_count = len(str(r_comp).strip().split())
                stats.setdefault(r_tipo, []).append(word_count)
            context.shared_context[cache_key] = stats

        stats = context.shared_context[cache_key]
        peers = stats.get(tipo_item)
        if not peers or len(peers) < 2:
            return

        avg = sum(peers) / len(peers)
        current_words = len(complemento_str.split())
        if avg > 0 and current_words < avg * 0.5:
            issues.append(
                ValidationIssue(
                    code="ZERO_ITEM_COMPLEMENTO_BELOW_PEERS",
                    severity="warning",
                    message=(
                        f"Complemento abaixo da média para '{tipo_item}'"
                        f" ({current_words} palavras vs média {avg:.1f})"
                    ),
                    field="complemento",
                )
            )
