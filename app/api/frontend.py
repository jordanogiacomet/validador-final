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
    @import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700&family=Source+Serif+4:opsz,wght@8..60,600;8..60,700&display=swap');

    :root {
      --bg: #eef1ef;
      --bg-deep: #dce4e0;
      --shell: #f7f8f6;
      --panel: rgba(255, 255, 255, 0.9);
      --panel-strong: #ffffff;
      --ink: #18212b;
      --muted: #5b6775;
      --line: rgba(24, 33, 43, 0.12);
      --line-strong: rgba(24, 33, 43, 0.2);
      --accent: #154e4a;
      --accent-soft: #e8f1ef;
      --accent-wash: rgba(21, 78, 74, 0.08);
      --warning: #9a5b00;
      --warning-soft: #fff1d6;
      --error: #b42318;
      --error-soft: #fde9e7;
      --success: #1f7a4f;
      --success-soft: #e6f6ee;
      --shadow: 0 24px 60px rgba(24, 33, 43, 0.09);
      --radius-xl: 28px;
      --radius-lg: 22px;
      --radius-md: 16px;
    }

    * {
      box-sizing: border-box;
    }

    body {
      margin: 0;
      min-height: 100vh;
      font-family: "IBM Plex Sans", "Segoe UI", sans-serif;
      color: var(--ink);
      background:
        radial-gradient(circle at 0% 0%, rgba(21, 78, 74, 0.18), transparent 26%),
        radial-gradient(circle at 100% 10%, rgba(154, 91, 0, 0.09), transparent 22%),
        linear-gradient(180deg, var(--bg) 0%, var(--bg-deep) 100%);
    }

    a {
      color: inherit;
    }

    button,
    input,
    select {
      font: inherit;
    }

    .shell {
      width: min(1360px, calc(100% - 32px));
      margin: 0 auto;
      padding: 28px 0 42px;
    }

    .masthead {
      position: relative;
      overflow: hidden;
      display: grid;
      grid-template-columns: minmax(0, 1.45fr) minmax(320px, 0.8fr);
      gap: 24px;
      padding: 30px;
      border-radius: 32px;
      background:
        linear-gradient(140deg, rgba(255,255,255,0.84), rgba(255,255,255,0.62)),
        linear-gradient(120deg, #eff3ef 0%, #fbfcfb 52%, #edf4f1 100%);
      border: 1px solid rgba(255,255,255,0.7);
      box-shadow: var(--shadow);
    }

    .masthead::after {
      content: "";
      position: absolute;
      right: -120px;
      top: -70px;
      width: 320px;
      height: 320px;
      border-radius: 999px;
      background: rgba(21, 78, 74, 0.08);
      filter: blur(4px);
    }

    .eyebrow {
      display: inline-flex;
      align-items: center;
      gap: 10px;
      padding: 8px 14px;
      border-radius: 999px;
      background: rgba(21, 78, 74, 0.08);
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .eyebrow::before {
      content: "";
      width: 8px;
      height: 8px;
      border-radius: 999px;
      background: var(--accent);
    }

    h1,
    h2,
    h3,
    p {
      margin: 0;
    }

    h1 {
      margin-top: 18px;
      max-width: 760px;
      font-family: "Source Serif 4", Georgia, serif;
      font-size: clamp(2.4rem, 4vw, 4.35rem);
      line-height: 0.96;
      letter-spacing: -0.04em;
    }

    .masthead-copy {
      max-width: 760px;
      margin-top: 18px;
      color: var(--muted);
      font-size: 1.02rem;
      line-height: 1.65;
    }

    .masthead-points {
      display: grid;
      gap: 12px;
      align-self: stretch;
      position: relative;
      z-index: 1;
    }

    .point-card {
      padding: 20px 20px 18px;
      border-radius: 22px;
      background: rgba(255,255,255,0.78);
      border: 1px solid rgba(255,255,255,0.72);
      box-shadow: 0 20px 40px rgba(24, 33, 43, 0.07);
    }

    .point-card small {
      display: block;
      margin-bottom: 10px;
      color: var(--accent);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .point-card strong {
      display: block;
      margin-bottom: 8px;
      font-size: 1.08rem;
    }

    .point-card p {
      color: var(--muted);
      line-height: 1.55;
      font-size: 0.95rem;
    }

    .workspace {
      display: grid;
      grid-template-columns: 360px minmax(0, 1fr);
      gap: 24px;
      margin-top: 24px;
      align-items: start;
    }

    .panel {
      background: var(--panel);
      border: 1px solid rgba(255,255,255,0.72);
      border-radius: var(--radius-xl);
      box-shadow: var(--shadow);
      backdrop-filter: blur(10px);
    }

    .sidebar {
      position: sticky;
      top: 18px;
      display: grid;
      gap: 18px;
    }

    .control-card {
      padding: 24px;
    }

    .panel-kicker {
      margin-bottom: 10px;
      color: var(--accent);
      font-size: 0.8rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .panel-title {
      font-size: 1.24rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .panel-copy {
      margin-top: 8px;
      color: var(--muted);
      line-height: 1.58;
      font-size: 0.95rem;
    }

    .form-grid {
      display: grid;
      gap: 16px;
      margin-top: 22px;
    }

    .field {
      display: grid;
      gap: 8px;
    }

    .field label {
      font-size: 0.9rem;
      font-weight: 700;
      letter-spacing: 0.01em;
    }

    .field select {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 13px 14px;
      background: rgba(255,255,255,0.92);
      color: var(--ink);
    }

    .field small {
      color: var(--muted);
      line-height: 1.45;
    }

    .file-picker {
      border: 1px solid var(--line);
      border-radius: 18px;
      padding: 14px;
      background: rgba(255,255,255,0.92);
    }

    .file-picker-top {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      align-items: center;
    }

    .file-trigger {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 0 16px;
      border-radius: 999px;
      background: var(--accent);
      color: #fff;
      font-weight: 700;
      cursor: pointer;
      text-decoration: none;
      transition: filter 160ms ease, transform 160ms ease;
    }

    .file-trigger:hover {
      filter: brightness(1.03);
      transform: translateY(-1px);
    }

    .file-input {
      position: absolute;
      width: 1px;
      height: 1px;
      opacity: 0;
      pointer-events: none;
    }

    .file-name {
      display: block;
      margin-top: 14px;
      font-weight: 600;
      color: var(--ink);
      line-height: 1.5;
      word-break: break-word;
    }

    .file-help {
      margin-top: 8px;
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.45;
    }

    .cta {
      width: 100%;
      border: 0;
      border-radius: 18px;
      padding: 14px 18px;
      background: linear-gradient(135deg, #154e4a 0%, #123f3c 100%);
      color: #fff;
      font-weight: 700;
      cursor: pointer;
      transition: transform 160ms ease, filter 160ms ease, box-shadow 160ms ease;
      box-shadow: 0 18px 30px rgba(21, 78, 74, 0.18);
    }

    .cta:hover {
      filter: brightness(1.03);
      transform: translateY(-1px);
    }

    .cta:disabled {
      cursor: wait;
      opacity: 0.76;
      transform: none;
      box-shadow: none;
    }

    .support-list {
      display: grid;
      gap: 12px;
      margin-top: 20px;
      padding-top: 18px;
      border-top: 1px solid var(--line);
    }

    .support-item {
      display: grid;
      gap: 4px;
    }

    .support-item strong {
      font-size: 0.92rem;
    }

    .support-item span {
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.45;
    }

    .main {
      display: grid;
      gap: 18px;
    }

    .process-card {
      padding: 22px;
    }

    .process-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
    }

    .status-chip {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 122px;
      min-height: 40px;
      padding: 0 14px;
      border-radius: 999px;
      font-size: 0.84rem;
      font-weight: 700;
      text-transform: uppercase;
      letter-spacing: 0.06em;
    }

    .status-chip.info {
      background: var(--accent-soft);
      color: var(--accent);
    }

    .status-chip.success {
      background: var(--success-soft);
      color: var(--success);
    }

    .status-chip.warning {
      background: var(--warning-soft);
      color: var(--warning);
    }

    .status-chip.error {
      background: var(--error-soft);
      color: var(--error);
    }

    .status-title {
      margin-top: 6px;
      font-size: 1.4rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .status-detail {
      margin-top: 10px;
      color: var(--muted);
      line-height: 1.58;
      max-width: 780px;
    }

    .lot-grid {
      display: grid;
      grid-template-columns: 1.2fr 1fr;
      gap: 16px;
      margin-top: 20px;
    }

    .lot-card {
      padding: 18px;
      border-radius: 22px;
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(24, 33, 43, 0.08);
    }

    .lot-card dl {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px 16px;
      margin: 0;
    }

    .lot-card dt {
      margin-bottom: 4px;
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.07em;
      text-transform: uppercase;
    }

    .lot-card dd {
      margin: 0;
      font-size: 0.98rem;
      font-weight: 600;
      line-height: 1.45;
      word-break: break-word;
    }

    .step-list {
      display: grid;
      gap: 12px;
      margin: 0;
      padding: 0;
      list-style: none;
    }

    .step-item {
      display: grid;
      grid-template-columns: 28px minmax(0, 1fr);
      gap: 12px;
      align-items: start;
      padding: 12px 14px;
      border-radius: 18px;
      border: 1px solid rgba(24, 33, 43, 0.08);
      background: rgba(255,255,255,0.74);
    }

    .step-dot {
      width: 28px;
      height: 28px;
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      justify-content: center;
      font-size: 0.78rem;
      font-weight: 700;
      background: rgba(24, 33, 43, 0.08);
      color: var(--muted);
    }

    .step-item.complete .step-dot {
      background: var(--accent);
      color: #fff;
    }

    .step-item.active {
      border-color: rgba(21, 78, 74, 0.24);
      background: var(--accent-soft);
    }

    .step-item.active .step-dot {
      background: var(--accent);
      color: #fff;
    }

    .step-item.failed {
      border-color: rgba(180, 35, 24, 0.22);
      background: rgba(253, 233, 231, 0.68);
    }

    .step-item.failed .step-dot {
      background: var(--error);
      color: #fff;
    }

    .step-item strong {
      display: block;
      font-size: 0.96rem;
      margin-bottom: 4px;
    }

    .step-item span {
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.45;
    }

    .summary-grid {
      display: grid;
      grid-template-columns: repeat(6, minmax(0, 1fr));
      gap: 14px;
    }

    .state-banner {
      display: grid;
      gap: 8px;
      padding: 20px 22px;
    }

    .state-banner small {
      color: var(--muted);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .state-banner strong {
      font-size: 1.08rem;
      letter-spacing: -0.01em;
    }

    .state-banner p {
      color: var(--muted);
      line-height: 1.55;
      margin: 0;
    }

    .state-banner.info {
      border: 1px solid rgba(21, 78, 74, 0.14);
      background: rgba(232, 241, 239, 0.86);
    }

    .state-banner.warning {
      border: 1px solid rgba(154, 91, 0, 0.16);
      background: rgba(255, 241, 214, 0.88);
    }

    .state-banner.success {
      border: 1px solid rgba(31, 122, 79, 0.16);
      background: rgba(230, 246, 238, 0.9);
    }

    .state-banner.error {
      border: 1px solid rgba(180, 35, 24, 0.14);
      background: rgba(253, 233, 231, 0.9);
    }

    .summary-card {
      padding: 18px;
      border-radius: 22px;
      background: var(--panel-strong);
      border: 1px solid rgba(255,255,255,0.82);
      box-shadow: var(--shadow);
    }

    .summary-card small {
      display: block;
      margin-bottom: 10px;
      color: var(--muted);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .summary-card strong {
      display: block;
      font-family: "Source Serif 4", Georgia, serif;
      font-size: clamp(1.8rem, 3vw, 2.35rem);
      line-height: 0.95;
      letter-spacing: -0.04em;
    }

    .summary-card p {
      margin-top: 10px;
      color: var(--muted);
      line-height: 1.5;
      font-size: 0.9rem;
    }

    .summary-card.error strong {
      color: var(--error);
    }

    .summary-card.warning strong {
      color: var(--warning);
    }

    .summary-card.success strong {
      color: var(--success);
    }

    .priority-card,
    .actions-card,
    .duplicates-card,
    .nav-card,
    .problem-card,
    .empty-card,
    .clean-card {
      padding: 22px;
    }

    .priority-card {
      display: grid;
      grid-template-columns: minmax(0, 1.15fr) 280px;
      gap: 18px;
    }

    .priority-box {
      padding: 18px;
      border-radius: 22px;
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(24, 33, 43, 0.08);
    }

    .priority-box strong {
      display: block;
      margin-bottom: 8px;
      font-size: 1.14rem;
    }

    .priority-box p,
    .priority-box li {
      color: var(--muted);
      line-height: 1.55;
    }

    .priority-box ul {
      margin: 0;
      padding-left: 18px;
    }

    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }

    .action-link {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 0 16px;
      border-radius: 999px;
      border: 1px solid rgba(21, 78, 74, 0.18);
      background: rgba(255,255,255,0.9);
      color: var(--ink);
      text-decoration: none;
      font-weight: 700;
    }

    .metric-stack {
      display: grid;
      gap: 12px;
    }

    .metric-tile {
      padding: 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(24, 33, 43, 0.08);
    }

    .metric-tile small {
      display: block;
      color: var(--muted);
      font-size: 0.75rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .metric-tile strong {
      display: block;
      margin-top: 6px;
      font-size: 1.6rem;
    }

    .metric-tile span {
      display: block;
      margin-top: 6px;
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.45;
    }

    .nav-chips {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }

    .nav-chip {
      display: inline-flex;
      align-items: center;
      gap: 8px;
      min-height: 42px;
      padding: 0 14px;
      border-radius: 999px;
      background: rgba(255,255,255,0.9);
      border: 1px solid rgba(24, 33, 43, 0.08);
      text-decoration: none;
      color: var(--ink);
      font-weight: 600;
    }

    .nav-chip.error {
      border-color: rgba(180, 35, 24, 0.16);
      background: rgba(253, 233, 231, 0.66);
    }

    .nav-chip.warning {
      border-color: rgba(154, 91, 0, 0.18);
      background: rgba(255, 241, 214, 0.8);
    }

    .duplicates-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
      margin-top: 16px;
    }

    .duplicate-card {
      padding: 18px;
      border-radius: 20px;
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(24, 33, 43, 0.08);
    }

    .duplicate-card strong {
      display: block;
      margin-bottom: 8px;
      font-size: 1.05rem;
    }

    .duplicate-card p {
      color: var(--muted);
      line-height: 1.5;
      font-size: 0.92rem;
      margin-top: 5px;
    }

    .problems {
      display: grid;
      gap: 16px;
    }

    .problem-card {
      scroll-margin-top: 24px;
    }

    .problem-header {
      display: flex;
      justify-content: space-between;
      gap: 16px;
      align-items: start;
      margin-bottom: 18px;
    }

    .problem-kicker {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      background: rgba(21, 78, 74, 0.08);
      color: var(--accent);
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .problem-title {
      margin-top: 10px;
      font-size: 1.28rem;
      font-weight: 700;
      letter-spacing: -0.02em;
    }

    .problem-meta {
      margin-top: 8px;
      color: var(--muted);
      line-height: 1.5;
      font-size: 0.92rem;
    }

    .problem-layout {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 14px;
      margin-bottom: 16px;
    }

    .detail-box {
      padding: 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(24, 33, 43, 0.08);
    }

    .detail-box small {
      display: block;
      margin-bottom: 8px;
      color: var(--accent);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .detail-box p {
      color: var(--muted);
      line-height: 1.55;
      font-size: 0.94rem;
    }

    .table-wrap {
      overflow-x: auto;
      border-radius: 20px;
      border: 1px solid rgba(24, 33, 43, 0.08);
      background: rgba(255,255,255,0.92);
    }

    table {
      width: 100%;
      min-width: 760px;
      border-collapse: collapse;
    }

    th,
    td {
      padding: 12px 14px;
      text-align: left;
      vertical-align: top;
      border-bottom: 1px solid rgba(24, 33, 43, 0.08);
    }

    th {
      background: var(--accent);
      color: #fff;
      font-size: 0.78rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    td {
      font-size: 0.94rem;
      line-height: 1.5;
    }

    tr:last-child td {
      border-bottom: 0;
    }

    .field-pill {
      display: inline-flex;
      align-items: center;
      min-height: 30px;
      padding: 0 10px;
      border-radius: 999px;
      background: var(--accent-wash);
      color: var(--accent);
      font-size: 0.82rem;
      font-weight: 700;
    }

    .empty-card,
    .clean-card {
      background:
        linear-gradient(140deg, rgba(255,255,255,0.86), rgba(255,255,255,0.72)),
        linear-gradient(135deg, rgba(21, 78, 74, 0.03), rgba(255,255,255,0));
    }

    .empty-card p,
    .clean-card p {
      margin-top: 10px;
      color: var(--muted);
      line-height: 1.6;
      max-width: 760px;
    }

    .clean-card {
      border: 1px solid rgba(31, 122, 79, 0.12);
    }

    .hidden {
      display: none !important;
    }

    @media (max-width: 1180px) {
      .workspace,
      .masthead,
      .priority-card,
      .lot-grid {
        grid-template-columns: 1fr;
      }

      .sidebar {
        position: static;
      }

      .summary-grid {
        grid-template-columns: repeat(3, minmax(0, 1fr));
      }
    }

    @media (max-width: 760px) {
      .shell {
        width: min(100% - 20px, 100%);
        padding-top: 18px;
      }

      .masthead,
      .control-card,
      .process-card,
      .priority-card,
      .actions-card,
      .duplicates-card,
      .nav-card,
      .problem-card,
      .empty-card,
      .clean-card {
        padding-left: 18px;
        padding-right: 18px;
      }

      .summary-grid,
      .problem-layout,
      .lot-card dl {
        grid-template-columns: 1fr;
      }

      .process-header,
      .problem-header {
        flex-direction: column;
      }

      h1 {
        font-size: 2.45rem;
      }
    }
  </style>
</head>
<body>
  <div class="shell">
    <section class="masthead">
      <div>
        <div class="eyebrow">Central de Correção Patrimonial</div>
        <h1>Transforme o retorno técnico em uma rotina clara de correção operacional.</h1>
        <p class="masthead-copy">
          Esta tela organiza o lote enviado, mostra o estado do processamento e apresenta as pendências em ordem de tratamento.
          O objetivo é reduzir ambiguidade, acelerar a revisão da planilha e dar uma leitura institucional ao resultado.
        </p>
      </div>
      <div class="masthead-points">
        <article class="point-card">
          <small>Padrão corporativo</small>
          <strong>Resumo executivo, priorização e artefatos do lote em uma única área de trabalho.</strong>
          <p>Sem navegar por endpoints ou interpretar retorno técnico bruto para saber o que corrigir primeiro.</p>
        </article>
        <article class="point-card">
          <small>Foco operacional</small>
          <strong>Erros, avisos e ações exigidas aparecem separados com hierarquia clara.</strong>
          <p>As equipes patrimoniais enxergam rapidamente qual linha revisar, qual campo atuar e qual impacto cada problema traz.</p>
        </article>
      </div>
    </section>

    <div class="workspace">
      <aside class="sidebar">
        <section class="panel control-card">
          <div class="panel-kicker">Entrada do lote</div>
          <h2 class="panel-title">Novo processamento</h2>
          <p class="panel-copy">
            Selecione a organização correta, anexe a planilha CSV e acompanhe o lote até a publicação do resumo e do PDF.
          </p>

          <form id="validation-form" class="form-grid">
            <div class="field">
              <label for="tenant">Organização</label>
              <select id="tenant" name="tenant_id">__TENANT_OPTIONS__</select>
              <small>Use a configuração correspondente ao ambiente ou contrato patrimonial que deve reger a validação.</small>
            </div>

            <div class="field">
              <label for="file">Planilha CSV</label>
              <div class="file-picker">
                <div class="file-picker-top">
                  <label class="file-trigger" for="file">Selecionar arquivo</label>
                  <span class="panel-kicker" style="margin: 0;">CSV</span>
                </div>
                <input id="file" class="file-input" name="file" type="file" accept=".csv,text/csv" required />
                <span id="file-name" class="file-name">Nenhum arquivo selecionado.</span>
                <div class="file-help">O validador espera um arquivo tabular com cabeçalho na primeira linha. Envie sempre a versão mais recente do lote corrigido.</div>
              </div>
            </div>

            <button id="submit-button" class="cta" type="submit">Processar lote</button>
          </form>

          <div class="support-list">
            <div class="support-item">
              <strong>O que esta tela entrega</strong>
              <span>Resumo executivo, trilha de processamento, blocos de correção priorizados e acesso aos artefatos finais.</span>
            </div>
            <div class="support-item">
              <strong>Uso recomendado</strong>
              <span>Corrija primeiro os erros, depois os avisos. Reenvie a planilha apenas quando o lote estiver ajustado.</span>
            </div>
            <div class="support-item">
              <strong>Artefatos disponíveis</strong>
              <span>Relatório PDF institucional para registro e dados estruturados para consulta detalhada quando necessário.</span>
            </div>
          </div>
        </section>
      </aside>

      <main class="main">
        <section id="process-card" class="panel process-card">
          <div class="process-header">
            <div>
              <div class="panel-kicker">Acompanhamento do lote</div>
              <h2 id="status-title" class="status-title">Pronto para receber um novo arquivo</h2>
              <p id="status-detail" class="status-detail">Assim que a planilha for enviada, esta área passará a exibir o estado do processamento, a identificação do lote e a trilha de etapas até o relatório final.</p>
            </div>
            <span id="status-chip" class="status-chip info">Aguardando</span>
          </div>

          <div class="lot-grid">
            <section class="lot-card">
              <div class="panel-kicker">Identificação</div>
              <dl id="lot-metadata">
                <div>
                  <dt>Organização</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>Arquivo</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>Job</dt>
                  <dd>-</dd>
                </div>
                <div>
                  <dt>Atualizado em</dt>
                  <dd>-</dd>
                </div>
              </dl>
            </section>

            <section class="lot-card">
              <div class="panel-kicker">Trilha de processamento</div>
              <ol id="step-list" class="step-list"></ol>
            </section>
          </div>
        </section>

        <section id="state-banner" class="panel state-banner hidden"></section>

        <section id="summary-section" class="summary-grid hidden"></section>

        <section id="priority-section" class="panel priority-card hidden"></section>

        <section id="actions-section" class="panel actions-card hidden">
          <div class="panel-kicker">Artefatos do lote</div>
          <h2 class="panel-title">Saídas consolidadas para consulta e registro</h2>
          <p class="panel-copy">Use o PDF para distribuição institucional e o arquivo estruturado apenas quando precisar aprofundar a análise do lote.</p>
          <div class="actions">
            <a id="download-pdf" class="action-link" href="#" target="_blank" rel="noopener noreferrer">Baixar relatório PDF</a>
            <a id="download-json" class="action-link" href="#" target="_blank" rel="noopener noreferrer">Baixar dados estruturados</a>
          </div>
        </section>

        <section id="duplicates-section" class="panel duplicates-card hidden"></section>

        <section id="nav-section" class="panel nav-card hidden"></section>

        <section id="clean-section" class="panel clean-card hidden"></section>

        <section id="problems-section" class="problems hidden"></section>

        <section id="empty-state" class="panel empty-card">
          <div class="panel-kicker">Workspace operacional</div>
          <h2 class="panel-title">O lote ainda não foi processado</h2>
          <p>
            Depois do envio, o sistema mostra a identificação do arquivo, a etapa atual do processamento, o resumo executivo do lote e os blocos de correção agrupados por tipo de problema.
          </p>
        </section>
      </main>
    </div>
  </div>

  <script>
    const PROCESS_STEPS = [
      {
        id: "file_received",
        label: "Arquivo recebido",
        detail: "O lote foi registrado e entrou na fila interna de processamento.",
      },
      {
        id: "reading_lot",
        label: "Leitura do lote",
        detail: "O arquivo está sendo importado e preparado para validação.",
      },
      {
        id: "indexing_global",
        label: "Indexação global",
        detail: "O conjunto completo do lote está sendo mapeado para liberar apenas prévias confiáveis.",
      },
      {
        id: "validating_batches",
        label: "Validação em batches",
        detail: "A prévia operacional é atualizada em etapas com contexto completo do lote.",
      },
      {
        id: "building_artifacts",
        label: "Consolidação dos artefatos",
        detail: "Resumo executivo, dados estruturados e PDF estão sendo montados.",
      },
      {
        id: "report_ready",
        label: "Relatório pronto",
        detail: "O lote foi concluído e os artefatos estão disponíveis para consulta.",
      },
    ];

    const FIELD_LABELS = {
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

    const form = document.getElementById("validation-form");
    const fileInput = document.getElementById("file");
    const fileName = document.getElementById("file-name");
    const tenantInput = document.getElementById("tenant");
    const submitButton = document.getElementById("submit-button");
    const statusTitle = document.getElementById("status-title");
    const statusDetail = document.getElementById("status-detail");
    const statusChip = document.getElementById("status-chip");
    const lotMetadata = document.getElementById("lot-metadata");
    const stepList = document.getElementById("step-list");
    const stateBanner = document.getElementById("state-banner");
    const summarySection = document.getElementById("summary-section");
    const prioritySection = document.getElementById("priority-section");
    const actionsSection = document.getElementById("actions-section");
    const duplicatesSection = document.getElementById("duplicates-section");
    const navSection = document.getElementById("nav-section");
    const cleanSection = document.getElementById("clean-section");
    const problemsSection = document.getElementById("problems-section");
    const emptyState = document.getElementById("empty-state");
    const downloadPdfLink = document.getElementById("download-pdf");
    const downloadJsonLink = document.getElementById("download-json");

    const workspaceContext = {
      organizationLabel: tenantInput.options[tenantInput.selectedIndex]?.text || "-",
      fileName: null,
    };

    function escapeHtml(value) {
      return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
    }

    function slugify(value) {
      return String(value || "")
        .toLowerCase()
        .replaceAll(/[^a-z0-9]+/g, "-")
        .replaceAll(/^-+|-+$/g, "");
    }

    function lineNumber(rowIndex) {
      return Number(rowIndex) + 2;
    }

    function formatFieldName(field) {
      if (!field) {
        return "Revisão geral";
      }
      return FIELD_LABELS[field] || field;
    }

    function formatDateTime(value) {
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

    function formatStatusChip(job) {
      const status = job?.status;
      if (status === "queued") {
        return { label: "Recebido", kind: "info" };
      }
      if (status === "completed") {
        return { label: "Consolidado", kind: "success" };
      }
      if (status === "failed") {
        return { label: "Falha", kind: "error" };
      }
      if (job?.is_partial_result_available) {
        return { label: "Prévia em atualização", kind: "warning" };
      }
      return { label: "Em processamento", kind: "info" };
    }

    function setEmptyState(title, detail) {
      emptyState.innerHTML = `
        <div class="panel-kicker">Workspace operacional</div>
        <h2 class="panel-title">${escapeHtml(title)}</h2>
        <p>${escapeHtml(detail)}</p>
      `;
      emptyState.classList.remove("hidden");
    }

    function renderStateBanner(kind, label, detail) {
      stateBanner.className = `panel state-banner ${kind}`;
      stateBanner.innerHTML = `
        <small>Estado do lote</small>
        <strong>${escapeHtml(label)}</strong>
        <p>${escapeHtml(detail)}</p>
      `;
      stateBanner.classList.remove("hidden");
    }

    function hideStateBanner() {
      stateBanner.classList.add("hidden");
      stateBanner.innerHTML = "";
    }

    function getPreviewReportData(job) {
      if (!job?.is_partial_result_available) {
        return null;
      }

      return {
        summary: job.partial_summary || {},
        duplicates: job.partial_duplicates || [],
        grouped_problems: job.partial_grouped_problems || {},
        row_results: job.row_results_preview || [],
      };
    }

    function describeIssue(code) {
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

      if (code.startsWith("CATEGORY_") && code.endsWith("_REQUIRED")) {
        return {
          title: "Campo esperado da espécie não preenchido",
          context: "Para esta espécie de bem, a organização espera um campo obrigatório para identificar o ativo com segurança.",
          impact: "Sem esse campo, a linha continua operacionalmente fraca e depende de interpretação manual para ser validada.",
          action: "Preencha o campo destacado seguindo o padrão patrimonial adotado para essa espécie de bem.",
        };
      }

      if (code.startsWith("CATEGORY_")) {
        return {
          title: "Informação crítica da espécie ausente",
          context: "A classificação do bem exige um detalhe técnico mínimo, mas esse padrão não foi encontrado nos campos avaliados.",
          impact: "O lote avança com identificação incompleta e a revisão passa a depender de verificação manual adicional.",
          action: "Inclua a característica técnica obrigatória no campo indicado, como BTU, polegadas ou outro atributo essencial da espécie.",
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

    function renderLotMetadata(job) {
      const organization = workspaceContext.organizationLabel || "-";
      const fileLabel = job?.file_name || workspaceContext.fileName || "-";
      const updatedAt = formatDateTime(job?.updated_at);

      lotMetadata.innerHTML = `
        <div>
          <dt>Organização</dt>
          <dd>${escapeHtml(organization)}</dd>
        </div>
        <div>
          <dt>Arquivo</dt>
          <dd>${escapeHtml(fileLabel)}</dd>
        </div>
        <div>
          <dt>Job</dt>
          <dd>${escapeHtml(job?.job_id || "-")}</dd>
        </div>
        <div>
          <dt>Atualizado em</dt>
          <dd>${escapeHtml(updatedAt)}</dd>
        </div>
      `;
    }

    function renderSteps(job) {
      const activeIndex = PROCESS_STEPS.findIndex((step) => step.id === job?.current_step);
      const isFailed = job?.status === "failed";

      stepList.innerHTML = PROCESS_STEPS.map((step, index) => {
        let state = "pending";
        if (isFailed) {
          if (activeIndex >= 0 && index < activeIndex) {
            state = "complete";
          } else if (activeIndex === index) {
            state = "failed";
          }
        } else if (activeIndex >= 0 && index < activeIndex) {
          state = "complete";
        } else if (activeIndex === index) {
          state = "active";
        } else if (!job && index === 0) {
          state = "active";
        }

        if (job?.status === "completed" && step.id === "report_ready") {
          state = "complete";
        }

        const dotLabel = state === "complete" ? "OK" : index + 1;
        return `
          <li class="step-item ${escapeHtml(state)}">
            <span class="step-dot">${escapeHtml(dotLabel)}</span>
            <div>
              <strong>${escapeHtml(step.label)}</strong>
              <span>${escapeHtml(step.detail)}</span>
            </div>
          </li>
        `;
      }).join("");
    }

    function renderProcessCard(job) {
      const chip = formatStatusChip(job);
      statusChip.className = `status-chip ${chip.kind}`;
      statusChip.textContent = chip.label;
      statusTitle.textContent = job?.status_title || "Pronto para receber um novo arquivo";
      statusDetail.textContent = job?.status_detail || "Assim que a planilha for enviada, esta área passará a exibir o estado do processamento, a identificação do lote e a trilha de etapas até o relatório final.";
      renderLotMetadata(job);
      renderSteps(job);
    }

    function renderSummary(summary, options = {}) {
      const isPartial = options.mode === "partial";
      const processedRows = Number(options.processedRows ?? summary.processed_rows ?? summary.total_rows ?? 0);
      const totalRows = Number(summary.total_rows ?? 0);
      const cleanRows = Math.max(
        (isPartial ? processedRows : totalRows) - Number(summary.rows_with_issues ?? 0),
        0,
      );

      const cards = isPartial
        ? [
            {
              label: "Linhas do lote",
              value: totalRows,
              copy: "Base completa já indexada para suportar a prévia com contexto global.",
              className: "",
            },
            {
              label: "Linhas validadas",
              value: processedRows,
              copy: "Parcela já consolidada na prévia operacional em atualização.",
              className: "",
            },
            {
              label: "Linhas com revisão",
              value: summary.rows_with_issues,
              copy: "Registros já avaliados que exigem ajuste nesta altura do processamento.",
              className: "",
            },
            {
              label: "Total de problemas",
              value: summary.total_issues,
              copy: "Apontamentos já confirmados dentro da prévia atual.",
              className: "",
            },
            {
              label: "Erros",
              value: summary.error_count,
              copy: "Pendências críticas já confirmadas na parcela validada.",
              className: "error",
            },
            {
              label: "Avisos",
              value: summary.warning_count,
              copy: "Pontos de qualidade já identificados na prévia em atualização.",
              className: "warning",
            },
          ]
        : [
            {
              label: "Linhas lidas",
              value: totalRows,
              copy: "Total de registros processados no lote atual.",
              className: "",
            },
            {
              label: "Linhas com revisão",
              value: summary.rows_with_issues,
              copy: "Registros que ainda exigem ajuste antes do próximo envio.",
              className: "",
            },
            {
              label: "Total de problemas",
              value: summary.total_issues,
              copy: "Soma dos apontamentos consolidados pelo validador.",
              className: "",
            },
            {
              label: "Erros",
              value: summary.error_count,
              copy: "Pendências críticas. Devem liderar a ordem de tratamento.",
              className: "error",
            },
            {
              label: "Avisos",
              value: summary.warning_count,
              copy: "Pontos de qualidade e detalhamento que precisam de complemento.",
              className: "warning",
            },
            {
              label: "Linhas sem ação",
              value: cleanRows,
              copy: "Registros que passaram pelo lote sem apontamentos ativos.",
              className: "success",
            },
          ];

      summarySection.innerHTML = cards.map((card) => `
        <article class="summary-card ${escapeHtml(card.className)}">
          <small>${escapeHtml(card.label)}</small>
          <strong>${escapeHtml(card.value)}</strong>
          <p>${escapeHtml(card.copy)}</p>
        </article>
      `).join("");
      summarySection.classList.remove("hidden");
    }

    function renderPriority(reportData, options = {}) {
      const isPartial = options.mode === "partial";
      const { summary, duplicates } = reportData;
      const duplicateCount = (duplicates || []).length;
      const processedRows = Number(options.processedRows ?? summary.processed_rows ?? summary.total_rows ?? 0);
      const totalRows = Number(summary.total_rows ?? 0);
      let headline = "Nenhuma pendência crítica identificada.";
      let copy = "O lote pode seguir para conferência final ou arquivamento, sem necessidade de nova rodada de correção.";
      let checklist = [
        "Registrar o PDF como artefato formal do lote.",
        "Manter a versão validada da planilha como referência operacional.",
      ];

      if (isPartial) {
        headline = "Prévia operacional em atualização.";
        copy = `Os indicadores abaixo refletem ${processedRows} de ${totalRows} linhas já validadas com contexto completo. O PDF será liberado apenas após a consolidação final.`;
        checklist = [
          "Usar esta prévia para antecipar a triagem do lote sem assumir que a execução já terminou.",
          "Acompanhar as próximas atualizações até o fechamento final do processamento.",
        ];

        if (summary.error_count > 0) {
          headline = "Prioridade preliminar: tratar os erros já confirmados na prévia.";
          checklist = [
            "Atacar primeiro os grupos já confirmados como erro.",
            "Manter a revisão aberta até a consolidação final do lote.",
            "Reprocessar a planilha apenas depois do fechamento do lote atual.",
          ];
        } else if (summary.warning_count > 0) {
          headline = "Prévia sem erros confirmados até agora, com pontos de qualidade em andamento.";
          checklist = [
            "Agrupar ajustes semelhantes enquanto a prévia continua evoluindo.",
            "Aguardar o fechamento do lote para validar o quadro consolidado.",
          ];
        }
      } else if (summary.error_count > 0) {
        headline = "Prioridade imediata: tratar erros antes de qualquer novo envio.";
        copy = "Os erros afetam consistência, identificação ou regras críticas do lote. Resolva esse grupo antes de atacar avisos de qualidade.";
        checklist = [
          "Abrir primeiro os grupos sinalizados como erro.",
          "Tratar duplicidades e inconsistências de identificação antes de revisar detalhes de preenchimento.",
          "Reprocessar a planilha somente depois que os erros tiverem sido resolvidos.",
        ];
      } else if (summary.warning_count > 0) {
        headline = "Lote sem erros críticos, com pontos de qualidade ainda abertos.";
        copy = "Os avisos não bloqueiam a leitura estrutural do lote, mas indicam campos insuficientes ou cadastros com detalhamento abaixo do esperado.";
        checklist = [
          "Usar os grupos por tipo para atacar ocorrências semelhantes em bloco.",
          "Padronizar marca, modelo, complemento e demais campos textuais antes do reenvio.",
        ];
      }

      prioritySection.innerHTML = `
        <div class="priority-box">
          <div class="panel-kicker">${isPartial ? "Direção provisória de tratamento" : "Direção de tratamento"}</div>
          <strong>${escapeHtml(headline)}</strong>
          <p>${escapeHtml(copy)}</p>
          <div class="actions">
            <a class="action-link" href="#problems-section">Ir para os grupos de correção</a>
          </div>
        </div>
        <div class="metric-stack">
          <div class="metric-tile">
            <small>${isPartial ? "Cobertura da prévia" : "Risco de consistência"}</small>
            <strong>${escapeHtml(isPartial ? `${processedRows}/${totalRows}` : summary.error_count)}</strong>
            <span>${isPartial ? "Linhas já validadas com contexto global dentro da execução atual." : summary.error_count > 0 ? "Existem erros que devem ser resolvidos antes do próximo lote." : "Não há erros críticos abertos neste processamento."}</span>
          </div>
          <div class="metric-tile">
            <small>Duplicidades</small>
            <strong>${escapeHtml(duplicateCount)}</strong>
            <span>${duplicateCount > 0 ? "Itens repetidos exigem decisão patrimonial antes do reenvio." : isPartial ? "Nenhuma duplicidade confiável foi identificada após a indexação global." : "Nenhum item duplicado foi encontrado no lote atual."}</span>
          </div>
          <div class="metric-tile">
            <small>Roteiro recomendado</small>
            <span>${checklist.map((item) => escapeHtml(item)).join("<br />")}</span>
          </div>
        </div>
      `;
      prioritySection.classList.remove("hidden");
    }

    function renderDuplicates(duplicates, options = {}) {
      const isPartial = options.mode === "partial";
      if (!duplicates.length) {
        duplicatesSection.classList.add("hidden");
        duplicatesSection.innerHTML = "";
        return;
      }

      duplicatesSection.innerHTML = `
        <div class="panel-kicker">Consistência cadastral</div>
        <h2 class="panel-title">Itens com identificador repetido no lote</h2>
        <p class="panel-copy">${isPartial ? "Esta seção já é confiável durante a execução porque depende da indexação global do lote inteiro. Revise este grupo antes de trabalhar detalhes complementares do cadastro." : "Cada item patrimonial deve aparecer uma única vez. Revise este grupo antes de trabalhar detalhes complementares do cadastro."}</p>
        <div class="duplicates-grid">
          ${duplicates.map((duplicate) => `
            <article class="duplicate-card">
              <strong>${escapeHtml(duplicate.item)}</strong>
              <p><b>Nome do bem:</b> ${escapeHtml(duplicate.descricao || "Não informado")}</p>
              <p><b>Ocorrências:</b> ${escapeHtml(duplicate.count)}</p>
              <p><b>Linhas envolvidas:</b> ${duplicate.row_indices.map((rowIndex) => lineNumber(rowIndex)).join(", ")}</p>
            </article>
          `).join("")}
        </div>
      `;
      duplicatesSection.classList.remove("hidden");
    }

    function renderNav(groups) {
      if (!groups.length) {
        navSection.classList.add("hidden");
        navSection.innerHTML = "";
        return;
      }

      navSection.innerHTML = `
        <div class="panel-kicker">Mapa de navegação</div>
        <h2 class="panel-title">Acesso rápido aos grupos de correção</h2>
        <p class="panel-copy">Os grupos abaixo estão ordenados por criticidade e volume de ocorrências. Use os atalhos para percorrer o lote com mais rapidez.</p>
        <div class="nav-chips">
          ${groups.map(({ code, occurrences }) => {
            const severity = occurrences.some((occurrence) => occurrence.severity === "error") ? "error" : "warning";
            const guide = describeIssue(code);
            return `
              <a class="nav-chip ${severity}" href="#problem-${slugify(code)}">
                <span>${escapeHtml(guide.title)}</span>
                <strong>${escapeHtml(occurrences.length)}</strong>
              </a>
            `;
          }).join("")}
        </div>
      `;
      navSection.classList.remove("hidden");
    }

    function buildScopeSummary(occurrences) {
      const lines = occurrences
        .map((occurrence) => lineNumber(occurrence.row_index))
        .sort((left, right) => left - right);
      const uniqueFields = [...new Set(occurrences.map((occurrence) => formatFieldName(occurrence.field)))];
      const linePreview = lines.slice(0, 5).join(", ");
      const suffix = lines.length > 5 ? ", ..." : "";

      return `Atinge ${occurrences.length} linha(s). Campos mais envolvidos: ${uniqueFields.join(", ")}. Linhas destacadas: ${linePreview}${suffix}.`;
    }

    function renderProblems(groupedProblems, options = {}) {
      const isPartial = options.mode === "partial";
      const groups = Object.entries(groupedProblems)
        .map(([code, occurrences]) => ({ code, occurrences }))
        .sort((left, right) => {
          const leftHasError = left.occurrences.some((occurrence) => occurrence.severity === "error");
          const rightHasError = right.occurrences.some((occurrence) => occurrence.severity === "error");
          if (leftHasError !== rightHasError) {
            return leftHasError ? -1 : 1;
          }
          if (left.occurrences.length !== right.occurrences.length) {
            return right.occurrences.length - left.occurrences.length;
          }
          return left.code.localeCompare(right.code);
        });

      renderNav(groups);

      if (!groups.length) {
        problemsSection.classList.add("hidden");
        problemsSection.innerHTML = "";
        return;
      }

      problemsSection.innerHTML = groups.map(({ code, occurrences }) => {
        const guide = describeIssue(code);
        const severity = occurrences.some((occurrence) => occurrence.severity === "error") ? "error" : "warning";
        const severityLabel = severity === "error" ? "Erro" : "Aviso";
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
          <article id="problem-${slugify(code)}" class="panel problem-card">
            <div class="problem-header">
              <div>
                <span class="problem-kicker">${severity === "error" ? "Prioridade alta" : "Qualidade e complemento"}</span>
                <h3 class="problem-title">${escapeHtml(guide.title)}</h3>
                <p class="problem-meta">${escapeHtml(code)} • ${escapeHtml(occurrences.length)} ocorrência(s) ${isPartial ? "na prévia atual" : "no lote atual"}</p>
              </div>
              <span class="status-chip ${severity === "error" ? "error" : "warning"}">${escapeHtml(severityLabel)}</span>
            </div>

            <div class="problem-layout">
              <section class="detail-box">
                <small>Contexto operacional</small>
                <p>${escapeHtml(guide.context)}</p>
              </section>
              <section class="detail-box">
                <small>Impacto na correção</small>
                <p>${escapeHtml(guide.impact)}</p>
              </section>
              <section class="detail-box">
                <small>Ação exigida</small>
                <p>${escapeHtml(guide.action)}</p>
              </section>
              <section class="detail-box">
                <small>Escopo deste grupo</small>
                <p>${escapeHtml(buildScopeSummary(occurrences))}</p>
              </section>
            </div>

            <div class="table-wrap">
              <table>
                <thead>
                  <tr>
                    <th>Linha</th>
                    <th>Item</th>
                    <th>Nome do bem</th>
                    <th>Campo a revisar</th>
                    <th>Orientação do validador</th>
                  </tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
          </article>
        `;
      }).join("");
      problemsSection.classList.remove("hidden");
    }

    function renderCleanState(summary, options = {}) {
      const isPartial = options.mode === "partial";
      const processedRows = Number(options.processedRows ?? summary.processed_rows ?? summary.total_rows ?? 0);

      if (summary.rows_with_issues > 0) {
        cleanSection.classList.add("hidden");
        cleanSection.innerHTML = "";
        return;
      }

      cleanSection.innerHTML = `
        <div class="panel-kicker">Resultado do lote</div>
        <h2 class="panel-title">${isPartial ? "Nenhuma pendência foi confirmada na prévia atual" : "Nenhuma correção foi exigida neste processamento"}</h2>
        <p>${isPartial ? `As ${processedRows} linhas já validadas não geraram apontamentos até este momento. Continue acompanhando a execução até a consolidação final do lote.` : "O arquivo passou pela validação sem pendências abertas. Ainda assim, preserve o PDF como artefato institucional do lote e mantenha esta versão da planilha como referência validada."}</p>
      `;
      cleanSection.classList.remove("hidden");
    }

    function resetResultWorkspace() {
      summarySection.classList.add("hidden");
      prioritySection.classList.add("hidden");
      actionsSection.classList.add("hidden");
      duplicatesSection.classList.add("hidden");
      navSection.classList.add("hidden");
      cleanSection.classList.add("hidden");
      problemsSection.classList.add("hidden");
      duplicatesSection.innerHTML = "";
      navSection.innerHTML = "";
      cleanSection.innerHTML = "";
      problemsSection.innerHTML = "";
    }

    function renderReportWorkspace(reportData, options = {}) {
      emptyState.classList.add("hidden");
      renderSummary(reportData.summary || {}, options);
      renderPriority(reportData, options);
      renderDuplicates(reportData.duplicates || [], options);
      renderCleanState(reportData.summary || {}, options);
      renderProblems(reportData.grouped_problems || {}, options);
    }

    function renderLiveJob(job) {
      renderProcessCard(job);

      if (job?.status === "failed") {
        resetResultWorkspace();
        renderStateBanner(
          "error",
          "Falha no processamento",
          job?.error_message || job?.status_detail || "O lote não conseguiu concluir a execução.",
        );
        setEmptyState(
          "O lote falhou antes da consolidação final",
          "Revise a mensagem de falha acima e reenfileire o arquivo somente depois de corrigir a causa raiz."
        );
        return;
      }

      const previewData = getPreviewReportData(job);
      if (previewData) {
        renderStateBanner(
          "warning",
          "Prévia em atualização",
          `Os dados abaixo refletem ${job.processed_rows || 0} de ${job.total_rows || 0} linhas já validadas. O PDF permanece reservado para o fechamento final do lote.`
        );
        renderReportWorkspace(
          {
            summary: previewData.summary,
            duplicates: previewData.duplicates,
            grouped_problems: previewData.grouped_problems,
            row_results: previewData.row_results,
          },
          { mode: "partial", processedRows: job.processed_rows }
        );
        return;
      }

      resetResultWorkspace();
      if (job?.status === "queued" || job?.status === "running") {
        renderStateBanner(
          "info",
          "Processamento em andamento sem prévia",
          "A prévia operacional será liberada assim que a indexação global terminar e o primeiro batch confiável for validado."
        );
        setEmptyState(
          "Prévia ainda indisponível",
          "O sistema está preparando o lote para liberar apenas informações parciais já confiáveis. Continue nesta tela para receber a atualização automática."
        );
        return;
      }

      hideStateBanner();
      setEmptyState(
        "O lote ainda não foi processado",
        "Depois do envio, o sistema mostra a identificação do arquivo, a etapa atual do processamento, o resumo executivo do lote e os blocos de correção agrupados por tipo de problema."
      );
    }

    function renderFinalJob(job, reportData) {
      renderProcessCard(job);
      renderStateBanner(
        "success",
        "Resultado final consolidado",
        "A execução foi concluída. O resumo operacional, os dados estruturados e o PDF institucional já estão disponíveis."
      );
      renderReportWorkspace(reportData, { mode: "final", processedRows: reportData.summary?.total_rows });
      downloadPdfLink.href = `/jobs/${job.job_id}/report`;
      downloadJsonLink.href = `/jobs/${job.job_id}/result`;
      actionsSection.classList.remove("hidden");
    }

    async function waitForJob(jobId) {
      while (true) {
        const response = await fetch(`/jobs/${jobId}`);
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Falha ao consultar o lote.");
        }

        if (payload.status === "failed") {
          renderLiveJob(payload);
          return payload;
        }

        if (payload.status === "completed") {
          return payload;
        }

        renderLiveJob(payload);

        await new Promise((resolve) => setTimeout(resolve, 1000));
      }
    }

    fileInput.addEventListener("change", () => {
      const selected = fileInput.files?.[0];
      workspaceContext.fileName = selected ? selected.name : null;
      fileName.textContent = selected ? selected.name : "Nenhum arquivo selecionado.";
    });

    tenantInput.addEventListener("change", () => {
      workspaceContext.organizationLabel = tenantInput.options[tenantInput.selectedIndex]?.text || "-";
      renderLiveJob();
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();

      if (!fileInput.files.length) {
        renderLiveJob({
          status: "failed",
          status_title: "Arquivo não informado",
          status_detail: "Selecione um CSV antes de iniciar o processamento do lote.",
          current_step: "file_received",
          file_name: workspaceContext.fileName,
        });
        return;
      }

      workspaceContext.organizationLabel = tenantInput.options[tenantInput.selectedIndex]?.text || "-";
      workspaceContext.fileName = fileInput.files[0].name;
      resetResultWorkspace();
      emptyState.classList.add("hidden");
      submitButton.disabled = true;
      submitButton.textContent = "Processando lote...";

      renderLiveJob({
        status: "queued",
        current_step: "file_received",
        status_title: "Arquivo recebido",
        status_detail: "O lote foi registrado e aguardará o início do processamento automático.",
        file_name: workspaceContext.fileName,
        updated_at: new Date().toISOString(),
      });

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);

      try {
        const uploadResponse = await fetch(`/validate?tenant_id=${encodeURIComponent(tenantInput.value)}`, {
          method: "POST",
          body: formData,
        });
        const uploadPayload = await uploadResponse.json();

        if (!uploadResponse.ok) {
          throw new Error(uploadPayload.detail || "Falha ao enviar o lote.");
        }

        renderLiveJob({
          job_id: uploadPayload.job_id,
          status: uploadPayload.status,
          current_step: "file_received",
          status_title: "Arquivo recebido",
          status_detail: "O lote foi registrado e entrará na etapa de leitura em seguida.",
          file_name: workspaceContext.fileName,
          updated_at: new Date().toISOString(),
        });

        const job = await waitForJob(uploadPayload.job_id);
        if (job.status !== "completed") {
          throw new Error(job.error_message || job.status_detail || "O lote terminou com falha.");
        }

        const resultResponse = await fetch(`/jobs/${uploadPayload.job_id}/result`);
        const reportData = await resultResponse.json();
        if (!resultResponse.ok) {
          throw new Error(reportData.detail || "Falha ao carregar o resultado estruturado do lote.");
        }

        renderFinalJob(job, reportData);
      } catch (error) {
        renderLiveJob({
          status: "failed",
          current_step: "failed",
          status_title: "Falha no processamento",
          status_detail: error.message || "Não foi possível concluir o lote.",
          file_name: workspaceContext.fileName,
          updated_at: new Date().toISOString(),
        });
      } finally {
        submitButton.disabled = false;
        submitButton.textContent = "Processar lote";
      }
    });

    renderLiveJob();
  </script>
</body>
</html>
"""

    return html.replace("__TENANT_OPTIONS__", tenant_options)
