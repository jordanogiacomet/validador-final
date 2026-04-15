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
    select,
    textarea {
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

    .scope-options {
      display: grid;
      gap: 10px;
    }

    .scope-option {
      display: grid;
      gap: 8px;
      padding: 14px;
      border: 1px solid var(--line);
      border-radius: 18px;
      background: rgba(255,255,255,0.92);
      cursor: pointer;
    }

    .scope-option-head {
      display: flex;
      align-items: center;
      gap: 10px;
    }

    .scope-option input {
      margin: 0;
      accent-color: var(--accent);
    }

    .scope-option strong {
      font-size: 0.95rem;
    }

    .scope-option span {
      padding-left: 28px;
      color: var(--muted);
      font-size: 0.88rem;
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

    .job-list {
      display: grid;
      gap: 12px;
      margin-top: 18px;
    }

    .job-item {
      display: grid;
      gap: 12px;
      padding: 16px;
      border-radius: 20px;
      background: rgba(255,255,255,0.82);
      border: 1px solid rgba(24, 33, 43, 0.08);
    }

    .job-item-head {
      display: flex;
      align-items: flex-start;
      justify-content: space-between;
      gap: 12px;
    }

    .job-item-head strong {
      display: block;
      font-size: 0.98rem;
      line-height: 1.35;
      word-break: break-word;
    }

    .job-item-head small {
      display: block;
      margin-top: 4px;
      color: var(--muted);
      line-height: 1.45;
    }

    .job-item-meta {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 0.86rem;
      line-height: 1.45;
    }

    .job-item-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
    }

    .job-item-actions .action-button {
      min-height: 38px;
      padding: 0 14px;
      font-size: 0.82rem;
    }

    .job-empty {
      margin: 0;
      padding: 16px;
      border-radius: 18px;
      background: rgba(255,255,255,0.78);
      border: 1px dashed rgba(24, 33, 43, 0.14);
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
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

    .export-actions {
      display: grid;
      gap: 14px;
      margin-top: 18px;
      padding-top: 18px;
      border-top: 1px solid rgba(24, 33, 43, 0.08);
    }

    .export-actions-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: 12px;
    }

    .export-card {
      display: grid;
      gap: 8px;
      padding: 16px;
      border-radius: 20px;
      border: 1px solid rgba(24, 33, 43, 0.08);
      background: rgba(255,255,255,0.82);
    }

    .export-card strong {
      font-size: 1rem;
      letter-spacing: -0.01em;
    }

    .export-card p {
      color: var(--muted);
      font-size: 0.92rem;
      line-height: 1.5;
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

    .duplicate-card-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 14px;
    }

    .duplicate-manage-button {
      min-height: 38px;
      padding: 0 14px;
      font-size: 0.82rem;
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

    .problem-pagination {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      margin-top: 14px;
      padding: 0 4px;
    }

    .problem-pagination p {
      color: var(--muted);
      font-size: 0.88rem;
      line-height: 1.5;
    }

    .problem-load-more {
      min-height: 38px;
      padding: 0 14px;
      font-size: 0.82rem;
      white-space: nowrap;
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

    .edit-action {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 32px;
      padding: 0 12px;
      border-radius: 999px;
      border: 1px solid rgba(24, 33, 43, 0.12);
      background: rgba(255, 255, 255, 0.9);
      color: var(--ink);
      font-size: 0.78rem;
      font-weight: 700;
      cursor: pointer;
      transition: transform 150ms ease, filter 150ms ease;
    }

    .edit-action:hover {
      filter: brightness(0.98);
      transform: translateY(-1px);
    }

    .edit-action:disabled {
      cursor: not-allowed;
      opacity: 0.6;
      transform: none;
    }

    .correction-card {
      padding: 22px;
      border: 1px solid rgba(21, 78, 74, 0.14);
      background:
        linear-gradient(140deg, rgba(255,255,255,0.88), rgba(255,255,255,0.76)),
        linear-gradient(135deg, rgba(21, 78, 74, 0.05), rgba(255,255,255,0));
    }

    .correction-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      margin-top: 16px;
    }

    .action-button {
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-height: 44px;
      padding: 0 16px;
      border-radius: 999px;
      border: 1px solid rgba(21, 78, 74, 0.18);
      background: rgba(255,255,255,0.9);
      color: var(--ink);
      font-weight: 700;
      cursor: pointer;
    }

    .action-button.primary {
      border-color: rgba(21, 78, 74, 0.28);
      background: linear-gradient(135deg, #154e4a 0%, #123f3c 100%);
      color: #fff;
      box-shadow: 0 18px 30px rgba(21, 78, 74, 0.16);
    }

    .action-button:disabled {
      cursor: not-allowed;
      opacity: 0.6;
      box-shadow: none;
    }

    .modal-shell {
      position: fixed;
      inset: 0;
      z-index: 50;
      display: grid;
      place-items: center;
      padding: 20px;
      background: rgba(24, 33, 43, 0.42);
      backdrop-filter: blur(6px);
    }

    .modal-card {
      width: min(760px, 100%);
      padding: 24px;
      border-radius: 28px;
      background:
        linear-gradient(145deg, rgba(255,255,255,0.96), rgba(255,255,255,0.9)),
        linear-gradient(135deg, rgba(21, 78, 74, 0.05), rgba(255,255,255,0));
      border: 1px solid rgba(255,255,255,0.8);
      box-shadow: 0 30px 80px rgba(24, 33, 43, 0.18);
    }

    .modal-grid {
      display: grid;
      gap: 14px;
      margin-top: 18px;
    }

    .modal-grid .field {
      gap: 6px;
    }

    .modal-grid input,
    .modal-grid textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 16px;
      padding: 13px 14px;
      background: rgba(255,255,255,0.94);
      color: var(--ink);
      resize: vertical;
    }

    .modal-grid input[readonly],
    .modal-grid textarea[readonly] {
      background: rgba(232, 241, 239, 0.66);
      color: var(--muted);
    }

    .modal-actions {
      display: flex;
      flex-wrap: wrap;
      gap: 10px;
      justify-content: flex-end;
      margin-top: 20px;
    }

    .duplicate-resolution-list {
      display: grid;
      gap: 12px;
      margin-top: 18px;
      max-height: min(420px, 58vh);
      overflow-y: auto;
      padding-right: 4px;
    }

    .duplicate-resolution-option {
      display: grid;
      gap: 12px;
      padding: 16px;
      border: 1px solid rgba(24, 33, 43, 0.12);
      border-radius: 20px;
      background: rgba(255,255,255,0.92);
    }

    .duplicate-resolution-option-head {
      display: flex;
      gap: 12px;
      align-items: flex-start;
    }

    .duplicate-resolution-option input {
      margin-top: 3px;
      accent-color: var(--accent);
    }

    .duplicate-resolution-title {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
      align-items: center;
    }

    .duplicate-resolution-title strong {
      font-size: 1rem;
    }

    .duplicate-resolution-badge {
      display: inline-flex;
      align-items: center;
      min-height: 28px;
      padding: 0 10px;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: 0.76rem;
      font-weight: 700;
      letter-spacing: 0.04em;
      text-transform: uppercase;
    }

    .duplicate-resolution-note {
      color: var(--muted);
      font-size: 0.9rem;
      line-height: 1.5;
    }

    .duplicate-resolution-meta {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px 14px;
      padding-left: 30px;
    }

    .duplicate-resolution-meta div {
      display: grid;
      gap: 4px;
    }

    .duplicate-resolution-meta small {
      color: var(--muted);
      font-size: 0.74rem;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }

    .duplicate-resolution-meta span {
      font-size: 0.92rem;
      line-height: 1.45;
      word-break: break-word;
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
      .jobs-card,
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
      .lot-card dl,
      .duplicate-resolution-meta {
        grid-template-columns: 1fr;
      }

      .duplicate-resolution-meta {
        padding-left: 0;
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
          Você pode processar apenas itens cadastrados do zero ou todo o lote; o resumo, os agrupamentos e o PDF sempre acompanham o escopo escolhido no envio.
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
            Selecione a organização correta, defina o escopo da análise, anexe a planilha CSV e acompanhe o lote até a publicação do resumo e do PDF.
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

            <div class="field">
              <label>Escopo da análise</label>
              <div class="scope-options">
                <label class="scope-option" for="validation-scope-zero">
                  <div class="scope-option-head">
                    <input id="validation-scope-zero" name="validation_scope" type="radio" value="zero_items" checked />
                    <strong>Apenas itens cadastrados do zero</strong>
                  </div>
                  <span>Preserva o fluxo operacional atual e mantém linhas coletadas fora do resumo, dos agrupamentos e do PDF.</span>
                </label>
                <label class="scope-option" for="validation-scope-all">
                  <div class="scope-option-head">
                    <input id="validation-scope-all" name="validation_scope" type="radio" value="all_items" />
                    <strong>Todos os itens</strong>
                  </div>
                  <span>Inclui também linhas coletadas no resultado estruturado, nos agrupamentos e no relatório final.</span>
                </label>
              </div>
              <small>Essa escolha vale para o processamento atual e é preservada no reprocessamento do mesmo lote.</small>
            </div>

            <button id="submit-button" class="cta" type="submit">Processar lote</button>
          </form>

          <div class="support-list">
            <div class="support-item">
              <strong>O que esta tela entrega</strong>
              <span>Resumo executivo, trilha de processamento, blocos de correção priorizados e acesso aos artefatos finais conforme o escopo escolhido no envio.</span>
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

        <section id="jobs-card" class="panel control-card jobs-card">
          <div class="panel-kicker">Jobs do servidor</div>
          <h2 class="panel-title">Processamentos em andamento</h2>
          <p class="panel-copy">
            Esta fila mostra os jobs ativos desta instância. Você pode interromper um lote em andamento sem sair da tela operacional.
          </p>
          <div id="jobs-list" class="job-list">
            <p class="job-empty">Nenhum job em processamento no momento.</p>
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
          <p class="panel-copy">Use o PDF para distribuição institucional, o arquivo estruturado para auditoria completa e os recortes CSV quando precisar tratar um grupo operacional específico.</p>
          <div class="actions">
            <a id="download-pdf" class="action-link" href="#" target="_blank" rel="noopener noreferrer">Baixar relatório PDF</a>
            <a id="download-json" class="action-link" href="#" target="_blank" rel="noopener noreferrer">Baixar dados estruturados</a>
          </div>
          <div id="operational-exports" class="export-actions hidden"></div>
        </section>

        <section id="correction-section" class="panel correction-card hidden">
          <div class="panel-kicker">Correções aplicadas</div>
          <h2 class="panel-title">O CSV foi ajustado diretamente nesta sessão</h2>
          <p class="panel-copy">Baixe a planilha corrigida no mesmo formato do arquivo de entrada ou inicie um novo processamento para refletir as mudanças no resumo consolidado e no PDF final.</p>
          <div class="correction-actions">
            <a id="download-corrected-csv" class="action-link" href="#">Baixar CSV corrigido</a>
            <button id="reprocess-button" class="action-button primary" type="button">Reprocessar lote</button>
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

  <div id="edit-modal" class="modal-shell hidden">
    <div class="modal-card">
      <div class="panel-kicker">Correção direta no CSV</div>
      <h2 id="edit-modal-title" class="panel-title">Editar campo do lote</h2>
      <p id="edit-modal-detail" class="panel-copy">O valor atual será carregado diretamente do CSV do job antes do salvamento.</p>

      <div class="modal-grid">
        <div class="field">
          <label for="edit-field-display">Campo operacional</label>
          <input id="edit-field-display" type="text" readonly />
        </div>
        <div class="field">
          <label for="edit-source-column-display">Coluna no CSV</label>
          <input id="edit-source-column-display" type="text" readonly />
        </div>
        <div class="field">
          <label for="edit-current-value">Valor atual no arquivo</label>
          <textarea id="edit-current-value" rows="3" readonly></textarea>
        </div>
        <div class="field">
          <label for="edit-new-value">Novo valor</label>
          <textarea id="edit-new-value" rows="4"></textarea>
        </div>
      </div>

      <div class="modal-actions">
        <button id="edit-cancel-button" class="action-button" type="button">Cancelar</button>
        <button id="edit-save-button" class="action-button primary" type="button">Salvar no CSV</button>
      </div>
    </div>
  </div>

  <div id="duplicate-modal" class="modal-shell hidden">
    <div class="modal-card">
      <div class="panel-kicker">Resolução de duplicidade</div>
      <h2 id="duplicate-modal-title" class="panel-title">Escolher linha para manter</h2>
      <p id="duplicate-modal-detail" class="panel-copy">Selecione a ocorrência que deve permanecer no CSV. As demais linhas com o mesmo Item serão removidas do arquivo corrigido.</p>

      <div id="duplicate-modal-options" class="duplicate-resolution-list"></div>

      <div class="modal-actions">
        <button id="duplicate-cancel-button" class="action-button" type="button">Cancelar</button>
        <button id="duplicate-save-button" class="action-button primary" type="button">Excluir duplicados no CSV</button>
      </div>
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

    const CATEGORY_CHECK_LABELS = {
      btu_pattern: "capacidade em BTU",
      inches_pattern: "polegadas",
      ports_pattern: "quantidade de portas",
      channels_pattern: "quantidade de canais",
      liters_pattern: "capacidade em litros",
    };

    const INITIAL_PROBLEM_OCCURRENCES = 20;
    const PROBLEM_OCCURRENCES_STEP = 20;

    const form = document.getElementById("validation-form");
    const fileInput = document.getElementById("file");
    const fileName = document.getElementById("file-name");
    const tenantInput = document.getElementById("tenant");
    const jobsList = document.getElementById("jobs-list");
    const validationScopeInputs = Array.from(
      document.querySelectorAll('input[name="validation_scope"]')
    );
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
    const operationalExports = document.getElementById("operational-exports");
    const duplicatesSection = document.getElementById("duplicates-section");
    const navSection = document.getElementById("nav-section");
    const cleanSection = document.getElementById("clean-section");
    const problemsSection = document.getElementById("problems-section");
    const emptyState = document.getElementById("empty-state");
    const downloadPdfLink = document.getElementById("download-pdf");
    const downloadJsonLink = document.getElementById("download-json");
    const downloadCorrectedCsvLink = document.getElementById("download-corrected-csv");
    const correctionSection = document.getElementById("correction-section");
    const reprocessButton = document.getElementById("reprocess-button");
    const editModal = document.getElementById("edit-modal");
    const editModalTitle = document.getElementById("edit-modal-title");
    const editModalDetail = document.getElementById("edit-modal-detail");
    const editFieldDisplay = document.getElementById("edit-field-display");
    const editSourceColumnDisplay = document.getElementById("edit-source-column-display");
    const editCurrentValue = document.getElementById("edit-current-value");
    const editNewValue = document.getElementById("edit-new-value");
    const editCancelButton = document.getElementById("edit-cancel-button");
    const editSaveButton = document.getElementById("edit-save-button");
    const duplicateModal = document.getElementById("duplicate-modal");
    const duplicateModalTitle = document.getElementById("duplicate-modal-title");
    const duplicateModalDetail = document.getElementById("duplicate-modal-detail");
    const duplicateModalOptions = document.getElementById("duplicate-modal-options");
    const duplicateCancelButton = document.getElementById("duplicate-cancel-button");
    const duplicateSaveButton = document.getElementById("duplicate-save-button");
    let currentJobId = null;
    let hasPendingCorrections = false;
    let activeEditContext = null;
    let activeDuplicateContext = null;
    let visibleProblemOccurrencesByCode = {};
    let jobsRefreshInFlight = false;

    const workspaceContext = {
      organizationLabel: tenantInput.options[tenantInput.selectedIndex]?.text || "-",
      fileName: null,
      validationScope: "zero_items",
    };

    function normalizeValidationScope(value) {
      return value === "all_items" ? "all_items" : "zero_items";
    }

    function getSelectedValidationScope() {
      return normalizeValidationScope(
        validationScopeInputs.find((input) => input.checked)?.value
      );
    }

    function isAllItemsScope(scope = workspaceContext.validationScope) {
      return normalizeValidationScope(scope) === "all_items";
    }

    function getValidationScopeLabel(scope = workspaceContext.validationScope) {
      return isAllItemsScope(scope)
        ? "Todos os itens"
        : "Itens cadastrados do zero";
    }

    function buildFinalScopeCopy(scope = workspaceContext.validationScope) {
      if (isAllItemsScope(scope)) {
        return "A execução foi concluída. O resumo operacional considera todos os itens do lote, e os dados estruturados e o PDF institucional já estão disponíveis.";
      }

      return "A execução foi concluída. O resumo operacional considera apenas itens cadastrados do zero, e os dados estruturados e o PDF institucional já estão disponíveis.";
    }

    workspaceContext.validationScope = getSelectedValidationScope();

    function resolveEditableField(occurrence) {
      if (!occurrence?.field) {
        return null;
      }

      if (
        occurrence.field === "flag_item_coletado"
        || occurrence.field === "flag_item_cadastrado_do_zero"
      ) {
        return "placa_anterior";
      }

      return occurrence.field;
    }

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

    function getValidatedTotalRows(summary = {}) {
      return Number(summary.validated_rows ?? summary.total_rows ?? 0);
    }

    function getSourceTotalRows(summary = {}) {
      return Number(summary.source_total_rows ?? getValidatedTotalRows(summary));
    }

    function buildScopeSummaryCopy(summary = {}) {
      const validatedRows = getValidatedTotalRows(summary);
      const sourceTotalRows = getSourceTotalRows(summary);

      if (sourceTotalRows !== validatedRows) {
        return `Somente itens cadastrados do zero entram na análise operacional. Arquivo com ${sourceTotalRows} linhas.`;
      }

      return "Todas as linhas lidas entraram no escopo validado deste lote.";
    }

    function formatFieldName(field) {
      if (!field) {
        return "Revisão geral";
      }
      return FIELD_LABELS[field] || field;
    }

    function humanizeCategoryToken(categoryToken) {
      return String(categoryToken || "").replaceAll("_", " ").trim().toUpperCase();
    }

    function parseCategoryRequiredCode(code) {
      if (!code?.startsWith("CATEGORY_") || !code.endsWith("_REQUIRED")) {
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

    function parseCategoryCriticalCode(code) {
      if (!code?.startsWith("CATEGORY_") || !code.endsWith("_MISSING")) {
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
      if (job?.cancel_requested) {
        return { label: "Cancelando", kind: "warning" };
      }
      const status = job?.status;
      if (status === "queued") {
        return { label: "Recebido", kind: "info" };
      }
      if (status === "canceled") {
        return { label: "Cancelado", kind: "warning" };
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

    function describeJobScope(job) {
      return getValidationScopeLabel(job?.validation_scope || workspaceContext.validationScope);
    }

    function describeJobProgress(job) {
      if (job?.cancel_requested) {
        return job.status_detail || "O sistema está interrompendo este processamento.";
      }
      if (job?.status === "queued") {
        return "Aguardando início do processamento automático.";
      }
      if (job?.status === "running") {
        const processed = Number(job?.processed_rows || 0);
        const total = Number(job?.total_rows || 0);
        if (total > 0) {
          return `${processed} de ${total} item(ns) em escopo já passaram pela etapa atual.`;
        }
        return job?.status_detail || "O lote está em processamento.";
      }
      if (job?.status === "canceled") {
        return job?.status_detail || "O lote foi interrompido antes da consolidação final.";
      }
      return job?.status_detail || "Sem detalhes adicionais.";
    }

    async function fetchJobs() {
      const response = await fetch("/jobs?active_only=true");
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao listar os jobs ativos.");
      }
      return payload;
    }

    function renderJobsPanel(jobs = []) {
      if (!jobs.length) {
        jobsList.innerHTML = '<p class="job-empty">Nenhum job em processamento no momento.</p>';
        return;
      }

      jobsList.innerHTML = jobs.map((job) => {
        const chip = formatStatusChip(job);
        const canCancel = (job.status === "queued" || job.status === "running") && !job.cancel_requested;
        return `
          <article class="job-item">
            <div class="job-item-head">
              <div>
                <strong>${escapeHtml(job.file_name || "Arquivo não identificado")}</strong>
                <small>${escapeHtml(job.tenant_id)} • ${escapeHtml(describeJobScope(job))}</small>
              </div>
              <span class="status-chip ${chip.kind}">${escapeHtml(chip.label)}</span>
            </div>
            <div class="job-item-meta">
              <span><b>Job:</b> ${escapeHtml(job.job_id)}</span>
              <span><b>Atualizado:</b> ${escapeHtml(formatDateTime(job.updated_at))}</span>
              <span><b>Etapa:</b> ${escapeHtml(job.status_title || "Processamento em andamento")}</span>
              <span>${escapeHtml(describeJobProgress(job))}</span>
            </div>
            <div class="job-item-actions">
              <button
                class="action-button job-open-button"
                type="button"
                data-job-open="${escapeHtml(job.job_id)}"
              >
                Acompanhar
              </button>
              <button
                class="action-button ${canCancel ? "" : "primary"} job-cancel-button"
                type="button"
                data-job-cancel="${escapeHtml(job.job_id)}"
                ${canCancel ? "" : "disabled"}
              >
                ${job.cancel_requested ? "Cancelando..." : "Cancelar job"}
              </button>
            </div>
          </article>
        `;
      }).join("");

      jobsList.querySelectorAll(".job-open-button").forEach((button) => {
        button.addEventListener("click", () => {
          const jobId = button.getAttribute("data-job-open");
          if (!jobId) {
            return;
          }

          openJob(jobId).catch((error) => {
            renderStateBanner(
              "error",
              "Falha ao abrir o job",
              error.message || "Não foi possível carregar o job selecionado."
            );
          });
        });
      });

      jobsList.querySelectorAll(".job-cancel-button").forEach((button) => {
        button.addEventListener("click", () => {
          const jobId = button.getAttribute("data-job-cancel");
          if (!jobId || button.disabled) {
            return;
          }

          cancelJob(jobId).catch((error) => {
            renderStateBanner(
              "error",
              "Falha ao cancelar o job",
              error.message || "Não foi possível interromper o job selecionado."
            );
          });
        });
      });
    }

    async function refreshJobsPanel() {
      if (jobsRefreshInFlight) {
        return;
      }

      jobsRefreshInFlight = true;
      try {
        const jobs = await fetchJobs();
        renderJobsPanel(jobs);
      } finally {
        jobsRefreshInFlight = false;
      }
    }

    function syncCorrectedCsvDownload(jobId = currentJobId) {
      downloadCorrectedCsvLink.href = jobId ? `/jobs/${jobId}/csv` : "#";
    }

    function buildOperationalExportUrl(kind, problemCode = null) {
      if (!currentJobId) {
        return "#";
      }

      const params = new URLSearchParams({ kind });
      if (problemCode) {
        params.set("problem_code", problemCode);
      }
      return `/jobs/${currentJobId}/exports/csv?${params.toString()}`;
    }

    function renderOperationalExports(reportData) {
      const duplicates = reportData?.duplicates || [];
      const groupedProblems = reportData?.grouped_problems || {};
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

      const cards = [];
      if (duplicates.length) {
        cards.push(`
          <article class="export-card">
            <small>Duplicidades</small>
            <strong>CSV apenas com itens duplicados</strong>
            <p>${escapeHtml(duplicates.length)} agrupamento(s) com Item repetido dentro do escopo validado.</p>
            <a class="action-link" href="${escapeHtml(buildOperationalExportUrl("duplicates"))}">Baixar duplicados em CSV</a>
          </article>
        `);
      }

      groups.forEach(({ code, occurrences }) => {
        const guide = describeIssue(code);
        cards.push(`
          <article class="export-card">
            <small>${escapeHtml(code)}</small>
            <strong>${escapeHtml(guide.title)}</strong>
            <p>${escapeHtml(occurrences.length)} ocorrência(s) deste grupo em formato operacional para tratamento em lote.</p>
            <a class="action-link" href="${escapeHtml(buildOperationalExportUrl("problem_group", code))}">Baixar este grupo em CSV</a>
          </article>
        `);
      });

      if (!cards.length) {
        operationalExports.classList.add("hidden");
        operationalExports.innerHTML = "";
        return;
      }

      operationalExports.innerHTML = `
        <div>
          <div class="panel-kicker">Exportações operacionais</div>
          <p class="panel-copy">Cada link abaixo gera um CSV focado em um recorte de tratamento, como duplicidades ou um tipo específico de apontamento.</p>
        </div>
        <div class="export-actions-grid">
          ${cards.join("")}
        </div>
      `;
      operationalExports.classList.remove("hidden");
    }

    function resetProblemVisibilityState() {
      visibleProblemOccurrencesByCode = {};
    }

    function getVisibleProblemOccurrences(code) {
      return visibleProblemOccurrencesByCode[code] || INITIAL_PROBLEM_OCCURRENCES;
    }

    function showMoreProblemOccurrences(code) {
      visibleProblemOccurrencesByCode[code] =
        getVisibleProblemOccurrences(code) + PROBLEM_OCCURRENCES_STEP;
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

    function updateCorrectionSection() {
      if (hasPendingCorrections) {
        correctionSection.classList.remove("hidden");
        return;
      }

      correctionSection.classList.add("hidden");
    }

    function markCorrectionsPending() {
      hasPendingCorrections = true;
      updateCorrectionSection();
    }

    function clearCorrectionsPending() {
      hasPendingCorrections = false;
      updateCorrectionSection();
    }

    function closeEditModal() {
      activeEditContext = null;
      editModal.classList.add("hidden");
      editFieldDisplay.value = "";
      editSourceColumnDisplay.value = "";
      editCurrentValue.value = "";
      editNewValue.value = "";
      editSaveButton.disabled = false;
      editSaveButton.textContent = "Salvar no CSV";
    }

    function closeDuplicateModal() {
      activeDuplicateContext = null;
      duplicateModal.classList.add("hidden");
      duplicateModalOptions.innerHTML = "";
      duplicateSaveButton.disabled = false;
      duplicateSaveButton.textContent = "Excluir duplicados no CSV";
    }

    async function fetchJobRow(jobId, rowIndex) {
      const response = await fetch(`/jobs/${jobId}/rows/${rowIndex}`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao carregar a linha do CSV.");
      }
      return payload;
    }

    function getCanonicalFieldValue(rowPayload, field) {
      const sourceColumn = rowPayload?.resolved_columns?.[field] || field;
      return rowPayload?.row?.[sourceColumn] || "";
    }

    async function openEditModal(rowIndex, field, itemLabel) {
      if (!currentJobId) {
        throw new Error("Nenhum job ativo foi identificado para abrir a correção.");
      }

      const rowPayload = await fetchJobRow(currentJobId, rowIndex);
      const sourceColumn = rowPayload.resolved_columns?.[field] || field;
      const currentValue = rowPayload.row?.[sourceColumn] || "";

      activeEditContext = {
        rowIndex,
        field,
        sourceColumn,
      };

      editModalTitle.textContent = `Editar ${formatFieldName(field)} na linha ${lineNumber(rowIndex)}`;
      editModalDetail.textContent = itemLabel
        ? `O valor atual foi carregado do CSV do lote para o item ${itemLabel}.`
        : "O valor atual foi carregado diretamente do CSV do lote.";
      editFieldDisplay.value = formatFieldName(field);
      editSourceColumnDisplay.value = sourceColumn;
      editCurrentValue.value = currentValue;
      editNewValue.value = currentValue;
      editModal.classList.remove("hidden");
      editNewValue.focus();
      editNewValue.setSelectionRange(editNewValue.value.length, editNewValue.value.length);
    }

    async function openDuplicateModal(duplicate) {
      if (!currentJobId) {
        throw new Error("Nenhum job ativo foi identificado para resolver a duplicidade.");
      }

      const rowIndices = (duplicate?.row_indices || [])
        .map((value) => Number(value))
        .filter((value) => Number.isInteger(value) && value >= 0)
        .sort((left, right) => left - right);

      if (rowIndices.length < 2) {
        throw new Error("Esta duplicidade não possui linhas suficientes para resolução.");
      }

      const suggestedKeepRowIndex = rowIndices[rowIndices.length - 1];
      const rows = await Promise.all(
        rowIndices.map(async (rowIndex) => ({
          rowIndex,
          rowPayload: await fetchJobRow(currentJobId, rowIndex),
        }))
      );

      activeDuplicateContext = {
        duplicate,
        rows,
        suggestedKeepRowIndex,
      };

      duplicateModalTitle.textContent = `Escolher linha para manter do item ${duplicate.item || "sem identificação"}`;
      duplicateModalDetail.textContent = "Selecione a ocorrência que deve permanecer no CSV. Como o sistema ainda não registra alteração por linha, a última ocorrência no arquivo aparece destacada como referência prática.";
      duplicateModalOptions.innerHTML = rows.map(({ rowIndex, rowPayload }) => {
        const descricao = getCanonicalFieldValue(rowPayload, "descricao") || "Não informado";
        const placa = getCanonicalFieldValue(rowPayload, "placa_anterior") || "Sem placa anterior";
        const marca = getCanonicalFieldValue(rowPayload, "marca") || "Não informado";
        const modelo = getCanonicalFieldValue(rowPayload, "modelo") || "Não informado";
        const ns = getCanonicalFieldValue(rowPayload, "ns") || "Não informado";
        const complemento = getCanonicalFieldValue(rowPayload, "complemento") || "Não informado";
        const isSuggested = rowIndex === suggestedKeepRowIndex;

        return `
          <label class="duplicate-resolution-option" for="duplicate-keep-${rowIndex}">
            <div class="duplicate-resolution-option-head">
              <input
                id="duplicate-keep-${rowIndex}"
                name="duplicate_keep_row"
                type="radio"
                value="${rowIndex}"
                ${isSuggested ? "checked" : ""}
              />
              <div>
                <div class="duplicate-resolution-title">
                  <strong>Linha ${lineNumber(rowIndex)}</strong>
                  ${isSuggested ? '<span class="duplicate-resolution-badge">Última ocorrência no CSV</span>' : ""}
                </div>
                <div class="duplicate-resolution-note">
                  Item ${escapeHtml(duplicate.item || "-")} | ${escapeHtml(descricao)}
                </div>
              </div>
            </div>
            <div class="duplicate-resolution-meta">
              <div>
                <small>Placa Anterior</small>
                <span>${escapeHtml(placa)}</span>
              </div>
              <div>
                <small>Marca</small>
                <span>${escapeHtml(marca)}</span>
              </div>
              <div>
                <small>Modelo</small>
                <span>${escapeHtml(modelo)}</span>
              </div>
              <div>
                <small>NS</small>
                <span>${escapeHtml(ns)}</span>
              </div>
              <div style="grid-column: 1 / -1;">
                <small>Complemento</small>
                <span>${escapeHtml(complemento)}</span>
              </div>
            </div>
          </label>
        `;
      }).join("");

      duplicateModal.classList.remove("hidden");
    }

    async function saveEditModal() {
      if (!activeEditContext || !currentJobId) {
        return;
      }

      editSaveButton.disabled = true;
      editSaveButton.textContent = "Salvando...";

      try {
        const response = await fetch(
          `/jobs/${currentJobId}/rows/${activeEditContext.rowIndex}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              updates: { [activeEditContext.field]: editNewValue.value },
            }),
          }
        );
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Falha ao atualizar o CSV.");
        }

        markCorrectionsPending();
        closeEditModal();
        renderStateBanner(
          "success",
          "Correção registrada",
          "O CSV de entrada foi atualizado com o novo valor. Quando terminar as edições, reprocesse o lote para consolidar o resultado."
        );
      } catch (error) {
        editSaveButton.disabled = false;
        editSaveButton.textContent = "Salvar no CSV";
        renderStateBanner(
          "error",
          "Falha ao corrigir",
          error.message || "Não foi possível atualizar o CSV."
        );
      }
    }

    async function saveDuplicateModal() {
      if (!activeDuplicateContext || !currentJobId) {
        return;
      }

      const selectedKeepInput = duplicateModal.querySelector('input[name="duplicate_keep_row"]:checked');
      if (!selectedKeepInput) {
        renderStateBanner(
          "warning",
          "Seleção pendente",
          "Escolha a linha que deve permanecer no CSV antes de excluir as demais ocorrências."
        );
        return;
      }

      duplicateSaveButton.disabled = true;
      duplicateSaveButton.textContent = "Atualizando lote...";

      try {
        const keepRowIndex = Number(selectedKeepInput.value);
        const response = await fetch(
          `/jobs/${currentJobId}/duplicates/resolve`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              row_indices: activeDuplicateContext.rows.map((entry) => entry.rowIndex),
              keep_row_index: keepRowIndex,
            }),
          }
        );
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Falha ao excluir as linhas duplicadas do CSV.");
        }

        closeDuplicateModal();
        clearCorrectionsPending();
        resetResultWorkspace();
        emptyState.classList.add("hidden");
        await finalizeJob(currentJobId);
        renderStateBanner(
          "success",
          "Lote atualizado no mesmo processamento",
          `A linha ${lineNumber(payload.kept_row_index)} foi mantida e as demais ocorrências duplicadas foram excluídas do arquivo corrigido. Resumo, agrupamentos, JSON e PDF já refletem esta exclusão no mesmo job.`
        );
      } catch (error) {
        duplicateSaveButton.disabled = false;
        duplicateSaveButton.textContent = "Excluir duplicados no CSV";
        renderStateBanner(
          "error",
          "Falha ao excluir duplicados",
          error.message || "Não foi possível atualizar o CSV."
        );
      }
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
        return {
          title: `${categoryCritical.categoryLabel}: informar ${categoryCritical.requirementLabel}`,
          context: `Itens da espécie ${categoryCritical.categoryLabel} precisam trazer ${categoryCritical.requirementLabel} em Descrição, Complemento ou Modelo.`,
          impact: "Sem esse detalhe técnico, a identificação do bem fica incompleta e a conciliação patrimonial exige verificação manual adicional.",
          action: `Inclua ${categoryCritical.requirementLabel} em Descrição, Complemento ou Modelo, conforme o padrão de cadastro usado para essa espécie.`,
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
      const validationScopeLabel = getValidationScopeLabel(
        job?.validation_scope || workspaceContext.validationScope
      );

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
        <div>
          <dt>Escopo</dt>
          <dd>${escapeHtml(validationScopeLabel)}</dd>
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
      const validatedRows = getValidatedTotalRows(summary);
      const processedRows = Number(options.processedRows ?? summary.processed_rows ?? validatedRows);
      const cleanRows = Math.max(
        (isPartial ? processedRows : validatedRows) - Number(summary.rows_with_issues ?? 0),
        0,
      );

      const cards = isPartial
        ? [
            {
              label: "Itens em escopo",
              value: validatedRows,
              copy: buildScopeSummaryCopy(summary),
              className: "",
            },
            {
              label: "Itens já validados",
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
              label: "Itens em escopo",
              value: validatedRows,
              copy: buildScopeSummaryCopy(summary),
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
      const validationScope = workspaceContext.validationScope;
      const isZeroItemsOnly = !isAllItemsScope(validationScope);
      const duplicateCount = (duplicates || []).length;
      const processedRows = Number(options.processedRows ?? summary.processed_rows ?? getValidatedTotalRows(summary));
      const validatedRows = getValidatedTotalRows(summary);
      const sourceTotalRows = getSourceTotalRows(summary);
      let headline = "Nenhuma pendência crítica identificada.";
      let copy = "O lote pode seguir para conferência final ou arquivamento, sem necessidade de nova rodada de correção.";
      let checklist = [
        "Registrar o PDF como artefato formal do lote.",
        "Manter a versão validada da planilha como referência operacional.",
      ];

      if (isPartial) {
        headline = "Prévia operacional em atualização.";
        copy = `Os indicadores abaixo refletem ${processedRows} de ${validatedRows} itens em escopo já validados com contexto completo. ${sourceTotalRows !== validatedRows ? `O CSV original tem ${sourceTotalRows} linhas. ` : ""}O PDF será liberado apenas após a consolidação final.`;
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
      } else if (isZeroItemsOnly && validatedRows === 0 && sourceTotalRows > 0) {
        headline = "Nenhum item cadastrado do zero entrou no escopo operacional.";
        copy = `O arquivo original tem ${sourceTotalRows} linhas, mas o resultado validado considera apenas itens com flag_item_cadastrado_do_zero = 1.`;
        checklist = [
          "Usar este processamento como registro de que não houve itens em escopo para consolidar.",
          "Só reenviar a planilha se houver ajuste que mude o enquadramento dos itens ou outros dados do CSV.",
        ];
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
            <strong>${escapeHtml(isPartial ? `${processedRows}/${validatedRows}` : summary.error_count)}</strong>
            <span>${isPartial ? "Itens em escopo já validados com contexto global dentro da execução atual." : summary.error_count > 0 ? "Existem erros que devem ser resolvidos antes do próximo lote." : isZeroItemsOnly && validatedRows === 0 && sourceTotalRows > 0 ? "Nenhum item cadastrado do zero entrou no escopo operacional." : "Não há erros críticos abertos neste processamento."}</span>
          </div>
          <div class="metric-tile">
            <small>Duplicidades</small>
            <strong>${escapeHtml(duplicateCount)}</strong>
            <span>${duplicateCount > 0 ? "Itens repetidos exigem decisão patrimonial antes do reenvio." : isPartial ? "Nenhuma duplicidade confiável foi identificada dentro do escopo validado." : "Nenhum item duplicado foi encontrado dentro do escopo validado."}</span>
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
      const isZeroItemsOnly = !isAllItemsScope(workspaceContext.validationScope);
      const canResolveDuplicates = !isPartial;
      if (!duplicates.length) {
        duplicatesSection.classList.add("hidden");
        duplicatesSection.innerHTML = "";
        return;
      }

      duplicatesSection.innerHTML = `
        <div class="panel-kicker">Consistência cadastral</div>
        <h2 class="panel-title">Itens com identificador repetido no escopo validado</h2>
        <p class="panel-copy">${isPartial && isZeroItemsOnly ? "Esta seção já é confiável durante a execução porque depende da indexação global do lote inteiro, mas consolida apenas os itens cadastrados do zero. Revise este grupo antes de trabalhar detalhes complementares do cadastro." : isPartial ? "Esta seção já é confiável durante a execução porque depende da indexação global do lote inteiro e já reflete as duplicidades do escopo escolhido. Revise este grupo antes de trabalhar detalhes complementares do cadastro." : "Cada item patrimonial em escopo deve aparecer uma única vez. Revise este grupo antes de trabalhar detalhes complementares do cadastro."}</p>
        <div class="duplicates-grid">
          ${duplicates.map((duplicate, duplicateIndex) => `
            <article class="duplicate-card">
              <strong>${escapeHtml(duplicate.item)}</strong>
              <p><b>Nome do bem:</b> ${escapeHtml(duplicate.descricao || "Não informado")}</p>
              <p><b>Ocorrências:</b> ${escapeHtml(duplicate.count)}</p>
              <p><b>Linhas envolvidas:</b> ${duplicate.row_indices.map((rowIndex) => lineNumber(rowIndex)).join(", ")}</p>
              <div class="duplicate-card-actions">
                <button
                  class="action-button duplicate-manage-button duplicate-resolve-action"
                  type="button"
                  data-duplicate-index="${duplicateIndex}"
                  ${canResolveDuplicates ? "" : "disabled"}
                >
                  ${canResolveDuplicates ? "Escolher linha para manter" : "Disponível após conclusão"}
                </button>
              </div>
            </article>
          `).join("")}
        </div>
      `;
      duplicatesSection.classList.remove("hidden");
      duplicatesSection.querySelectorAll(".duplicate-resolve-action").forEach((button) => {
        button.addEventListener("click", async () => {
          const duplicateIndex = Number(button.getAttribute("data-duplicate-index"));
          try {
            await openDuplicateModal(duplicates[duplicateIndex]);
          } catch (error) {
            renderStateBanner(
              "error",
              "Falha ao abrir a resolução",
              error.message || "Não foi possível carregar as linhas duplicadas no CSV."
            );
          }
        });
      });
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
        const visibleCount = Math.min(
          occurrences.length,
          getVisibleProblemOccurrences(code)
        );
        const visibleOccurrences = [...occurrences]
          .sort((left, right) => left.row_index - right.row_index)
          .slice(0, visibleCount);
        const rows = visibleOccurrences
          .map((occurrence) => {
            const editableField = resolveEditableField(occurrence);
            return `
              <tr>
                <td>${lineNumber(occurrence.row_index)}</td>
                <td>${escapeHtml(occurrence.item || "Não informado")}</td>
                <td>${escapeHtml(occurrence.descricao || "Não informado")}</td>
                <td><span class="field-pill">${escapeHtml(formatFieldName(editableField || occurrence.field))}</span></td>
                <td>${escapeHtml(occurrence.message)}</td>
                <td>
                  <button
                    class="edit-action"
                    data-row-index="${escapeHtml(occurrence.row_index)}"
                    data-field="${escapeHtml(editableField || "")}"
                    data-item="${escapeHtml(occurrence.item || "")}"
                    ${editableField ? "" : "disabled"}
                  >
                    Corrigir
                  </button>
                </td>
              </tr>
            `;
          })
          .join("");

        return `
          <article id="problem-${slugify(code)}" class="panel problem-card">
            <div class="problem-header">
              <div>
                <span class="problem-kicker">${severity === "error" ? "Prioridade alta" : "Qualidade e complemento"}</span>
                <h3 class="problem-title">${escapeHtml(guide.title)}</h3>
                <p class="problem-meta">${escapeHtml(occurrences.length)} ocorrência(s) ${isPartial ? "na prévia atual do escopo validado" : "no escopo validado"}</p>
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
                    <th>Ação</th>
                  </tr>
                </thead>
                <tbody>${rows}</tbody>
              </table>
            </div>
            ${visibleCount < occurrences.length ? `
              <div class="problem-pagination">
                <p>Mostrando ${escapeHtml(visibleCount)} de ${escapeHtml(occurrences.length)} ocorrência(s) deste grupo para manter a tela responsiva.</p>
                <button
                  class="action-button problem-load-more"
                  type="button"
                  data-problem-code="${escapeHtml(code)}"
                >
                  Carregar mais
                </button>
              </div>
            ` : ""}
          </article>
        `;
      }).join("");
      problemsSection.classList.remove("hidden");

      problemsSection.querySelectorAll(".edit-action").forEach((button) => {
        button.addEventListener("click", () => handleEditClick(button));
      });
      problemsSection.querySelectorAll(".problem-load-more").forEach((button) => {
        button.addEventListener("click", () => {
          const code = button.getAttribute("data-problem-code");
          if (!code) {
            return;
          }

          showMoreProblemOccurrences(code);
          renderProblems(groupedProblems, options);
        });
      });
    }

    function renderCleanState(summary, options = {}) {
      const isPartial = options.mode === "partial";
      const processedRows = Number(options.processedRows ?? summary.processed_rows ?? getValidatedTotalRows(summary));
      const validatedRows = getValidatedTotalRows(summary);
      const sourceTotalRows = getSourceTotalRows(summary);
      const isZeroItemsOnly = !isAllItemsScope(workspaceContext.validationScope);

      if (summary.rows_with_issues > 0) {
        cleanSection.classList.add("hidden");
        cleanSection.innerHTML = "";
        return;
      }

      const title = !isPartial && isZeroItemsOnly && validatedRows === 0 && sourceTotalRows > 0
        ? "Nenhum item cadastrado do zero entrou no escopo deste processamento"
        : isPartial
          ? "Nenhuma pendência foi confirmada na prévia atual"
          : "Nenhuma correção foi exigida neste processamento";
      const detail = !isPartial && isZeroItemsOnly && validatedRows === 0 && sourceTotalRows > 0
        ? `O CSV original tem ${sourceTotalRows} linhas, mas nenhuma delas entrou no escopo operacional porque a análise considera apenas itens cadastrados do zero.`
        : isPartial
          ? `Os ${processedRows} itens em escopo já validados não geraram apontamentos até este momento. Continue acompanhando a execução até a consolidação final do lote.`
          : "O arquivo passou pela validação sem pendências abertas. Ainda assim, preserve o PDF como artefato institucional do lote e mantenha esta versão da planilha como referência validada.";

      cleanSection.innerHTML = `
        <div class="panel-kicker">Resultado do lote</div>
        <h2 class="panel-title">${escapeHtml(title)}</h2>
        <p>${escapeHtml(detail)}</p>
      `;
      cleanSection.classList.remove("hidden");
    }

    function resetResultWorkspace() {
      resetProblemVisibilityState();
      summarySection.classList.add("hidden");
      prioritySection.classList.add("hidden");
      actionsSection.classList.add("hidden");
      operationalExports.classList.add("hidden");
      duplicatesSection.classList.add("hidden");
      navSection.classList.add("hidden");
      cleanSection.classList.add("hidden");
      problemsSection.classList.add("hidden");
      operationalExports.innerHTML = "";
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
      if (job?.job_id) {
        currentJobId = job.job_id;
        syncCorrectedCsvDownload(job.job_id);
      }
      if (job?.validation_scope) {
        workspaceContext.validationScope = normalizeValidationScope(job.validation_scope);
      }
      renderProcessCard(job);

      if (job?.status === "canceled") {
        resetResultWorkspace();
        renderStateBanner(
          "warning",
          "Processamento cancelado",
          job?.status_detail || "O lote foi interrompido antes da consolidação final."
        );
        setEmptyState(
          "O lote foi cancelado",
          "Nenhum artefato final foi consolidado para este processamento. Você pode reenviar o arquivo quando quiser iniciar um novo lote."
        );
        return;
      }

      if (job?.cancel_requested) {
        resetResultWorkspace();
        renderStateBanner(
          "warning",
          "Cancelamento solicitado",
          job?.status_detail || "O lote será interrompido assim que a etapa segura atual terminar."
        );
        setEmptyState(
          "Encerrando o lote atual",
          "O sistema está finalizando a etapa segura em andamento antes de interromper o processamento e remover este job da fila ativa."
        );
        return;
      }

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
        const previewSummary = previewData.summary || {};
        const previewValidatedRows = getValidatedTotalRows(previewSummary);
        const previewSourceTotalRows = getSourceTotalRows(previewSummary);
        renderStateBanner(
          "warning",
          "Prévia em atualização",
          `Os dados abaixo refletem ${job.processed_rows || 0} de ${previewValidatedRows} itens em escopo já validados.${previewSourceTotalRows !== previewValidatedRows ? ` O CSV original tem ${previewSourceTotalRows} linhas.` : ""} O PDF permanece reservado para o fechamento final do lote.`
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
      if (job?.job_id) {
        currentJobId = job.job_id;
        syncCorrectedCsvDownload(job.job_id);
      }
      if (job?.validation_scope) {
        workspaceContext.validationScope = normalizeValidationScope(job.validation_scope);
      }
      renderProcessCard(job);
      renderStateBanner(
        "success",
        "Resultado final consolidado",
        buildFinalScopeCopy(workspaceContext.validationScope)
      );
      renderReportWorkspace(reportData, { mode: "final", processedRows: reportData.summary?.total_rows });
      downloadPdfLink.href = `/jobs/${job.job_id}/report`;
      downloadJsonLink.href = `/jobs/${job.job_id}/result`;
      renderOperationalExports(reportData);
      actionsSection.classList.remove("hidden");
      updateCorrectionSection();
    }

    async function handleEditClick(button) {
      const rowIndexRaw = button.getAttribute("data-row-index");
      const field = button.getAttribute("data-field");
      const itemLabel = button.getAttribute("data-item");

      if (!currentJobId) {
        renderStateBanner(
          "error",
          "Edição indisponível",
          "Nenhum job ativo foi identificado para registrar a correção."
        );
        return;
      }

      if (!rowIndexRaw || !field) {
        renderStateBanner(
          "warning",
          "Edição não permitida",
          "Este apontamento não possui um campo editável associado no CSV."
        );
        return;
      }

      const rowIndex = Number(rowIndexRaw);
      if (!Number.isInteger(rowIndex) || rowIndex < 0) {
        renderStateBanner(
          "error",
          "Edição inválida",
          "O índice da linha não foi reconhecido pelo sistema."
        );
        return;
      }

      try {
        await openEditModal(rowIndex, field, itemLabel);
      } catch (error) {
        renderStateBanner(
          "error",
          "Falha ao corrigir",
          error.message || "Não foi possível carregar o valor atual no CSV."
        );
      }
    }

    async function fetchJobStatus(jobId) {
      const response = await fetch(`/jobs/${jobId}`);
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao carregar o estado do job.");
      }
      return payload;
    }

    async function openJob(jobId) {
      const job = await fetchJobStatus(jobId);
      if (job.status === "completed") {
        const reportData = await fetchJobResult(jobId);
        renderFinalJob(job, reportData);
        return;
      }

      renderLiveJob(job);
    }

    async function cancelJob(jobId) {
      const response = await fetch(`/jobs/${jobId}/cancel`, {
        method: "POST",
      });
      const payload = await response.json();
      if (!response.ok) {
        throw new Error(payload.detail || "Falha ao solicitar o cancelamento do job.");
      }

      if (jobId === currentJobId) {
        renderLiveJob(payload);
      }

      renderStateBanner(
        "warning",
        payload.status === "canceled" ? "Processamento cancelado" : "Cancelamento solicitado",
        payload.status_detail || "O lote será interrompido em uma etapa segura."
      );
      await refreshJobsPanel();
      return payload;
    }

    async function fetchJobResult(jobId) {
      const resultResponse = await fetch(`/jobs/${jobId}/result`);
      const reportData = await resultResponse.json();
      if (!resultResponse.ok) {
        throw new Error(reportData.detail || "Falha ao carregar o resultado estruturado do lote.");
      }
      return reportData;
    }

    async function finalizeJob(jobId) {
      const job = await waitForJob(jobId);
      if (job.status === "canceled") {
        renderLiveJob(job);
        return;
      }
      if (job.status !== "completed") {
        throw new Error(job.error_message || job.status_detail || "O lote terminou com falha.");
      }

      const reportData = await fetchJobResult(jobId);
      renderFinalJob(job, reportData);
    }

    async function startJobFlow(uploadPayload, fileNameOverride = null) {
      workspaceContext.validationScope = normalizeValidationScope(
        uploadPayload.validation_scope || workspaceContext.validationScope
      );
      await refreshJobsPanel();
      renderLiveJob({
        job_id: uploadPayload.job_id,
        status: uploadPayload.status,
        validation_scope: workspaceContext.validationScope,
        current_step: "file_received",
        status_title: "Arquivo recebido",
        status_detail: "O lote foi registrado e entrará na etapa de leitura em seguida.",
        file_name: fileNameOverride || workspaceContext.fileName,
        updated_at: new Date().toISOString(),
      });

      await finalizeJob(uploadPayload.job_id);
    }

    async function handleReprocessClick() {
      if (!currentJobId || !hasPendingCorrections) {
        return;
      }

      reprocessButton.disabled = true;
      reprocessButton.textContent = "Reprocessando...";
      closeEditModal();
      closeDuplicateModal();
      resetResultWorkspace();
      emptyState.classList.add("hidden");

      try {
        const response = await fetch(`/jobs/${currentJobId}/reprocess`, {
          method: "POST",
        });
        const payload = await response.json();
        if (!response.ok) {
          throw new Error(payload.detail || "Falha ao iniciar o reprocessamento.");
        }

        clearCorrectionsPending();
        await startJobFlow(payload, workspaceContext.fileName);
      } catch (error) {
        renderStateBanner(
          "error",
          "Falha ao reprocessar",
          error.message || "Não foi possível iniciar um novo processamento para o lote corrigido."
        );
      } finally {
        reprocessButton.disabled = false;
        reprocessButton.textContent = "Reprocessar lote";
      }
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

        if (payload.status === "canceled") {
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

    editCancelButton.addEventListener("click", closeEditModal);
    editSaveButton.addEventListener("click", saveEditModal);
    duplicateCancelButton.addEventListener("click", closeDuplicateModal);
    duplicateSaveButton.addEventListener("click", saveDuplicateModal);
    reprocessButton.addEventListener("click", handleReprocessClick);

    editModal.addEventListener("click", (event) => {
      if (event.target === editModal) {
        closeEditModal();
      }
    });

    duplicateModal.addEventListener("click", (event) => {
      if (event.target === duplicateModal) {
        closeDuplicateModal();
      }
    });

    fileInput.addEventListener("change", () => {
      const selected = fileInput.files?.[0];
      workspaceContext.fileName = selected ? selected.name : null;
      fileName.textContent = selected ? selected.name : "Nenhum arquivo selecionado.";
    });

    tenantInput.addEventListener("change", () => {
      workspaceContext.organizationLabel = tenantInput.options[tenantInput.selectedIndex]?.text || "-";
      renderLiveJob();
    });

    validationScopeInputs.forEach((input) => {
      input.addEventListener("change", () => {
        workspaceContext.validationScope = getSelectedValidationScope();
      });
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
      workspaceContext.validationScope = getSelectedValidationScope();
      clearCorrectionsPending();
      closeEditModal();
      closeDuplicateModal();
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
        validation_scope: workspaceContext.validationScope,
        updated_at: new Date().toISOString(),
      });

      const formData = new FormData();
      formData.append("file", fileInput.files[0]);

      try {
        const uploadResponse = await fetch(`/validate?tenant_id=${encodeURIComponent(tenantInput.value)}&validation_scope=${encodeURIComponent(workspaceContext.validationScope)}`, {
          method: "POST",
          body: formData,
        });
        const uploadPayload = await uploadResponse.json();

        if (!uploadResponse.ok) {
          throw new Error(uploadPayload.detail || "Falha ao enviar o lote.");
        }

        await startJobFlow(uploadPayload, workspaceContext.fileName);
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
        refreshJobsPanel().catch(() => {});
      }
    });

    refreshJobsPanel().catch(() => {});
    setInterval(() => {
      refreshJobsPanel().catch(() => {});
    }, 2000);

    renderLiveJob();
  </script>
</body>
</html>
"""

    return html.replace("__TENANT_OPTIONS__", tenant_options)
