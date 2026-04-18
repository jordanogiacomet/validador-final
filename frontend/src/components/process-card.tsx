import React from "react";

import {
  PROCESS_STEPS,
  buildProcessGuidance,
  formatDateTime,
  formatStatusChip,
  getValidationScopeLabel,
} from "@/lib/presentation";
import type { JobStatusResponse, ValidationScope } from "@/lib/types";

interface ProcessCardProps {
  job: JobStatusResponse | null;
  organizationLabel: string;
  fallbackFileName: string | null;
  validationScope: ValidationScope;
}

export function ProcessCard({
  job,
  organizationLabel,
  fallbackFileName,
  validationScope,
}: ProcessCardProps) {
  const chip = formatStatusChip(job);
  const activeIndex = PROCESS_STEPS.findIndex((step) => step.id === job?.current_step);
  const isFailed = job?.status === "failed";
  const guidance = buildProcessGuidance(job);

  return (
    <section className="panel process-card">
      <div className="process-header">
        <div>
          <div className="panel-kicker">2. Acompanhar o lote</div>
          <h2 className="status-title">{job?.status_title || "Aguardando uma nova planilha"}</h2>
          <p className="status-detail">
            {job?.status_detail || "Assim que você enviar um CSV, a conferência aparece aqui."}
          </p>
        </div>
        <span className={`status-chip ${chip.kind}`}>{chip.label}</span>
      </div>

      <div className="lot-grid">
        <section className="lot-card lot-card-emphasis">
          <div className="panel-kicker">Próximo passo</div>
          <strong className="lot-guidance-title">{guidance.title}</strong>
          <p className="lot-guidance-copy">{guidance.detail}</p>
        </section>

        <section className="lot-card">
          <div className="panel-kicker">Resumo do lote</div>
          <dl className="lot-metadata">
            <div>
              <dt>Empresa</dt>
              <dd>{organizationLabel || "-"}</dd>
            </div>
            <div>
              <dt>Arquivo</dt>
              <dd>{job?.file_name || fallbackFileName || "-"}</dd>
            </div>
            <div>
              <dt>Código do lote</dt>
              <dd>{job?.job_id || "-"}</dd>
            </div>
            <div>
              <dt>Última atualização</dt>
              <dd>{formatDateTime(job?.updated_at)}</dd>
            </div>
            <div>
              <dt>Conferência</dt>
              <dd>{getValidationScopeLabel(job?.validation_scope || validationScope)}</dd>
            </div>
          </dl>
        </section>

        <section className="lot-card">
          <div className="panel-kicker">Andamento</div>
          <ol className="step-list">
            {PROCESS_STEPS.map((step, index) => {
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

              return (
                <li className={`step-item ${state}`} key={step.id}>
                  <span className="step-dot">{state === "complete" ? "OK" : index + 1}</span>
                  <div>
                    <strong>{step.label}</strong>
                    <span>{step.detail}</span>
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      </div>
    </section>
  );
}
