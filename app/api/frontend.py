# ruff: noqa: E501

from html import escape

from app.core.tenant_loader import list_tenants, load_tenant_config


def _build_tenant_options() -> str:
    options: list[str] = []
    for tenant_id in list_tenants():
        try:
            tenant = load_tenant_config(tenant_id)
            label = f"{tenant.display_name} ({tenant.tenant_id})"
        except FileNotFoundError:
            label = tenant_id

        selected = " selected" if tenant_id == "default" else ""
        options.append(
            f'<option value="{escape(tenant_id)}"{selected}>{escape(label)}</option>'
        )

    if not options:
        options.append('<option value="default" selected>Default Tenant (default)</option>')

    return "\n".join(options)


def build_frontend_html() -> str:
    tenant_options = _build_tenant_options()

    html = """<!DOCTYPE html>
<html lang="pt-BR">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <title>Central de Correção Patrimonial</title>
  <style>
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');

    :root {
      --bg: #f6efe4;
      --panel: rgba(255, 251, 245, 0.88);
      --panel-strong: #fffdf8;
      --ink: #1d2430;
      --muted: #5f6b78;
      --line: rgba(42, 57, 82, 0.16);
      --accent: #0f766e;
      --accent-soft: rgba(15, 118, 110, 0.14);
      --warning: #b45309;
      --warning-soft: rgba(245, 158, 11, 0.16);
      --error: #b42318;
      --error-soft: rgba(228, 77, 77, 0.12);
      --shadow: 0 18px 48px rgba(46, 52, 66, 0.12);
      --radius: 22px;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(15, 118, 110, 0.22), transparent 28%),
        radial-gradient(circle at 85% 15%, rgba(180, 83, 9, 0.18), transparent 24%),
        linear-gradient(180deg, #f7f0e5 0%, #efe7da 100%);
      min-height: 100vh;
    }

    .shell {
      width: min(1180px, calc(100% - 32px));
      margin: 0 auto;
      padding: 32px 0 48px;
    }

    .hero {
      position: relative;
      overflow: hidden;
      padding: 32px;
      border-radius: 32px;
      background:
        linear-gradient(135deg, rgba(255,255,255,0.76), rgba(255,255,255,0.52)),
        linear-gradient(120deg, #f4ede1 0%, #fdf8f0 55%, #e9f7f3 100%);
      border: 1px solid rgba(255,255,255,0.5);
      box-shadow: var(--shadow);
    }

    .hero::after {
      content: "";
      position: absolute;
      inset: auto -60px -100px auto;
      width: 260px;
      height: 260px;
      border-radius: 999px;
      background: rgba(15, 118, 110, 0.08);
      transform: rotate(18deg);
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.72);
      color: var(--accent);
      font-size: 0.88rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    h1, h2, h3 {
      margin: 0;
    }

    h1 {
      margin-top: 18px;
      max-width: 780px;
      font-family: "Fraunces", Georgia, serif;
      font-size: clamp(2rem, 4vw, 3.8rem);
      line-height: 1.02;
      letter-spacing: -0.03em;
    }

    .hero p {
      max-width: 760px;
      margin: 16px 0 0;
      color: var(--muted);
      font-size: 1.02rem;
      line-height: 1.6;
    }

    .layout {
      display: grid;
      grid-template-columns: 340px minmax(0, 1fr);
      gap: 24px;
      margin-top: 24px;
    }

    .panel {
      background: var(--panel);
      border: 1px solid rgba(255,255,255,0.56);
      border-radius: var(--radius);
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }

    .upload-panel {
      padding: 24px;
      position: sticky;
      top: 20px;
      align-self: start;
    }

    .section-title {
      font-size: 1.12rem;
      font-weight: 700;
      margin-bottom: 6px;
    }

    .section-copy {
      margin: 0 0 18px;
      color: var(--muted);
      line-height: 1.55;
      font-size: 0.96rem;
    }

    .field {
      display: grid;
      gap: 8px;
      margin-bottom: 16px;
    }

    .field label {
      font-size: 0.92rem;
      font-weight: 700;
    }

    .field select,
    .field input[type="file"] {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 14px;
      padding: 13px 14px;
      font: inherit;
      background: rgba(255,255,255,0.86);
      color: var(--ink);
    }

    .field small {
      color: var(--muted);
      line-height: 1.45;
    }

    .cta {
      width: 100%;
      border: 0;
      border-radius: 16px;
      padding: 14px 18px;
      background: linear-gradient(135deg, #0f766e, #115e59);
      color: #fff;
      font: inherit;
      font-weight: 700;
      cursor: pointer;
      transition: transform 160ms ease, box-shadow 160ms ease, filter 160ms ease;
      box-shadow: 0 12px 24px rgba(15, 118, 110, 0.22);
    }

    .cta:hover {
      filter: brightness(1.03);
      transform: translateY(-1px);
    }

    .cta:disabled {
      cursor: wait;
      opacity: 0.72;
      transform: none;
      box-shadow: none;
    }

    .microcopy {
      margin-top: 14px;
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.5;
    }

    .content {
      display: grid;
      gap: 18px;
    }

    .status-banner {
      display: none;
      padding: 18px 20px;
      border-radius: 20px;
      border: 1px solid transparent;
      animation: slideUp 260ms ease;
    }

    .status-banner.active {
      display: block;
    }

    .status-banner.info {
      background: rgba(255,255,255,0.72);
      border-color: rgba(15, 118, 110, 0.18);
    }

    .status-banner.success {
      background: rgba(236, 253, 245, 0.8);
      border-color: rgba(15, 118, 110, 0.2);
    }

    .status-banner.error {
      background: rgba(254, 242, 242, 0.92);
      border-color: rgba(180, 35, 24, 0.2);
    }

    .status-banner strong {
      display: block;
      margin-bottom: 6px;
      font-size: 1rem;
    }

    .empty-state {
      padding: 28px;
      border-radius: var(--radius);
      background: rgba(255,255,255,0.7);
      border: 1px dashed rgba(29, 36, 48, 0.14);
      color: var(--muted);
      line-height: 1.6;
    }

    .summary-grid {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 14px;
    }

    .summary-card {
      padding: 18px;
      border-radius: 20px;
      background: var(--panel-strong);
      border: 1px solid rgba(255,255,255,0.6);
      box-shadow: var(--shadow);
      animation: slideUp 320ms ease;
    }

    .summary-card small {
      display: block;
      margin-bottom: 8px;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      font-size: 0.76rem;
      font-weight: 700;
    }

    .summary-card strong {
      font-size: clamp(1.6rem, 2.5vw, 2.2rem);
      font-family: "Fraunces", Georgia, serif;
    }

    .summary-card p {
      margin: 8px 0 0;
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.45;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 6px;
    }

    .ghost-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      padding: 11px 16px;
      border-radius: 999px;
      border: 1px solid rgba(15, 118, 110, 0.18);
      background: rgba(255,255,255,0.72);
      color: var(--ink);
      text-decoration: none;
      font-weight: 600;
    }

    .guide {
      padding: 22px;
    }

    .guide ul {
      margin: 14px 0 0;
      padding-left: 18px;
      color: var(--muted);
      line-height: 1.6;
    }

    .problems {
      display: grid;
      gap: 16px;
    }

    .problem-card {
      overflow: hidden;
      padding: 0;
      animation: slideUp 360ms ease;
    }

    .problem-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      padding: 20px 22px 14px;
      align-items: start;
      border-bottom: 1px solid rgba(29, 36, 48, 0.08);
    }

    .problem-header h3 {
      font-size: 1.1rem;
      margin-bottom: 6px;
    }

    .problem-subtitle {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
    }

    .problem-body {
      display: grid;
      gap: 16px;
      padding: 18px 22px 22px;
    }

    .problem-guide {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
    }

    .guide-card {
      padding: 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.72);
      border: 1px solid rgba(29, 36, 48, 0.08);
    }

    .guide-card strong {
      display: block;
      margin-bottom: 8px;
      font-size: 0.86rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .guide-card p {
      margin: 0;
      color: var(--muted);
      line-height: 1.55;
      font-size: 0.95rem;
    }

    .badge {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 90px;
      padding: 8px 12px;
      border-radius: 999px;
      font-size: 0.84rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }

    .badge.warning {
      background: var(--warning-soft);
      color: var(--warning);
    }

    .badge.error {
      background: var(--error-soft);
      color: var(--error);
    }

    .occurrence-table-wrap {
      overflow-x: auto;
      border-radius: 18px;
      border: 1px solid rgba(29, 36, 48, 0.08);
      background: rgba(255,255,255,0.78);
    }

    table {
      width: 100%;
      border-collapse: collapse;
      min-width: 720px;
    }

    th,
    td {
      padding: 12px 14px;
      text-align: left;
      border-bottom: 1px solid rgba(29, 36, 48, 0.08);
      vertical-align: top;
    }

    th {
      font-size: 0.8rem;
      color: var(--muted);
      text-transform: uppercase;
      letter-spacing: 0.04em;
      background: rgba(29, 36, 48, 0.04);
    }

    td {
      font-size: 0.95rem;
    }

    tr:last-child td {
      border-bottom: 0;
    }

    .field-pill {
      display: inline-flex;
      padding: 5px 9px;
      border-radius: 999px;
      background: rgba(15, 118, 110, 0.1);
      color: var(--accent);
      font-weight: 700;
      font-size: 0.84rem;
    }

    .duplicates-panel {
      padding: 22px;
    }

    .duplicates-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
      gap: 12px;
      margin-top: 14px;
    }

    .duplicate-card {
      padding: 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.76);
      border: 1px solid rgba(29, 36, 48, 0.08);
    }

    .duplicate-card strong {
      display: block;
      margin-bottom: 6px;
      font-size: 1rem;
    }

    .duplicate-card p {
      margin: 4px 0;
      color: var(--muted);
      line-height: 1.45;
      font-size: 0.92rem;
    }

    .helper-text {
      font-size: 0.92rem;
      color: var(--muted);
      line-height: 1.55;
    }

    @keyframes slideUp {
      from {
        opacity: 0;
        transform: translateY(8px);
      }
      to {
        opacity: 1;
        transform: translateY(0);
      }
    }

    @media (max-width: 1040px) {
      .layout {
        grid-template-columns: 1fr;
      }

      .upload-panel {
        position: static;
      }

      .summary-grid,
      .problem-guide {
        grid-template-columns: 1fr 1fr;
      }
    }

    @media (max-width: 720px) {
      .shell {
        width: min(100% - 20px, 100%);
        padding-top: 20px;
      }

      .hero,
      .upload-panel,
      .summary-card,
      .guide,
      .duplicates-panel,
      .problem-header,
      .problem-body {
        padding-left: 18px;
        padding-right: 18px;
      }

      .summary-grid,
      .problem-guide {
        grid-template-columns: 1fr;
      }

      h1 {
        font-size: 2.35rem;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="hero">
      <div class="eyebrow">Central de Correção Patrimonial</div>
      <h1>Envie a planilha e receba instruções claras sobre o que precisa ser corrigido.</h1>
      <p>
        Esta tela traduz o relatório técnico em orientações operacionais para a equipe patrimonial:
        qual linha revisar, qual campo ajustar e por que o item foi sinalizado.
      </p>
    </section>

    <div class="layout">
      <aside class="panel upload-panel">
        <h2 class="section-title">Novo envio</h2>
        <p class="section-copy">
          Escolha o tenant correto, anexe o CSV e aguarde a leitura automática. O sistema vai agrupar
          os problemas por tipo e indicar como corrigir cada caso.
        </p>

        <form id="validation-form">
          <div class="field">
            <label for="tenant">Organização</label>
            <select id="tenant" name="tenant_id">__TENANT_OPTIONS__</select>
            <small>Use a configuração correspondente à organização ou ao cenário de validação.</small>
          </div>

          <div class="field">
            <label for="file">Planilha CSV</label>
            <input id="file" name="file" type="file" accept=".csv,text/csv" required />
            <small>O arquivo deve conter as colunas canônicas esperadas pela validação.</small>
          </div>

          <button id="submit-button" class="cta" type="submit">Analisar planilha</button>
        </form>

        <p class="microcopy">
          Dica: use o PDF apenas como artefato formal. Esta tela foi pensada para orientar a correção
          linha a linha de forma mais rápida.
        </p>
      </aside>

      <main class="content">
        <section id="status-banner" class="status-banner info">
          <strong>Pronto para começar</strong>
          <span>Envie um arquivo para visualizar o resumo operacional.</span>
        </section>

        <section id="summary-section" class="summary-grid" hidden></section>

        <section id="actions-section" class="panel guide" hidden>
          <h2 class="section-title">Próximos passos para a equipe</h2>
          <p class="section-copy">
            Corrija primeiro os erros, depois os avisos. Após atualizar a planilha, faça um novo envio
            para confirmar se os pontos foram resolvidos.
          </p>
          <div class="actions">
            <a id="download-pdf" class="ghost-link" href="#" target="_blank" rel="noopener noreferrer">Baixar PDF</a>
            <a id="download-json" class="ghost-link" href="#" target="_blank" rel="noopener noreferrer">Baixar JSON bruto</a>
          </div>
        </section>

        <section id="guide-section" class="panel guide" hidden>
          <h2 class="section-title">Como ler este resultado</h2>
          <ul>
            <li><strong>Linhas com problemas</strong> mostram quantos registros precisam de revisão.</li>
            <li><strong>Erros</strong> representam inconsistências mais críticas e devem ser tratados primeiro.</li>
            <li><strong>Avisos</strong> indicam baixa qualidade de preenchimento ou ausência de detalhes.</li>
            <li><strong>Linha da planilha</strong> é exibida em formato humano, considerando o cabeçalho do arquivo.</li>
          </ul>
        </section>

        <section id="duplicates-section" class="panel duplicates-panel" hidden></section>

        <section id="problems-section" class="problems" hidden></section>

        <section id="empty-state" class="empty-state">
          Assim que a análise terminar, você verá aqui um resumo com os problemas agrupados por tipo,
          explicações em português claro e uma lista objetiva das linhas que precisam de ajuste.
        </section>
      </main>
    </div>
  </div>

  <script>
    const form = document.getElementById("validation-form");
    const submitButton = document.getElementById("submit-button");
    const statusBanner = document.getElementById("status-banner");
    const summarySection = document.getElementById("summary-section");
    const guideSection = document.getElementById("guide-section");
    const actionsSection = document.getElementById("actions-section");
    const duplicatesSection = document.getElementById("duplicates-section");
    const problemsSection = document.getElementById("problems-section");
    const emptyState = document.getElementById("empty-state");
    const downloadPdfLink = document.getElementById("download-pdf");
    const downloadJsonLink = document.getElementById("download-json");

    const FIELD_LABELS = {
      item: "Item",
      descricao: "Descrição",
      marca: "Marca",
      modelo: "Modelo",
      complemento: "Complemento",
      observacao: "Observação",
      ns: "NS",
      placa_anterior: "Placa anterior",
      flag_item_coletado: "Flag item coletado",
      flag_item_cadastrado_do_zero: "Flag item cadastrado do zero",
    };

    function statusMessage(kind, title, text) {
      statusBanner.className = `status-banner active ${kind}`;
      statusBanner.innerHTML = `<strong>${title}</strong><span>${text}</span>`;
    }

    function lineNumber(rowIndex) {
      return Number(rowIndex) + 2;
    }

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function formatFieldName(field) {
      if (!field) {
        return "Revisão geral";
      }
      return FIELD_LABELS[field] || field;
    }

    function describeIssue(code) {
      if (code === "DUPLICATE_ITEM") {
        return {
          title: "Item duplicado",
          meaning: "Dois ou mais bens estão usando o mesmo identificador patrimonial.",
          action: "Verifique qual código patrimonial está correto e ajuste os itens repetidos para que cada linha tenha um Item único.",
        };
      }

      if (code.startsWith("ZERO_ITEM_COMPLEMENTO_")) {
        return {
          title: "Complemento insuficiente para item novo",
          meaning: "O bem foi cadastrado do zero e o campo Complemento não traz detalhe suficiente para reconhecer o ativo sem ambiguidade.",
          action: "Preencha o Complemento com características físicas ou operacionais que diferenciem o item: cor, capacidade, setor, acabamento, posição, série ou outro detalhe objetivo.",
        };
      }

      if (code === "ZERO_ITEM_MARCA_MISSING") {
        return {
          title: "Marca ausente",
          meaning: "O item novo foi registrado sem a marca do fabricante.",
          action: "Confirme a marca no equipamento, etiqueta ou documento e preencha a coluna Marca.",
        };
      }

      if (code === "ZERO_ITEM_MODELO_MISSING") {
        return {
          title: "Modelo ausente",
          meaning: "O item novo foi registrado sem o modelo do fabricante.",
          action: "Preencha o modelo exato informado na etiqueta, caixa ou nota técnica do bem.",
        };
      }

      if (code.startsWith("FLAG_CONSISTENCY")) {
        return {
          title: "Inconsistência entre placa anterior e flags",
          meaning: "Os indicadores internos do item não batem com a existência ou ausência de Placa Anterior.",
          action: "Revise a Placa Anterior e confirme se o bem já existia em inventários anteriores. Se necessário, gere novamente a base de origem ou ajuste a informação de identificação anterior.",
        };
      }

      if (code.startsWith("CATEGORY_")) {
        return {
          title: "Informação crítica da categoria ausente",
          meaning: "A descrição do bem indica uma categoria que exige um dado obrigatório, mas esse padrão não foi encontrado nos campos analisados.",
          action: "Inclua na descrição, no modelo ou no complemento a característica obrigatória da categoria, como BTU para ar-condicionado ou polegadas para TV.",
        };
      }

      if (code.startsWith("LLM_AUDIT_FINDING")) {
        return {
          title: "Revisão semântica do preenchimento",
          meaning: "A auditoria textual encontrou um ponto de qualidade que pode dificultar a identificação do ativo.",
          action: "Leia a mensagem destacada e ajuste a descrição, marca, modelo, NS, complemento ou observação para deixar o cadastro mais específico.",
        };
      }

      if (code === "LLM_AUDIT_FAILURE" || code === "LLM_AUDIT_PROMPT_NOT_FOUND") {
        return {
          title: "Falha na auditoria automática",
          meaning: "A etapa opcional de revisão por LLM não conseguiu rodar corretamente.",
          action: "Neste caso, a equipe patrimonial não precisa corrigir a planilha. Encaminhe a ocorrência para o suporte técnico do validador.",
        };
      }

      return {
        title: code.replaceAll("_", " "),
        meaning: "Este agrupamento aponta um problema detectado automaticamente na planilha.",
        action: "Revise as linhas listadas abaixo e use a mensagem retornada pelo sistema como referência para o ajuste.",
      };
    }

    function renderSummary(summary) {
      const cleanRows = Math.max(summary.total_rows - summary.rows_with_issues, 0);
      const cards = [
        {
          label: "Linhas lidas",
          value: summary.total_rows,
          copy: "Total de registros avaliados na planilha enviada.",
        },
        {
          label: "Linhas com revisão",
          value: summary.rows_with_issues,
          copy: "Quantidade de linhas que precisam de ajuste antes do próximo envio.",
        },
        {
          label: "Erros",
          value: summary.error_count,
          copy: "Prioridade alta. Corrija estes casos primeiro.",
        },
        {
          label: "Avisos",
          value: summary.warning_count,
          copy: "Melhorias de qualidade e detalhamento do cadastro.",
        },
        {
          label: "Linhas sem ação",
          value: cleanRows,
          copy: "Itens que passaram pela validação sem pendências.",
        },
      ];

      summarySection.innerHTML = cards.map((card) => `
        <article class="summary-card">
          <small>${escapeHtml(card.label)}</small>
          <strong>${escapeHtml(card.value)}</strong>
          <p>${escapeHtml(card.copy)}</p>
        </article>
      `).join("");
      summarySection.hidden = false;
    }

    function renderDuplicates(duplicates) {
      if (!duplicates.length) {
        duplicatesSection.hidden = true;
        duplicatesSection.innerHTML = "";
        return;
      }

      duplicatesSection.innerHTML = `
        <h2 class="section-title">Itens duplicados</h2>
        <p class="section-copy">
          Estes itens compartilham o mesmo código patrimonial. Verifique qual linha deve permanecer com
          o identificador atual e ajuste as demais.
        </p>
        <div class="duplicates-grid">
          ${duplicates.map((dup) => `
            <article class="duplicate-card">
              <strong>${escapeHtml(dup.item)}</strong>
              <p><b>Nome do bem:</b> ${escapeHtml(dup.descricao || "Não informado")}</p>
              <p><b>Ocorrências:</b> ${escapeHtml(dup.count)}</p>
              <p><b>Linhas da planilha:</b> ${dup.row_indices.map((rowIndex) => lineNumber(rowIndex)).join(", ")}</p>
            </article>
          `).join("")}
        </div>
      `;
      duplicatesSection.hidden = false;
    }

    function renderProblems(groupedProblems) {
      const groups = Object.entries(groupedProblems)
        .map(([code, occurrences]) => ({ code, occurrences }))
        .sort((a, b) => b.occurrences.length - a.occurrences.length);

      if (!groups.length) {
        problemsSection.hidden = false;
        problemsSection.innerHTML = `
          <section class="panel guide">
            <h2 class="section-title">Nenhuma pendência agrupada</h2>
            <p class="helper-text">
              A validação não encontrou problemas agrupados por tipo. Se o resumo também estiver zerado,
              a planilha passou sem itens para corrigir.
            </p>
          </section>
        `;
        return;
      }

      problemsSection.innerHTML = groups.map(({ code, occurrences }) => {
        const guide = describeIssue(code);
        const severity = occurrences.some((occ) => occ.severity === "error") ? "error" : "warning";
        const rows = [...occurrences]
          .sort((left, right) => left.row_index - right.row_index)
          .map((occurrence) => `
            <tr>
              <td>${lineNumber(occurrence.row_index)}</td>
              <td>${escapeHtml(occurrence.item || "Não informado")}</td>
              <td>${escapeHtml(occurrence.descricao || "Não informado")}</td>
              <td><span class="field-pill">${escapeHtml(formatFieldName(occurrence.field))}</span></td>
              <td>${escapeHtml(occurrence.message)}</td>
            </tr>
          `)
          .join("");

        return `
          <article class="panel problem-card">
            <div class="problem-header">
              <div>
                <h3>${escapeHtml(guide.title)}</h3>
                <div class="problem-subtitle">${escapeHtml(code)} · ${occurrences.length} ocorrência(s)</div>
              </div>
              <span class="badge ${severity}">${severity === "error" ? "Erro" : "Aviso"}</span>
            </div>
            <div class="problem-body">
              <div class="problem-guide">
                <div class="guide-card">
                  <strong>O que isso significa</strong>
                  <p>${escapeHtml(guide.meaning)}</p>
                </div>
                <div class="guide-card">
                  <strong>Como corrigir</strong>
                  <p>${escapeHtml(guide.action)}</p>
                </div>
              </div>
              <div class="occurrence-table-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Linha da planilha</th>
                      <th>Item</th>
                      <th>Nome do bem</th>
                      <th>Campo a revisar</th>
                      <th>Mensagem do validador</th>
                    </tr>
                  </thead>
                  <tbody>${rows}</tbody>
                </table>
              </div>
            </div>
          </article>
        `;
      }).join("");

      problemsSection.hidden = false;
    }

    async function waitForJob(jobId) {
      while (true) {
        const response = await fetch(`/jobs/${jobId}`);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Falha ao consultar o job.");
        }

        statusMessage(
          "info",
          payload.status === "running" ? "Análise em andamento" : "Arquivo recebido",
          `Status atual: ${payload.status}. Linhas analisadas: ${payload.total_rows}. Problemas encontrados até agora: ${payload.total_issues}.`
        );

        if (payload.status === "completed" || payload.status === "failed") {
          return payload;
        }

        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }

    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      const fileInput = document.getElementById("file");
      const tenantInput = document.getElementById("tenant");

      if (!fileInput.files.length) {
        statusMessage("error", "Arquivo ausente", "Selecione um CSV antes de iniciar a análise.");
        return;
      }

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);

      submitButton.disabled = true;
      statusMessage("info", "Enviando arquivo", "A planilha está sendo recebida pelo validador.");

      try {
        const uploadResponse = await fetch(`/validate?tenant_id=${encodeURIComponent(tenantInput.value)}`, {
          method: "POST",
          body: formData,
        });
        const uploadPayload = await uploadResponse.json();

        if (!uploadResponse.ok) {
          throw new Error(uploadPayload.detail || "Falha ao enviar arquivo.");
        }

        const job = await waitForJob(uploadPayload.job_id);
        if (job.status !== "completed") {
          throw new Error(job.error_message || "O job terminou com falha.");
        }

        const resultResponse = await fetch(`/jobs/${uploadPayload.job_id}/result`);
        const reportData = await resultResponse.json();
        if (!resultResponse.ok) {
          throw new Error(reportData.detail || "Falha ao baixar o resultado estruturado.");
        }

        renderSummary(reportData.summary);
        renderDuplicates(reportData.duplicates || []);
        renderProblems(reportData.grouped_problems || {});

        guideSection.hidden = false;
        actionsSection.hidden = false;
        emptyState.hidden = true;

        downloadPdfLink.href = `/jobs/${uploadPayload.job_id}/report`;
        downloadJsonLink.href = `/jobs/${uploadPayload.job_id}/result`;

        statusMessage(
          "success",
          "Análise concluída",
          `Revise os blocos abaixo. Há ${reportData.summary.rows_with_issues} linha(s) com pendências.`
        );
      } catch (error) {
        statusMessage("error", "Falha na análise", error.message || "Não foi possível concluir a validação.");
      } finally {
        submitButton.disabled = false;
      }
    });

    statusMessage("info", "Pronto para começar", "Envie uma planilha para receber orientações de correção mais claras.");
  </script>
</body>
</html>
"""

    return html.replace("__TENANT_OPTIONS__", tenant_options)
