import { PROCESS_STEPS, formatDateTime, formatStatusChip, getValidationScopeLabel } from "@/lib/presentation";
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

  return (
    <section className="panel process-card">
      <div className="process-header">
        <div>
          <div className="panel-kicker">Lote atual</div>
          <h2 className="status-title">
            {job?.status_title || "Pronto para receber um novo arquivo"}
          </h2>
          <p className="status-detail">
            {job?.status_detail ||
              "Envie um CSV para acompanhar o processamento."}
          </p>
        </div>
        <span className={`status-chip ${chip.kind}`}>{chip.label}</span>
      </div>

      <div className="lot-grid">
        <section className="lot-card">
          <div className="panel-kicker">Identificação</div>
          <dl className="lot-metadata">
            <div>
              <dt>Organização</dt>
              <dd>{organizationLabel || "-"}</dd>
            </div>
            <div>
              <dt>Arquivo</dt>
              <dd>{job?.file_name || fallbackFileName || "-"}</dd>
            </div>
            <div>
              <dt>Job</dt>
              <dd>{job?.job_id || "-"}</dd>
            </div>
            <div>
              <dt>Atualizado em</dt>
              <dd>{formatDateTime(job?.updated_at)}</dd>
            </div>
            <div>
              <dt>Escopo</dt>
              <dd>{getValidationScopeLabel(job?.validation_scope || validationScope)}</dd>
            </div>
          </dl>
        </section>

        <section className="lot-card">
          <div className="panel-kicker">Etapas</div>
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
